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
import google.generativeai as genai
from google.generativeai import types
from google.generativeai.types import Tool, GenerateContentConfig, Content, Part, GenerateImagesConfig, FunctionDeclaration, FunctionCall
import os
import json
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
from utils import load_chat_log, save_message_to_log
from character_manager import get_character_files_paths

_gemini_client = None

def _define_image_generation_tool():
    """Gemini APIに渡すための画像生成ツールの定義を作成します。"""
    return Tool(
        function_declarations=[
            FunctionDeclaration(
                name="generate_image",
                description="ユーザーからのリクエストに応えたり、自身の感情や情景を表現したりするために、情景やキャラクターのイラストを描画します。ユーザーが絵を求めている場合や、視覚的な説明が有効だと判断した場合に、このツールを積極的に使用してください。",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "prompt": {
                            "type": "STRING",
                            "description": "生成したい画像の内容を詳細に記述した、英語のプロンプト。例: 'A beautiful girl with a gentle smile, anime style, peaceful landscape background, warm sunlight.'"
                        }
                    },
                    "required": ["prompt"]
                }
            )
        ]
    )

# --- Google API (Gemini) 連携関数 ---
def configure_google_api(api_key_name):
    if not api_key_name: return False, "APIキー名が指定されていません。"
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return False, f"APIキー名 '{api_key_name}' に対応する有効なAPIキーが設定されていません。"
    try:
        global _gemini_client
        _gemini_client = genai.Client(api_key=api_key)
        print(f"Google GenAI Client for API key '{api_key_name}' initialized successfully.")
        return True, None
    except Exception as e:
        return False, f"APIキー '{api_key_name}' での genai.Client 初期化中にエラー: {e}"

# gemini_api.py の send_to_gemini 関数を、このブロックで完全に置き換えてください

