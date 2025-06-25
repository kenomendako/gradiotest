# -*- coding: utf-8 -*-
# ##############################################################################
# #                                                                            #
# #  ! ! ! ! ! ! ! ! ! ! !   CRITICAL AI INSTRUCTION   ! ! ! ! ! ! ! ! ! ! ! !  #
# #                                                                            #
# #   THIS FILE MUST USE THE `google-genai` SDK.                               #
# #   DO NOT use the deprecated `google-generativeai` library.                 #
# #                                                                            #
# #   Correct Import: `from google import genai`                               #
# #   Incorrect Import: `import google.generativeai as genai`                  #
# #                                                                            #
# #   Refer to `AI_DEVELOPMENT_GUIDELINES.md` for details.                     #
# #                                                                            #
# # ! ! ! ! ! ! ! ! ! ! !   AIへの最重要指示   ! ! ! ! ! ! ! ! ! ! ! ! #
# #                                                                            #
# #   このファイルは `google-genai` SDK を使用します。                         #
# #   非推奨の `google-generativeai` ライブラリは使用禁止です。                #
# #                                                                            #
# #   正しいImport: `from google import genai`                                 #
# #   間違いのImport: `import google.generativeai as genai`                    #
# #                                                                            #
# #   詳細は `AI_DEVELOPMENT_GUIDELINES.md` を参照してください。               #
# #                                                                            #
# ##############################################################################
import google.genai as genai
# from google.genai import types # types は Content, Part で直接指定するため不要に
from google.genai.types import Tool, GoogleSearch, GenerateContentConfig, Content, Part, GenerateImagesConfig, FunctionDeclaration, FunctionCall # Content, Part を明示的にインポート
import os
import json
import rag_manager # 追加
import google.api_core.exceptions
import re
import math
import traceback
import base64
from PIL import Image
from io import BytesIO # Specific import for BytesIO
from typing import Optional # Added for type hinting
import io # Keep original io import if other parts of the file use it directly
import uuid
import config_manager
from utils import load_chat_log, save_message_to_log, convert_chat_log_to_langchain_format
from character_manager import get_character_files_paths, get_character_log_path # get_character_log_path を追加
import rag_graph # rag_graph.py をインポート
from langchain_core.messages import HumanMessage, AIMessage # LangChainのメッセージ型

_gemini_client = None
_rag_graph_instance = None # グローバルなRAGグラフインスタンス

# ★★★ 1. ツールの定義を、進化させる ★★★
def _define_image_generation_tool():
    """
    AIに「次に何をすべきか」を判断させるための、新しいツールセットを定義します。
    """
    return Tool(
        function_declarations=[
            # 行動計画を立てさせるための、新しい関数
            FunctionDeclaration(
                name="plan_next_action",
                description="ユーザーのリクエストに応じて、次に取るべき行動を計画します。返答するだけか、画像を生成するかを決定します。",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "action_type": {
                            "type": "STRING",
                            "description": "実行するアクションの種類。'TALK' または 'GENERATE_IMAGE' のいずれか。",
                            "enum": ["TALK", "GENERATE_IMAGE"]
                        },
                        "details": {
                            "type": "STRING",
                            "description": "アクションの詳細。action_typeが'TALK'の場合は応答テキスト、'GENERATE_IMAGE'の場合は画像生成用の英語プロンプト。"
                        }
                    },
                    "required": ["action_type", "details"]
                }
            )
        ]
    )

# --- Google API (Gemini) 連携関数 ---
def configure_google_api(api_key_name=None): # api_key_name はオプションに
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key == "YOUR_API_KEY_HERE":
        # .envファイルから取得できなかった場合、config.jsonの古いキーを参照する（互換性のため）
        # ただし、将来的にはこのフォールバックは削除するべき
        if api_key_name and config_manager.API_KEYS.get(api_key_name):
            api_key = config_manager.API_KEYS.get(api_key_name)
            print(f"警告: GEMINI_API_KEYが.envファイルに設定されていません。古いconfig.jsonのキー '{api_key_name}' を使用します。")
        else:
            return False, "有効なGEMINI_API_KEYが.envファイルに設定されていません。"

    try:
        global _gemini_client
        _gemini_client = genai.Client(api_key=api_key)
        # APIキー名をログに出力しないように変更
        print(f"Google GenAI Client initialized successfully using API key from environment variable.")
        return True, None
    except Exception as e:
        # APIキー名をログに出力しないように変更
        return False, f"genai.Client 初期化中にエラー: {e}"

