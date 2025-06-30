import google.genai as genai
from google.genai.types import Tool, GoogleSearch, GenerateContentConfig, Content, Part, GenerateImagesConfig, FunctionDeclaration, FunctionCall
import os
import json
import rag_manager
import google.api_core.exceptions
import re
import traceback
from typing import Optional
from langchain_core.messages import HumanMessage

import config_manager
from utils import save_message_to_log # load_chat_log は不要になる
from character_manager import get_character_files_paths
# from agent.graph import graph # 新しく作成したグラフをインポート <- 循環参照のためコメントアウト

_gemini_client = None

def configure_google_api(api_key_name):
    """
    APIキーを元にGoogle GenAI Clientを初期化する関数。（変更なし）
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

def invoke_rag_graph(graph_obj, character_name: str, user_prompt: str): # graph_obj を引数に追加
    """
    ユーザープロンプトを受け取り、RAG + 思考プロセスを実行するLangGraphを呼び出す。
    これが今後のAIとの対話の唯一の窓口となる。
    """
    if not graph_obj:
        return "エラー: LangGraphオブジェクトが提供されていません。", None
    if not user_prompt.strip():
        return "エラー: メッセージが空です。", None

    try:
        # LangGraphの入力形式を作成
        inputs = {
            "messages": [HumanMessage(content=user_prompt)],
            "character_name": character_name,
        }

        # グラフを実行し、最終的な結果を取得
        # .invoke()は、すべてのノードの処理が終わった後の最終状態を返す
        final_state = graph_obj.invoke(inputs) # graph を graph_obj に変更

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

# --- send_alarm_to_gemini と generate_image_with_gemini は変更なし ---
# (既存のコードをここに維持してください)
# (ただし、古いsend_to_geminiは削除されていることを確認してください)

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

from PIL import Image
from io import BytesIO
import uuid

def generate_image_with_gemini(prompt: str, output_image_filename_suggestion: str, character_name: str) -> tuple[Optional[str], Optional[str]]:
    # (この関数の実装は変更ありません)
    if _gemini_client is None:
        return "エラー: Geminiクライアントが初期化されていません。APIキーを設定してください。", None
    model_name = "gemini-1.0-pro" # Note: Update to a model that supports image generation if needed.
    try:
        print(f"--- Gemini 画像生成開始 (model: {model_name}) --- プロンプト: '{prompt[:100]}...'")
        generation_config = GenerateImagesConfig(prompt=prompt)
        response = _gemini_client.generate_images(model=model_name, config=generation_config)

        # This part needs to be adapted based on the actual response structure for image generation
        # The following is a placeholder based on common patterns.
        if response.images:
            image_data = response.images[0].data # Assuming the first image's data
            # ★★★ ここからが修正箇所 ★★★
            # キャラクターごとの画像保存ディレクトリを決定
            char_base_path = os.path.join("characters", character_name)
            save_dir = os.path.join(char_base_path, "images")
            os.makedirs(save_dir, exist_ok=True)

            base_name = re.sub(r'[^\w\s-]', '', os.path.splitext(output_image_filename_suggestion)[0]).strip().replace(' ', '_')
            if not base_name: base_name = "gemini_image"
            unique_id = uuid.uuid4().hex[:8]
            # MIMEタイプに基づいて拡張子を決定する仮定（実際のAPI応答構造に依存）
            # ここでは .png をデフォルトとしますが、実際のAPI応答からMIMEタイプを取得して適切な拡張子を設定すべきです。
            # 例えば、response.images[0].mime_type などで取得できるかもしれません。
            # この例では image_mime_type 変数がないため、一旦 .png に固定します。
            # img_ext = ".png"
            # if image_mime_type == "image/jpeg": img_ext = ".jpg"
            # elif image_mime_type == "image/webp": img_ext = ".webp"
            # image_filename = f"{base_name}_{unique_id}{img_ext}"
            image_filename = f"{base_name}_{unique_id}.png" # 仮にpngに固定

            # image_pathは、Gradioが表示するための「絶対パス」
            image_path_absolute = os.path.abspath(os.path.join(save_dir, image_filename))

            # log_pathは、ログに記録し、将来どこでも使えるようにするための「相対パス」
            image_path_relative = os.path.join(save_dir, image_filename).replace("\\", "/")
            image_path_for_log = None # 初期化

            try:
                image = Image.open(BytesIO(image_data))
                # if img_ext == ".jpg" and image.mode == 'RGBA': # img_extが固定なので不要
                #     image = image.convert('RGB')
                if image_filename.endswith(".jpg") and image.mode == 'RGBA': # 拡張子で判定
                    image = image.convert('RGB')
                # 絶対パスで画像を保存
                image.save(image_path_absolute)
                print(f"生成された画像を '{image_path_absolute}' に保存しました。")
                # ログ記録用に相対パスを返す
                image_path_for_log = image_path_relative

            except Exception as img_e:
                error_message = f"エラー: 画像データの処理または保存中にエラーが発生しました: {img_e}"
                print(error_message)
                traceback.print_exc()
                return error_message, None # エラー時はNoneを返す

            return "画像を生成しました。", image_path_for_log
        else:
            return "画像生成に失敗しました。応答に画像データが含まれていません。", None

    except Exception as e:
        error_msg = f"エラー: Gemini画像生成中に予期しないエラーが発生しました: {e}"
        print(error_msg)
        traceback.print_exc()
        return error_msg, None