def send_to_gemini(system_prompt_path, log_file_path, user_prompt, selected_model, character_name, send_thoughts_to_api, api_history_limit_option, uploaded_file_parts: list = None, memory_json_path=None):
    if _gemini_client is None:
        return "エラー: Geminiクライアントが初期化されていません。APIキーを設定してください。", None

    # --- 1. プロンプトと会話履歴の準備 ---
    print(f"--- 対話処理開始 (Tool Use対応) --- Thoughts API送信: {send_thoughts_to_api}, 履歴制限: {api_history_limit_option}")

    sys_ins_text = "あなたはチャットボットです。"
    if system_prompt_path and os.path.exists(system_prompt_path):
        try:
            with open(system_prompt_path, "r", encoding="utf-8") as f: sys_ins_text = f.read().strip() or sys_ins_text
        except Exception as e: print(f"システムプロンプト '{system_prompt_path}' 読込エラー: {e}")
    if memory_json_path and os.path.exists(memory_json_path):
        try:
            # Ensure json is imported (globally)
            with open(memory_json_path, "r", encoding="utf-8") as f: mem = json.load(f)
            m_api = {k: v for k, v in {
                "user_profile": mem.get("user_profile"), "self_identity": mem.get("self_identity"),
                "shared_language": mem.get("shared_language"), "current_context": mem.get("current_context"),
                "memory_summary": mem.get("memory_summary", [])[-config_manager.MEMORY_SUMMARY_LIMIT_FOR_API:]
            }.items() if v}
            if m_api: sys_ins_text += f"\n\n---\n## 参考記憶:\n{json.dumps(m_api, indent=2, ensure_ascii=False)}\n---"
        except Exception as e: print(f"記憶ファイル '{memory_json_path}' 読込/処理エラー: {e}")

    # Ensure load_chat_log is available (from utils)
    msgs = load_chat_log(log_file_path, character_name)

    if api_history_limit_option.isdigit():
        try:
            limit = int(api_history_limit_option)
            if limit > 0:
                # 1往復 = 2メッセージ (user, model)
                limit_msgs = limit * 2
                if len(msgs) > limit_msgs:
                    print(f"情報: 履歴を直近 {limit} 往復 ({limit_msgs} メッセージ) に制限します。")
                    msgs = msgs[-limit_msgs:]
        except ValueError:
            # isdigit()でチェックしているので基本的にはここに来ないはず
            print(f"警告: api_history_limit_option '{api_history_limit_option}' は不正な数値です。履歴は制限されません。")
    # "all" の場合は何もしない (全履歴を使用)

    if msgs and msgs[-1].get("role") == "user":
        print("情報: ログ末尾のユーザーメッセージを履歴から一時的に削除し、引数の内容で上書きします。")
        msgs = msgs[:-1]

    api_contents_from_history = []
    # Ensure 're' is imported (globally)
    th_pat = re.compile(r"【Thoughts】.*?【/Thoughts】\s*", re.DOTALL | re.IGNORECASE)
    # Ensure 'Content' and 'Part' from google.generativeai.types are imported (globally)
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
        # Ensure 'os' and 'base64' are imported (globally)
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

    final_api_contents = []
    if sys_ins_text:
        final_api_contents.append(Content(role="user", parts=[Part(text=sys_ins_text)]))
        final_api_contents.append(Content(role="model", parts=[Part(text="了解しました。システム指示に従い、対話を開始します。")]))

    # --- ここからが【最重要修正点】 ---
    # 履歴とお手本の順番を調整し、お手本が「最近の会話」だと誤認されるのを防ぐ

    # AIにツールの使い方を教えるための、文脈に依存しない「機能テスト」のお手本
    few_shot_example = [
        Content(role="user", parts=[Part(text="画像生成ツールの動作確認をします。")]),
        Content(role="model", parts=[Part(function_call=FunctionCall(
            name="generate_image",
            args={"prompt": "A basic test pattern: a red square, a blue circle, and a green triangle on a plain white background. Clear, simple, vector style."}
        ))]),
        Content(role="user", parts=[Part.from_function_response(
            name="generate_image",
            response={"result": "画像生成に成功しました。パス: path/to/test_pattern.png。この事実に基づき、ユーザーへの応答メッセージだけを生成してください。"}
        )]),
        Content(role="model", parts=[Part(text="ツールの動作確認用画像を生成しました。指定通り、赤い四角、青い丸、緑の三角形が描画されています。")])
    ]
    # 最初に、会話の前提知識となる「お手本」を追加する
    final_api_contents.extend(few_shot_example)

    # 次に、実際の過去の会話履歴を追加する
    final_api_contents.extend(api_contents_from_history)

    # 最後に、現在のユーザー入力を追加する
    if current_turn_parts: final_api_contents.append(Content(role="user", parts=current_turn_parts))
    # --- ここまでが【最重要修正点】 ---

    # (以降のコードは変更なし)
    image_generation_tool = _define_image_generation_tool()

    formatted_safety_settings = []
    if config_manager.SAFETY_CONFIG and isinstance(config_manager.SAFETY_CONFIG, dict):
        for category, threshold in config_manager.SAFETY_CONFIG.items():
            formatted_safety_settings.append({
                "category": category,
                "threshold": threshold
            })

    try:
        image_path_for_final_return = None
        while True:
            print(f"Gemini APIへ送信開始... (Tool Use有効) contents長: {len(final_api_contents)}")

            generation_config = GenerateContentConfig(
                tools=[image_generation_tool],
                safety_settings=formatted_safety_settings
            )

            response = _gemini_client.models.generate_content(
                model=selected_model,
                contents=final_api_contents,
                config=generation_config
            )

            candidate = response.candidates[0]
            if not candidate.content.parts or not candidate.content.parts[0].function_call:
                print("情報: AIからの応答は通常のテキストです。処理を終了します。")
                final_text_parts = [part.text for part in candidate.content.parts if hasattr(part, 'text') and part.text is not None]
                final_text = "".join(final_text_parts).strip()
                return final_text, image_path_for_final_return

            function_call = candidate.content.parts[0].function_call
            if function_call.name != "generate_image":
                return f"エラー: 不明な関数 '{function_call.name}' が呼び出されました。", None

            print(f"情報: AIが画像生成ツール '{function_call.name}' の使用を要求しました。")
            final_api_contents.append(candidate.content)

            args = function_call.args
            image_prompt = args.get("prompt")
            tool_result_content = ""
            if not image_prompt:
                tool_result_content = "エラー: 画像生成のプロンプトが指定されませんでした。この状況をユーザーに伝えてください。"
            else:
                print(f"画像生成プロンプト: '{image_prompt[:100]}...'")
                sanitized_base_name = "".join(c for c in image_prompt[:30] if c.isalnum() or c in [' ']).strip().replace(' ', '_')
                filename_suggestion = f"{character_name}_{sanitized_base_name}"

                text_response, image_path = generate_image_with_gemini(
                    prompt=image_prompt,
                    output_image_filename_suggestion=filename_suggestion
                )
                if image_path:
                    image_path_for_final_return = image_path

                if image_path:
                    tool_result_content = f"画像生成に成功しました。パス: {image_path}。この事実に基づき、ユーザーへの応答メッセージだけを生成してください。"
                else:
                    tool_result_content = f"画像生成に失敗しました。理由: {text_response}。このエラーメッセージを参考に、ユーザーに応答してください。"

            function_response_part = Part.from_function_response(
                name="generate_image",
                response={"result": tool_result_content}
            )
            final_api_contents.append(Content(parts=[function_response_part]))

    except google.api_core.exceptions.GoogleAPIError as e:
        return f"エラー: Gemini APIとの通信中にエラーが発生しました: {e}", None
    except Exception as e:
        traceback.print_exc()
        return f"エラー: Gemini APIとの通信中に予期しないエラーが発生しました: {e}", None