# ★★★ 2. APIとの対話方法を、根本的に、変更する ★★★
def send_to_gemini(system_prompt_path, log_file_path, user_prompt, selected_model, character_name, send_thoughts_to_api, api_history_limit_option, uploaded_file_parts: list = None, memory_json_path=None):
    if _gemini_client is None:
        return "エラー: Geminiクライアントが初期化されていません。", None

    # --- ステップ1: AIの「意思」を確認する ---
    print(f"--- 対話処理開始 (意思決定フェーズ) ---")

    # (プロンプトと履歴の準備：既存のロジックを流用)
    sys_ins_text = "あなたはチャットボットです。"
    # ... (この部分は既存のコードと同じなので省略) ...
    if system_prompt_path and os.path.exists(system_prompt_path):
        try:
            with open(system_prompt_path, "r", encoding="utf-8") as f: sys_ins_text = f.read().strip() or sys_ins_text
        except Exception as e: print(f"システムプロンプト '{system_prompt_path}' 読込エラー: {e}")
    if memory_json_path and os.path.exists(memory_json_path):
        try:
            with open(memory_json_path, "r", encoding="utf-8") as f: mem = json.load(f)
            m_api = {k: v for k, v in {
                "user_profile": mem.get("user_profile"), "self_identity": mem.get("self_identity"),
                "shared_language": mem.get("shared_language"), "current_context": mem.get("current_context"),
                "memory_summary": mem.get("memory_summary", [])[-config_manager.MEMORY_SUMMARY_LIMIT_FOR_API:]
            }.items() if v}
            if m_api: sys_ins_text += f"\n\n---\n## 参考記憶:\n{json.dumps(m_api, indent=2, ensure_ascii=False)}\n---"
        except Exception as e: print(f"記憶ファイル '{memory_json_path}' 読込/処理エラー: {e}")
    msgs = load_chat_log(log_file_path, character_name)
    if api_history_limit_option.isdigit():
        try:
            limit = int(api_history_limit_option)
            if limit > 0:
                limit_msgs = limit * 2
                if len(msgs) > limit_msgs: msgs = msgs[-limit_msgs:]
        except ValueError: print(f"警告: api_history_limit_option '{api_history_limit_option}' は不正な数値です。")
    if msgs and msgs[-1].get("role") == "user": msgs = msgs[:-1]
    api_contents_from_history = []
    th_pat = re.compile(r"【Thoughts】.*?【/Thoughts】\s*", re.DOTALL | re.IGNORECASE)
    for m in msgs:
        sdk_role = "user" if m.get("role") == "user" else "model"
        content_text = m.get("content", "")
        if not content_text: continue
        processed_text = content_text
        if sdk_role == "user": processed_text = re.sub(r"\[画像添付:[^\]]+\]", "", processed_text).strip()
        elif sdk_role == "model" and not send_thoughts_to_api: processed_text = th_pat.sub("", processed_text).strip()
        if processed_text: api_contents_from_history.append(Content(role=sdk_role, parts=[Part(text=processed_text)]))
    current_turn_parts = []
    if user_prompt: current_turn_parts.append(Part(text=user_prompt))
    if uploaded_file_parts:
        for file_detail in uploaded_file_parts:
            file_path = file_detail['path']
            mime_type = file_detail['mime_type']
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'rb') as f_bytes: file_bytes = f_bytes.read()
                    encoded_data = base64.b64encode(file_bytes).decode('utf-8')
                    current_turn_parts.append(Part(inline_data={"mime_type": mime_type, "data": encoded_data}))
                except Exception as e: print(f"警告: ファイル '{os.path.basename(file_path)}' の処理中にエラー: {e}")
            else: print(f"警告: 指定されたファイルパス '{file_path}' が見つかりません。")

    # (プロンプト構築：既存のロジックを流用)
    final_api_contents = []
    if sys_ins_text:
        final_api_contents.append(Content(role="user", parts=[Part(text=sys_ins_text)]))
        final_api_contents.append(Content(role="model", parts=[Part(text="はい、承知いたしました。指示に従い、対話を開始します。")]))
    if user_prompt:
        relevant_chunks = rag_manager.search_relevant_chunks(character_name, user_prompt)
        if relevant_chunks:
            rag_context = "## 関連性の高い参考情報\n\n" + "\n\n---\n\n".join(relevant_chunks)
            final_api_contents.append(Content(role="user", parts=[Part(text=rag_context)]))
            final_api_contents.append(Content(role="model", parts=[Part(text="記憶とログから関連情報を参照しました。")]))
    final_api_contents.extend(api_contents_from_history)
    if current_turn_parts:
        final_api_contents.append(Content(role="user", parts=current_turn_parts))

    # (API呼び出し設定：既存のロジックを流用)
    action_planning_tool = _define_image_generation_tool() # 新しいツールセット
    formatted_safety_settings = []
    if config_manager.SAFETY_CONFIG and isinstance(config_manager.SAFETY_CONFIG, dict):
        for category, threshold in config_manager.SAFETY_CONFIG.items():
            formatted_safety_settings.append({"category": category, "threshold": threshold})

    try:
        generation_config = GenerateContentConfig(tools=[action_planning_tool], safety_settings=formatted_safety_settings)
        response = _gemini_client.models.generate_content(
            model=selected_model,
            contents=final_api_contents,
            config=generation_config
        )

        # ★★★ ここが、最後の、防波堤です ★★★
        # 応答候補が、そもそも、存在しない場合
        if not response.candidates:
            # 応答がブロックされた理由を確認する
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback.block_reason:
                reason = response.prompt_feedback.block_reason.name
                error_message = f"エラー: 応答がブロックされました。理由: {reason}"
                print(f"警告: {error_message}")
                return error_message, None
            else:
                # その他の理由で応答がない場合
                error_message = "エラー: モデルから有効な応答がありませんでした。（モデルの内部的な問題か、安全フィルター以外の理由でブロックされた可能性があります）"
                print(f"警告: {error_message}")
                return error_message, None

        candidate = response.candidates[0]

        # (以降の処理は、変更ありません)
        # AIがツールを使わずに、ただテキストを返してきた場合
        if not candidate.content or not candidate.content.parts or not candidate.content.parts[0].function_call:
            print("情報: AIの意思は 'TALK' です。")
            final_text_parts = [part.text for part in candidate.content.parts if hasattr(part, 'text') and part.text is not None]
            final_text = "".join(final_text_parts).strip()
            return final_text, None

        # AIが行動計画ツールを呼び出した場合
        function_call = candidate.content.parts[0].function_call
        if function_call.name == "plan_next_action":
            args = function_call.args
            action_type = args.get("action_type")
            details = args.get("details", "")

            # --- ステップ2: AIの「意思」に基づき、コードが「実行」する ---
            if action_type == "GENERATE_IMAGE":
                # (この部分は変更ありません)
                # ...
                print(f"情報: AIの意思は 'GENERATE_IMAGE' です。プロンプト: '{details[:100]}...'")
                sanitized_base_name = "".join(c for c in details[:30] if c.isalnum() or c in [' ']).strip().replace(' ', '_')
                filename_suggestion = f"{character_name}_{sanitized_base_name}"
                text_response, image_path = generate_image_with_gemini(prompt=details, output_image_filename_suggestion=filename_suggestion)
                if not image_path:
                    return f"画像生成に失敗しました。理由: {text_response}", None
                print("情報: 画像生成成功。AIにコメント生成を依頼します。")
                comment_request_prompt = [*final_api_contents, Content(role="user", parts=[Part(text=f"（システム情報：画像生成に成功しました。画像パスは '{image_path}' です。この事実に基づき、ユーザーへの応答メッセージだけを、あなたの言葉で生成してください。）")])]
                comment_response = _gemini_client.models.generate_content(model=selected_model, contents=comment_request_prompt, config=GenerateContentConfig(safety_settings=formatted_safety_settings))
                comment_candidate = comment_response.candidates[0]
                comment_text_parts = [part.text for part in comment_candidate.content.parts if hasattr(part, 'text') and part.text is not None]
                final_comment = "".join(comment_text_parts).strip()
                return final_comment, image_path

            else: # action_type == "TALK"
                print("情報: AIの意思は 'TALK' (ツール経由) です。")
                return details, None
        else:
            return f"エラー: 不明な関数 '{function_call.name}' が呼び出されました。", None

    except google.api_core.exceptions.GoogleAPIError as e:
        return f"エラー: Gemini APIとの通信中にエラーが発生しました: {e}", None
    except Exception as e:
        traceback.print_exc()
        return f"エラー: Gemini APIとの通信中に予期しないエラーが発生しました: {e}", None

