import google.genai as genai
from google.genai.types import Tool, GoogleSearch, GenerateContentConfig, Content, Part, GenerateImagesConfig, FunctionDeclaration, FunctionCall
import os
import json
import traceback
from typing import Optional
from langchain_core.messages import HumanMessage
from PIL import Image
from io import BytesIO
import uuid

import config_manager
from utils import save_message_to_log
from character_manager import get_character_files_paths
from agent.graph import graph # グラフオブジェクトを直接インポート

# rag_manager のインポートは循環参照を避けるため、関数内ローカルインポートに移動させるか、
# DI (Dependency Injection) を検討する必要がありますが、一旦現状のまま進めます。
# TODO: rag_manager のインポート方法を再検討
import rag_manager


_gemini_client = None

def configure_google_api(api_key_name):
    """
    APIキーを元にGoogle GenAI Clientを初期化する関数。
    """
    if not api_key_name: return False, "APIキー名が指定されていません。"
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return False, f"APIキー名 '{api_key_name}' に対応する有効なAPIキーが設定されていません。"
    try:
        global _gemini_client
        _gemini_client = genai.Client(api_key=api_key)
        # LangChain用のGoogle APIキーも設定
        os.environ['GOOGLE_API_KEY'] = api_key
        print(f"Google GenAI Client and LangChain environment for API key '{api_key_name}' initialized successfully.")
        return True, None
    except Exception as e:
        return False, f"APIキー '{api_key_name}' での genai.Client 初期化中にエラー: {e}"

def invoke_rag_graph(character_name: str, user_prompt: str, api_history_limit_option: str):
    """
    ユーザープロンプトを受け取り、RAG + 思考プロセスを実行するLangGraphを呼び出す。
    これが今後のAIとの対話の唯一の窓口となる。
    """
    if not user_prompt.strip():
        return "エラー: メッセージが空です。", None

    try:
        # LangGraphの入力形式を作成
        inputs = {
            "messages": [HumanMessage(content=user_prompt)],
            "character_name": character_name,
            "api_history_limit_option": api_history_limit_option
        }

        # スレッドIDとしてキャラクター名を指定して、グラフを呼び出す
        # これにより、キャラクターごとに会話の状態が正しく保存・管理される
        final_state = graph.invoke(
            inputs,
            config={"configurable": {"thread_id": character_name}}
        )

        # 最終状態のmessagesリストから、最後のメッセージ（AIの応答）を取得
        ai_response_message = final_state["messages"][-1]

        # AIの応答テキストを返す
        api_response_text = ai_response_message.content

        # 現時点では画像生成機能はないため、image_pathはNoneを返す
        generated_image_path = None

        return api_response_text, generated_image_path

    except Exception as e:
        traceback.print_exc()
        return f"エラー: グラフの実行中に予期しないエラーが発生しました: {e}", None