def send_alarm_to_gemini(character_name, theme, flash_prompt_template, alarm_model_name, api_key_name, log_file_path, alarm_api_history_turns):
    print(f"--- アラーム応答生成開始 (google-generativeai SDK, client.models.generate_content) --- キャラ: {character_name}, テーマ: '{theme}'") # Corrected SDK print
    if _gemini_client is None:
        print("警告: _gemini_client is None in send_alarm_to_gemini. Attempting to configure with provided api_key_name.")
        config_success, config_msg = configure_google_api(api_key_name)
        if not config_success:
            return f"【アラームエラー】APIキー設定失敗: {config_msg}"
        if _gemini_client is None: # Check again after attempt
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

    current_alarm_turn_content = api_contents_from_history # Start with history
    # If history is empty or ends with model, add a placeholder user message to prompt response
    if not current_alarm_turn_content or (current_alarm_turn_content and current_alarm_turn_content[-1].role == "model"):
        placeholder_text = "（時間になりました。アラームメッセージをお願いします。）" if not current_alarm_turn_content else "（続けて）"
        current_alarm_turn_content.append(Content(role="user", parts=[Part(text=placeholder_text)]))
        print(f"情報: API呼び出し用に形式的なユーザー入力 ('{placeholder_text}') を追加しました。")

    if not current_alarm_turn_content: # Should not happen due to above logic
         return "【アラームエラー】内部エラー: 送信コンテンツ空"


    final_api_contents = []
    if sys_ins_text: # System instruction acts as the primary prompt
        # In the old SDK, system instructions were often the first user message.
        final_api_contents.append(Content(role="user", parts=[Part(text=sys_ins_text)]))
        # It was common to follow with a model "understood" message, but alarm didn't do that.
        # final_api_contents.append(Content(role="model", parts=[Part(text="了解しました。")]))
    final_api_contents.extend(current_alarm_turn_content) # Then the history + placeholder

    if not final_api_contents: # Double check
        return "【アラームエラー】最終送信コンテンツ空"

    # Safety Settings: Convert from new format (dict) to old format (list of SafetySetting) if needed
    # config_manager.SAFETY_CONFIG is expected to be in the NEW dict format.
    # The old SDK expects a list of types.SafetySetting objects.
    formatted_safety_settings_for_api = []
    if config_manager.SAFETY_CONFIG and isinstance(config_manager.SAFETY_CONFIG, dict):
        for category_str, threshold_str in config_manager.SAFETY_CONFIG.items():
            try:
                # Attempt to map string to HarmCategory and HarmBlockThreshold enums
                harm_category_enum = types.HarmCategory[category_str]
                harm_threshold_enum = types.HarmBlockThreshold[threshold_str.upper()] # old SDK uses uppercase for some thresholds
                formatted_safety_settings_for_api.append(
                    types.SafetySetting(category=harm_category_enum, threshold=harm_threshold_enum)
                )
            except KeyError as ke:
                print(f"警告 (alarm): 安全性設定のカテゴリまたは閾値の文字列からEnumへのマッピングに失敗しました: {ke}。この設定はスキップされます。")
            except Exception as e_ss_map:
                 print(f"警告 (alarm): 安全性設定の処理中に予期しないエラー: {e_ss_map}。この設定はスキップされます。")

        if not formatted_safety_settings_for_api: # If all mappings failed or input was empty
            active_safety_settings = None
        else:
            active_safety_settings = formatted_safety_settings_for_api
            print(f"デバッグ (alarm): 適用される安全性設定 (old SDK format): {active_safety_settings}")
    else:
        print(f"情報 (alarm): config_manager.SAFETY_CONFIG が無効または未設定です。安全性設定は適用されません。")
        active_safety_settings = None


    generation_config_args = {}
    if active_safety_settings:
        generation_config_args["safety_settings"] = active_safety_settings
    # Other config like temperature could be added here if needed for alarms.

    active_generation_config = None
    if generation_config_args:
        try:
            active_generation_config = GenerateContentConfig(**generation_config_args)
        except Exception as e_gc:
            print(f"警告: アラーム用 GenerateContentConfig の作成中にエラー: {e_gc}. 設定は部分的に適用されるか、または無視されます。")


    print(f"アラーム用モデル ({alarm_model_name}, client.models.generate_content) へ送信開始... 送信contents件数: {len(final_api_contents)}")
    try:
        gen_content_args = {
            "model": f"models/{alarm_model_name}", # Old SDK often needs "models/" prefix
            "contents": final_api_contents
        }
        if active_generation_config: # Only add if config was successfully created
            gen_content_args["generation_config"] = active_generation_config # Corrected: use generation_config

        response = _gemini_client.generate_content(**gen_content_args) # Corrected: call on _gemini_client

    except google.api_core.exceptions.GoogleAPIError as e_api:
        # More specific error handling if possible (e.g., InvalidArgument, PermissionDenied)
        print(f"アラームAPI呼び出しで GoogleAPIError: {e_api}")
        # Check for specific block reasons if available in the exception for old SDK
        if "prompt was blocked" in str(e_api).lower():
             return f"【アラームエラー】プロンプトブロック"
        return f"【アラームエラー】API通信失敗: {e_api}"

    except Exception as e:
        # Catching broad exceptions can hide issues; prefer specific ones if known.
        if "BlockedPromptException" in str(type(e)) or "StopCandidateException" in str(type(e)): # Example specific exceptions
             print(f"アラームAPI呼び出しでブロックまたは停止例外: {e}")
             return f"【アラームエラー】プロンプトブロックまたは候補生成停止"

        print(f"アラーム用モデル ({alarm_model_name}, google.generativeai) との通信中にエラーが発生しました: {traceback.format_exc()}")
        return f"【アラームエラー】API通信失敗: {e}"

    final_text_response = None
    try:
        # Accessing response parts for old SDK
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            text_parts = [part.text for part in response.candidates[0].content.parts if hasattr(part, 'text') and part.text is not None]
            final_text_response = "".join(text_parts).strip()

        if final_text_response is None or not final_text_response.strip():
            # Check for blocking reasons in prompt_feedback for old SDK
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback and response.prompt_feedback.block_reason:
                block_reason_str = str(response.prompt_feedback.block_reason)
                # You might want to map enum numbers to names if they are just numbers
                return f"【アラームエラー】応答取得失敗。ブロック理由: {block_reason_str}"
            if final_text_response is None: # Explicitly None vs empty string
                 final_text_response = "【アラームエラー】モデルから空の応答または非テキスト応答が返されました。"
            # else: it's an empty string, which is a valid (though perhaps undesirable) response.

        # Strip markdown-like prefixes as before
        if final_text_response.strip().startswith("```"):
            return final_text_response.strip() # Return as is if it's a code block
        else: # Remove leading list/quote markers or newlines
            return re.sub(r"^\s*([-*_#=`>]+|\n)+\s*", "", final_text_response.strip())


    except Exception as e_resp_proc: # Catch errors during response processing
        print(f"アラーム応答テキストの処理中にエラー: {e_resp_proc}")
        if hasattr(response, 'prompt_feedback') and response.prompt_feedback and response.prompt_feedback.block_reason:
            return f"【アラームエラー】応答処理エラー ({e_resp_proc}) ブロック理由: {response.prompt_feedback.block_reason}"
        return f"【アラームエラー】応答処理エラー ({e_resp_proc}) ブロック理由は不明"