def send_alarm_to_gemini(character_name, theme, flash_prompt_template, alarm_model_name, api_key_name, log_file_path, alarm_api_history_turns):
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
        msgs = load_chat_log(log_file_path, character_name)
        limit_msgs = alarm_api_history_turns * 2
        if len(msgs) > limit_msgs: msgs = msgs[-limit_msgs:]

        th_pat = re.compile(r"【Thoughts】.*?【/Thoughts】\s*", re.DOTALL | re.IGNORECASE)
        img_pat = re.compile(r"\[画像添付:[^\]]+\]")
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

    generation_config_args = {}
    if formatted_safety_settings:
        generation_config_args["safety_settings"] = formatted_safety_settings

    active_generation_config = None
    if generation_config_args:
        try:
            active_generation_config = GenerateContentConfig(**generation_config_args)
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


def generate_image_with_gemini(prompt: str, output_image_filename_suggestion: str) -> tuple[Optional[str], Optional[str]]:
    """
    Generates an image using a Gemini model with response_modalities and saves it.
    This function is updated to use the specified image generation model and robustly parse its response.

    Args:
        prompt (str): The text prompt for image generation.
        output_image_filename_suggestion (str): A suggestion for the output image filename.

    Returns:
        tuple: (generated_text, image_path)
               generated_text (str or None): Text response from the model, if any.
               image_path (str or None): Path to the saved image, or None if generation failed.
    """
    if _gemini_client is None:
        return "エラー: Geminiクライアントが初期化されていません。APIキーを設定してください。", None

    # ユーザー指定の、テキスト・画像同時生成に特化したプレビューモデルを使用
    model_name = "gemini-2.0-flash-preview-image-generation"

    try:
        print(f"--- Gemini 画像生成開始 (model: {model_name}) --- プロンプト: '{prompt[:100]}...'")

        # テキストと画像の両方を出力するようモデルに要求
        generation_config = GenerateContentConfig(
            response_modalities=['TEXT', 'IMAGE']
        )

        # generate_contentを呼び出し
        response = _gemini_client.models.generate_content(
            model=model_name,
            contents=[prompt], # プロンプトはシンプルなリストで渡す
            config=generation_config
        )

        generated_text = None
        image_path = None
        error_message = None

        if not response.candidates:
            error_message = "画像生成エラー: モデルから有効な応答候補(candidate)がありませんでした。"
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback.block_reason:
                error_message += f" ブロック理由: {response.prompt_feedback.block_reason}"
            print(error_message)
            return error_message, None

        # --- 最新のSDK仕様に準拠した、安全な応答解析ロジック ---
        candidate = response.candidates[0]
        image_data = None
        image_mime_type = None

        # 1. 応答の全パートを安全にループして、テキストと画像を抽出
        for part in candidate.content.parts:
            if hasattr(part, 'text') and part.text:
                current_part_text = part.text.strip()
                if current_part_text:
                    generated_text = f"{generated_text}\n{current_part_text}" if generated_text else current_part_text
                    print(f"画像生成APIからテキスト部分を取得: {current_part_text[:100]}...")

            if hasattr(part, 'inline_data') and hasattr(part.inline_data, 'data') and part.inline_data.data:
                image_data = part.inline_data.data
                image_mime_type = part.inline_data.mime_type
                print(f"画像生成APIから画像データ (MIME: {image_mime_type}) を取得しました。")
                # 画像が見つかっても、他にテキストパートがある可能性があるのでループは継続

        # 2. 画像データが見つかった場合にファイルとして保存
        if image_data:
            _script_dir = os.path.dirname(os.path.abspath(__file__))
            save_dir = os.path.join(_script_dir, "chat_attachments", "generated_images")
            os.makedirs(save_dir, exist_ok=True)

            base_name_suggestion, _ = os.path.splitext(output_image_filename_suggestion)
            base_name = re.sub(r'[^\w\s-]', '', base_name_suggestion).strip()
            base_name = re.sub(r'[-\s]+', '_', base_name)
            if not base_name: base_name = "gemini_image"

            unique_id = uuid.uuid4().hex[:8]
            img_ext = ".png" # デフォルト
            if image_mime_type == "image/jpeg": img_ext = ".jpg"
            elif image_mime_type == "image/webp": img_ext = ".webp"

            image_filename = f"{base_name}_{unique_id}{img_ext}"
            temp_image_path = os.path.join(save_dir, image_filename)

            try:
                image = Image.open(BytesIO(image_data))
                if img_ext == ".jpg" and image.mode == 'RGBA':
                    image = image.convert('RGB')
                image.save(temp_image_path)
                image_path = temp_image_path
                print(f"生成された画像を '{image_path}' に保存しました。")
            except Exception as img_e:
                error_message = f"エラー: 画像データの処理または保存中にエラーが発生しました: {img_e}"
                print(error_message)
                traceback.print_exc()
                generated_text = f"{generated_text}\n{error_message}" if generated_text else error_message

        # 3. 画像もテキストもなかった場合の最終フォールバック
        if image_path is None and generated_text is None and error_message is None:
            error_message = "モデル応答にテキストまたは画像データが見つかりませんでした。"
            print(error_message)
            return error_message, None

    except google.api_core.exceptions.GoogleAPIError as e:
        error_msg = f"エラー: Gemini APIとの通信中にエラーが発生しました (画像生成): {e}"
        print(error_msg)
        traceback.print_exc()
        return error_msg, None
    except Exception as e:
        error_msg = f"エラー: Gemini画像生成中に予期しないエラーが発生しました: {e}"
        print(error_msg)
        traceback.print_exc()
        return error_msg, None

    return generated_text, image_path