def send_alarm_to_gemini(character_name, theme, flash_prompt_template, alarm_model_name, api_key_name, log_file_path, alarm_api_history_turns):
    # (この関数の実装は変更ありません)
    print(f"--- アラーム応答生成開始 (google-genai SDK, client.models.generate_content) --- キャラ: {character_name}, テーマ: '{theme}'")
    if _gemini_client is None:
        print("警告: _gemini_client is None in send_alarm_to_gemini. Attempting to configure with provided api_key_name.")
        config_success, config_msg = configure_google_api(api_key_name)
        if not config_success:
            return f"【アラームエラー】APIキー設定失敗: {config_msg}"
        if _gemini_client is None:
            return "【アラームエラー】Geminiクライアントが初期化されていません。"

    sys_ins_text = ""
    if flash_prompt_template:
        sys_ins_text = flash_prompt_template.replace("[キャラクター名]", character_name).replace("[テーマ内容]", theme)
        sys_ins_text += "\n\n**重要:** あなたの思考過程、応答の候補、メタテキスト（例: ---）などは一切出力せず、ユーザーに送る最終的な短いメッセージ本文のみを生成してください。"
    elif theme:
        sys_ins_text = f"""あなたはキャラクター「{character_name}」です。
以下のテーマについて、ユーザーに送る短いメッセージを生成してください。
過去の会話履歴があれば参考にし、自然な応答を心がけてください。

テーマ: {theme}

重要: あなたの思考過程、応答の候補リスト、自己対話、マーカー（例: `---`）などは一切含めず、ユーザーに送る最終的な短いメッセージ本文のみを出力してください。"""

    _, _, _, memory_json_path = get_character_files_paths(character_name)
    if memory_json_path and os.path.exists(memory_json_path):
        try:
            with open(memory_json_path, "r", encoding="utf-8") as f: mem = json.load(f)
            m_api = {k: v for k, v in {
                "user_profile": mem.get("user_profile"),
                "self_identity": mem.get("self_identity"),
                "shared_language": mem.get("shared_language"),
                "current_context": mem.get("current_context"),
                "memory_summary": mem.get("memory_summary", [])[-config_manager.MEMORY_SUMMARY_LIMIT_FOR_API:]
            }.items() if v}
            if m_api: sys_ins_text += f"\n\n---\n## 参考記憶:\n{json.dumps(m_api, indent=2, ensure_ascii=False)}\n---"
        except Exception as e: print(f"記憶ファイル '{memory_json_path}' 読込/処理エラー (アラーム): {e}")

    api_contents_from_history = []
    if alarm_api_history_turns > 0:
        from utils import load_chat_log # ローカルインポート
        msgs = load_chat_log(log_file_path, character_name)
        limit_msgs = alarm_api_history_turns * 2
        if len(msgs) > limit_msgs: msgs = msgs[-limit_msgs:]

        th_pat = re.compile(r"【Thoughts】.*?【/Thoughts】\s*", re.DOTALL | re.IGNORECASE)
        img_pat = re.compile(r"\[Generated Image: [^\]]+\]")
        alrm_pat = re.compile(r"（システムアラーム：.*?）")

        for m in msgs:
            sdk_role = "user" if m.get("role") == "user" else "model"
            content_text = m.get("content", "")
            if not content_text: continue
            processed_text = content_text
            if sdk_role == "model": processed_text = th_pat.sub("", processed_text).strip()
            processed_text = img_pat.sub("", processed_text).strip()
            processed_text = alrm_pat.sub("", processed_text).strip()
            if processed_text:
                api_contents_from_history.append(Content(role=sdk_role, parts=[Part(text=processed_text)]))
        print(f"情報: アラーム応答生成のために、直近 {alarm_api_history_turns} 往復 ({len(api_contents_from_history)} 件) の整形済み履歴を参照します。")
    else:
        print("情報: アラーム応答生成では履歴を参照しません。")

    current_alarm_turn_content = api_contents_from_history
    if not current_alarm_turn_content or (current_alarm_turn_content and current_alarm_turn_content[-1].role == "model"):
        placeholder_text = "（時間になりました。アラームメッセージをお願いします。）" if not current_alarm_turn_content else "（続けて）"
        current_alarm_turn_content.append(Content(role="user", parts=[Part(text=placeholder_text)]))
        print(f"情報: API呼び出し用に形式的なユーザー入力 ('{placeholder_text}') を追加しました。")

    if not current_alarm_turn_content:
         return "【アラームエラー】内部エラー: 送信コンテンツ空"

    final_api_contents = []
    if sys_ins_text:
        print(f"デバッグ (alarm): Prepending system instruction to contents.")
        final_api_contents.append(Content(role="user", parts=[Part(text=sys_ins_text)]))
    final_api_contents.extend(current_alarm_turn_content)

    if not final_api_contents:
        return "【アラームエラー】最終送信コンテンツ空"

    formatted_safety_settings_for_api = []
    if config_manager.SAFETY_CONFIG:
        try:
            for category_enum, threshold_enum in config_manager.SAFETY_CONFIG.items():
                category_str = category_enum.name
                threshold_str = threshold_enum.name
                formatted_safety_settings_for_api.append({
                    "category": category_str,
                    "threshold": threshold_str
                })
            print(f"デバッグ (alarm): formatted_safety_settings_for_api (list of dicts with strings): {formatted_safety_settings_for_api}")
            if not formatted_safety_settings_for_api:
                formatted_safety_settings = None
            else:
                formatted_safety_settings = formatted_safety_settings_for_api
        except AttributeError as ae:
            print(f"警告 (alarm): categoryまたはthresholdに .name 属性がありません。category: {type(category_enum)}, threshold: {type(threshold_enum)}. Error: {ae}")
            formatted_safety_settings = None
        except Exception as e_ss_alarm:
            print(f"警告 (alarm): Error processing safety settings: {e_ss_alarm}. Safety settings may not be applied.")
            formatted_safety_settings = None
    else:
        formatted_safety_settings = None

    active_generation_config = None
    if formatted_safety_settings:
        try:
            active_generation_config = GenerateContentConfig(safety_settings=formatted_safety_settings)
        except Exception as e:
            print(f"警告: アラーム用 GenerateContentConfig の作成中にエラー: {e}.")

    print(f"アラーム用モデル ({alarm_model_name}, client.models.generate_content) へ送信開始... 送信contents件数: {len(final_api_contents)}")
    try:
        gen_content_args = {
            "model": alarm_model_name,
            "contents": final_api_contents
        }
        if active_generation_config:
            gen_content_args["config"] = active_generation_config

        response = _gemini_client.models.generate_content(**gen_content_args)

    except Exception as e:
        if "BlockedPromptException" in str(type(e)) or "StopCandidateException" in str(type(e)):
             print(f"アラームAPI呼び出しでブロックまたは停止例外: {e}")
             return f"【アラームエラー】プロンプトブロックまたは候補生成停止"

        print(f"アラーム用モデル ({alarm_model_name}, google-genai) との通信中にエラーが発生しました: {traceback.format_exc()}")
        return f"【アラームエラー】API通信失敗: {e}"

    final_text_response = None
    try:
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            text_parts = [part.text for part in response.candidates[0].content.parts if hasattr(part, 'text')]
            final_text_response = "".join(text_parts)

        if final_text_response is None or not final_text_response.strip():
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback and response.prompt_feedback.block_reason:
                block_reason_str = str(response.prompt_feedback.block_reason)
                return f"【アラームエラー】応答取得失敗。ブロック理由: {block_reason_str}"
            if final_text_response is None:
                 final_text_response = "【アラームエラー】モデルから空の応答または非テキスト応答が返されました。"

        if final_text_response.strip().startswith("```"):
            return final_text_response.strip()
        else:
            return re.sub(r"^\s*([-*_#=`>]+|\n)+\s*", "", final_text_response.strip())

    except Exception as e:
        print(f"アラーム応答テキストの処理中にエラー: {e}")
        if hasattr(response, 'prompt_feedback') and response.prompt_feedback and response.prompt_feedback.block_reason:
            return f"【アラームエラー】応答処理エラー ({e}) ブロック理由: {response.prompt_feedback.block_reason}"
        return f"【アラームエラー】応答処理エラー ({e}) ブロック理由は不明"