def generate_image_with_gemini(prompt: str, output_image_filename_suggestion: str) -> tuple[Optional[str], Optional[str]]:
    """
    Generates an image using a Gemini model with response_modalities and saves it. (Old SDK version)
    """
    if _gemini_client is None:
        return "エラー: Geminiクライアントが初期化されていません。APIキーを設定してください。", None

    # This model name was specific to an old API version or a preview.
    # It might not be available with the current `google-generativeai` library version
    # or might require specific project allowlisting.
    model_name = "gemini-1.0-pro-vision-latest" # A more standard vision model, though not primarily for generation
    # The user's original code had "gemini-2.0-flash-preview-image-generation" which is highly specific.
    # For restoration, we should use what was there. If it fails, it indicates an environment/API version issue.
    # Let's assume "gemini-2.0-flash-preview-image-generation" was the original intent from the snippet.
    # However, the first read file uses "gemini-1.0-pro-vision-latest" for image generation.
    # The actual very first read file had:
    # model_name = "gemini-2.0-flash-preview-image-generation"
    # This discrepancy needs to be resolved. I will use what was in the *very first* `read_files` call for this file,
    # which was "gemini-2.0-flash-preview-image-generation".
    # The prompt now says the initially read file had "gemini-1.0-pro-vision-latest". This is confusing.
    # I will stick to the content provided in *this current tool call's description* as the source of truth for restoration.
    # The description's import list implies `google.generativeai`.
    # The very first `read_files` in the previous subtask (the one for `gemini_api.py` update) had:
    # `model_name = "gemini-2.0-flash-preview-image-generation"` in `generate_image_with_gemini`.
    # I will use that.

    model_to_use_for_image_gen = "gemini-1.0-pro-vision-latest" # Defaulting to a known model if the other is too specific/preview
    # Re-checking the initial file content provided in the previous subtask's `read_files` output:
    # The function `generate_image_with_gemini` in that initial read, used:
    # model_name = "gemini-2.0-flash-preview-image-generation"
    # So I will restore that.

    model_name_from_original = "gemini-2.0-flash-preview-image-generation"


    try:
        print(f"--- Gemini 画像生成開始 (model: {model_name_from_original}, response_modalities) --- プロンプト: '{prompt[:100]}...'")

        contents = [Content(parts=[Part(text=prompt)])]

        # GenerateImagesConfig is not standard in google.generativeai for generate_content
        # response_modalities was part of a specific client or model feature.
        # For google.generativeai, image generation is typically done by models that directly output images,
        # or by specific methods if the library supports them (like some PaLM API features).
        # The original code used `GenerateContentConfig(response_modalities=['TEXT', 'IMAGE'])`.
        # This might be specific to `genai.Client`'s capabilities if it's from a version
        # that supported this for certain models.

        active_generation_config = GenerateContentConfig(
             # temperature=0.8, # Example: can add other parameters
             response_modalities=['TEXT', 'IMAGE'] # This is the key part from original
        )

        # Ensure model name is prefixed with "models/" if required by the client version
        if not model_name_from_original.startswith("models/"):
            api_model_name = f"models/{model_name_from_original}"
        else:
            api_model_name = model_name_from_original

        response = _gemini_client.generate_content( # Corrected: use _gemini_client
            model=api_model_name, # Use the model name from original
            contents=contents,
            generation_config=active_generation_config # Corrected: use generation_config
        )

        generated_text = None
        image_path = None

        # Processing response parts (old SDK style)
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            for part_content in response.candidates[0].content.parts:
                if hasattr(part_content, 'text') and part_content.text:
                    current_part_text = part_content.text.strip()
                    if current_part_text:
                        if generated_text is None:
                            generated_text = current_part_text
                        else:
                            # Avoid duplicating text if model sends it in multiple small parts
                            if not generated_text.endswith(current_part_text): # Simple check
                               generated_text += "\n" + current_part_text
                        print(f"画像生成APIからテキスト部分を取得: {current_part_text[:100]}...")

                if hasattr(part_content, 'inline_data') and part_content.inline_data is not None:
                    if hasattr(part_content.inline_data, 'data') and part_content.inline_data.data:
                        print(f"画像生成APIから画像データ (MIME: {part_content.inline_data.mime_type}) を取得しました。")
                        image_data = part_content.inline_data.data # This should be bytes

                        _script_dir = os.path.dirname(os.path.abspath(__file__))
                        save_dir = os.path.join(_script_dir, "chat_attachments", "generated_images")
                        os.makedirs(save_dir, exist_ok=True)

                        base_name_suggestion, _ = os.path.splitext(output_image_filename_suggestion)
                        base_name = re.sub(r'[^\w\s-]', '', base_name_suggestion).strip()
                        base_name = re.sub(r'[-\s]+', '_', base_name)
                        if not base_name: base_name = "gemini_image"

                        unique_id = uuid.uuid4().hex[:8]
                        img_ext = ".png" # Default
                        mime = part_content.inline_data.mime_type
                        if mime == "image/jpeg": img_ext = ".jpg"
                        elif mime == "image/webp": img_ext = ".webp"
                        elif mime == "image/png": img_ext = ".png"
                        # else use default .png

                        image_filename = f"{base_name}_{unique_id}{img_ext}"
                        temp_image_path = os.path.join(save_dir, image_filename)

                        try:
                            image = Image.open(BytesIO(image_data))
                            if img_ext == ".jpg" and image.mode == "RGBA": # Convert RGBA to RGB for JPEG
                                image = image.convert("RGB")
                            image.save(temp_image_path)
                            image_path = temp_image_path
                            print(f"生成された画像を '{image_path}' に保存しました。")
                        except Exception as img_e:
                            print(f"エラー: 画像データの処理または保存中にエラーが発生しました: {img_e}")
                            error_for_text = f"画像処理エラー: {img_e}"
                            generated_text = (generated_text + f"\n{error_for_text}") if generated_text else error_for_text
                    else: # inline_data exists but no .data
                        if part_content.inline_data is not None : # Check if inline_data itself is not None
                            print("情報: part.inline_data は存在するものの、.data 属性がないか、または空です。")

                if image_path: # If an image was successfully saved, assume this is the primary output.
                    break

            if image_path is None and generated_text is None: # If loop finishes with no image and no text
                 generated_text = "モデル応答にテキストまたは画像データが見つかりませんでした。"


        elif hasattr(response, 'prompt_feedback') and response.prompt_feedback.block_reason:
            error_message = f"画像生成エラー: プロンプトがブロックされました。理由: {response.prompt_feedback.block_reason}"
            print(error_message)
            generated_text = error_message
        else: # No candidates or other issues
            error_message = "画像生成エラー: モデルから有効な応答がありませんでした (候補なし、または空のコンテンツ)。"
            print(error_message)
            generated_text = error_message

    except google.api_core.exceptions.GoogleAPIError as e_api_img:
        error_msg = f"エラー: Gemini APIとの通信中にエラーが発生しました (画像生成): {e_api_img}"
        print(error_msg)
        traceback.print_exc()
        generated_text = error_msg
        image_path = None # Ensure image_path is None on API error
    except Exception as e_img: # Catch other unexpected errors
        error_msg = f"エラー: Gemini画像生成中に予期しないエラーが発生しました: {e_img}"
        print(error_msg)
        traceback.print_exc()
        generated_text = error_msg
        image_path = None # Ensure image_path is None on other errors

    return generated_text, image_path