# --- RAG Graph Invocation ---
async def invoke_rag_graph(
    user_prompt: str,
    character_name: str,
    selected_model: str, # rag_graph.pyのcurrent_model_nameに渡す
    # log_file_path: str, # utils.load_chat_log と rag_manager.search_relevant_chunks で使用
    # memory_json_path: str, # 現在rag_graphでは直接使用していないが、将来的に渡す可能性
    api_history_limit_option: str # 履歴の長さを制御
    # uploaded_file_parts: list = None # rag_graphでは現在未対応
) -> str:
    """
    RAGベースのLangGraphを実行し、AIの応答を取得する非同期関数。
    """
    global _rag_graph_instance
    if _rag_graph_instance is None:
        print("情報: RAGグラフインスタンスを初回ビルドします。")
        _rag_graph_instance = rag_graph.build_rag_graph()
        if _rag_graph_instance is None:
            return "エラー: RAGグラフのビルドに失敗しました。"

    if _gemini_client is None:
        # configure_google_api は同期的だが、アプリケーション起動時に呼ばれる想定
        # ここで呼ばれるのはフォールバックに近い
        print("警告: Geminiクライアントが初期化されていません。configure_google_apiを試みます。")
        # api_key_name は configure_google_api の引数だが、.env優先なのでNoneでも動作するはず
        success, msg = configure_google_api()
        if not success:
            return f"エラー: Geminiクライアントの初期化に失敗しました: {msg}"
        if _gemini_client is None: # 再度確認
             return "エラー: Geminiクライアントの初期化に致命的に失敗しました。"


    # 1. RAG検索の実行
    # log_file_path は character_name から取得できる
    log_file_path = get_character_log_path(character_name) # character_managerから取得
    relevant_chunks = rag_manager.search_relevant_chunks(character_name, user_prompt, log_file_path)

    # 2. 会話履歴の読み込みと変換
    # utils.load_chat_log は {"role": "user/assistant", "content": "..."} のリストを返す
    # これをLangChainのBaseMessage形式に変換する必要がある
    raw_history = load_chat_log(log_file_path, character_name) # log_file_pathを渡す

    # api_history_limit_option に基づいて履歴を制限
    if api_history_limit_option.isdigit():
        try:
            limit = int(api_history_limit_option)
            if limit > 0:
                # ユーザーとAIの発言ペアで1往復なので、limit * 2 がメッセージ数
                # さらに、ユーザーの現在の入力が追加されるので、それより1つ少なく取得
                num_messages_to_keep = max(0, limit * 2 -1) # 負にならないように
                if len(raw_history) > num_messages_to_keep:
                    raw_history = raw_history[-num_messages_to_keep:]
        except ValueError:
            print(f"警告: api_history_limit_option '{api_history_limit_option}' は不正な数値です。履歴制限は適用されません。")


    # LangChain形式のメッセージリストに変換
    # convert_chat_log_to_langchain_format は utils.py に追加する必要がある
    langchain_messages = convert_chat_log_to_langchain_format(raw_history)

    # 現在のユーザープロンプトを履歴に追加
    current_user_message = HumanMessage(content=user_prompt)
    # langchain_messages.append(current_user_message) # GraphStateのmessagesへの追加はAnnotatedで行う

    # 3. GraphStateの初期化
    initial_graph_state = rag_graph.GraphState(
        messages=[current_user_message], # 最初の入力として現在のユーザーメッセージのみを渡す
                                         # 履歴はGraph内で別途ロード・マージするか、ここで結合するか検討
                                         # -> GraphStateのAnnotatedが `x + y` なので、履歴もここで結合して渡す
        character_name=character_name,
        rag_chunks=relevant_chunks if relevant_chunks else [], # Noneでなく空リストを渡す
        reflection="", # 初期値
        current_model_name=selected_model
    )
    # 履歴を結合する場合 (GraphStateのmessagesのAnnotatedが x+y のため)
    initial_graph_state["messages"] = langchain_messages + [current_user_message]


    # 4. グラフの非同期実行
    # 一意のスレッドIDを生成または取得する（会話の永続化のため）
    # ここでは単純な例として固定のIDを使用するが、実際にはユーザーやセッションごとに管理する
    thread_id = f"thread-rag-{character_name.replace(' ', '_')}" # キャラクターごとにスレッドを分ける例
    config = {"configurable": {"thread_id": thread_id}}

    print(f"情報: RAGグラフ({thread_id})を実行します。入力ユーザープロンプト: '{user_prompt[:100]}...'")
    try:
        # .ainvoke() を使用して非同期実行
        final_state = await _rag_graph_instance.ainvoke(initial_graph_state, config=config)
    except Exception as e:
        print(f"エラー: RAGグラフの実行中に例外が発生しました: {e}")
        traceback.print_exc()
        return f"エラー: 思考処理中に問題が発生しました ({e})"

    # 5. 結果の返却
    if final_state and final_state.get("messages"):
        # 最後のメッセージがAIの応答であると期待
        ai_final_response_message = final_state["messages"][-1]
        if isinstance(ai_final_response_message, AIMessage):
            print(f"情報: RAGグラフからAI応答を取得しました: '{ai_final_response_message.content[:100]}...'")
            return ai_final_response_message.content
        else:
            print(f"警告: RAGグラフの最後のメッセージがAIMessageではありません: {type(ai_final_response_message)}")
            return "エラー: AIからの応答形式が正しくありません。"
    else:
        print("警告: RAGグラフの実行結果からメッセージを取得できませんでした。")
        return "エラー: AIからの応答がありませんでした。"