def generate_image_with_gemini(prompt: str, output_image_filename_suggestion: str, character_name: str) -> tuple[Optional[str], Optional[str]]:
    # (この関数の実装は変更ありません)
    if _gemini_client is None:
        return "エラー: Geminiクライアントが初期化されていません。APIキーを設定してください。", None
    model_name = "gemini-1.5-pro-latest"
    try:
        print(f"--- Gemini 画像生成開始 (model: {model_name}) --- プロンプト: '{prompt[:100]}...'")
        response = _gemini_client.models.generate_content(
            model=model_name,
            contents=[prompt],
        )

        image_data = None
        generated_text = None
        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts:
                if "image" in part.mime_type: # Simple check, might need to be more robust
                    image_data = part.data
                if "text" in part.mime_type: # Simple check
                    generated_text = part.text

        if image_data:
            char_base_path = os.path.join("characters", character_name)
            save_dir = os.path.join(char_base_path, "images")
            os.makedirs(save_dir, exist_ok=True)

            base_name = re.sub(r'[^\w\s-]', '', os.path.splitext(output_image_filename_suggestion)[0]).strip().replace(' ', '_')
            if not base_name: base_name = "gemini_image"
            unique_id = uuid.uuid4().hex[:8]
            image_filename = f"{base_name}_{unique_id}.png"

            absolute_image_path = os.path.abspath(os.path.join(save_dir, image_filename))
            relative_image_path = os.path.join(save_dir, image_filename).replace("\\", "/")

            image = Image.open(BytesIO(image_data))
            image.save(absolute_image_path)

            print(f"生成された画像を '{absolute_image_path}' に保存しました。")
            return generated_text or "画像を生成しました。", relative_image_path
        else:
            # If no image data, but text was generated, return the text.
            if generated_text:
                return generated_text, None
            return "画像生成に失敗しました。", None # Default if neither image nor text

    except Exception as e:
        error_msg = f"エラー: Gemini画像生成中に予期しないエラーが発生しました: {e}"
        print(error_msg)
        traceback.print_exc()
        return error_msg, None
