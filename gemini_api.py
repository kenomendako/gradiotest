# -*- coding: utf-8 -*-
import google.genai as genai
from google.genai import types
from google.genai.types import Tool, GoogleSearch, GenerateContentConfig, Content, Part, GenerateImagesConfig # Added GenerateImagesConfig
from google.ai.generativelanguage import HarmCategory, SafetySetting
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
from utils import load_chat_log
from character_manager import get_character_files_paths

_gemini_client = None

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

def send_to_gemini(system_prompt_path, log_file_path, user_prompt, selected_model, character_name, send_thoughts_to_api, api_history_limit_option, uploaded_file_parts: list = None, memory_json_path=None):
    if _gemini_client is None:
        return "エラー: Geminiクライアントが初期化されていません。APIキーを設定してください。"

    print(f"--- 通常対話開始 (google-genai SDK, client.models.generate_content) --- Thoughts API送信: {send_thoughts_to_api}, 履歴制限: {api_history_limit_option}")

    sys_ins_text = "あなたはチャットボットです。"
    if system_prompt_path and os.path.exists(system_prompt_path):
        try:
            with open(system_prompt_path, "r", encoding="utf-8") as f: sys_ins_text = f.read().strip() or sys_ins_text
        except Exception as e: print(f"システムプロンプト '{system_prompt_path}' 読込エラー: {e}")
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
        except Exception as e: print(f"記憶ファイル '{memory_json_path}' 読込/処理エラー: {e}")

    # Renamed from g_hist and parts_for_gemini_api to api_contents_from_history and current_turn_parts
    msgs = load_chat_log(log_file_path, character_name)
    if api_history_limit_option.isdigit():
        limit_turns = int(api_history_limit_option)
        limit_msgs = limit_turns * 2
        if len(msgs) > limit_msgs:
            print(f"情報: API履歴を直近 {limit_turns} 往復 ({limit_msgs} メッセージ) に制限します。")
            msgs = msgs[-limit_msgs:]

    api_contents_from_history = []
    th_pat = re.compile(r"【Thoughts】.*?【/Thoughts】\s*", re.DOTALL | re.IGNORECASE)
    for m in msgs:
        sdk_role = "user" if m.get("role") == "user" else "model"
        content_text = m.get("content", "")
        if not content_text: continue
        processed_text = content_text
        if sdk_role == "user":
            processed_text = re.sub(r"\[画像添付:[^\]]+\]", "", processed_text).strip()
        elif sdk_role == "model" and not send_thoughts_to_api:
            processed_text = th_pat.sub("", processed_text).strip()
        if processed_text:
            api_contents_from_history.append(Content(role=sdk_role, parts=[Part(text=processed_text)]))

    current_turn_parts = []
    if user_prompt:
        current_turn_parts.append(Part(text=user_prompt))

    if uploaded_file_parts:
        for file_detail in uploaded_file_parts:
            file_path = file_detail['path']
            mime_type = file_detail['mime_type']
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'rb') as f_bytes: file_bytes = f_bytes.read()
                    encoded_data = base64.b64encode(file_bytes).decode('utf-8')
                    current_turn_parts.append(Part(inline_data={"mime_type": mime_type, "data": encoded_data}))
                    print(f"情報: ファイル '{os.path.basename(file_path)}' ({mime_type}) をAPIリクエストに追加しました。")
                except Exception as e: print(f"警告: ファイル '{os.path.basename(file_path)}' の処理中にエラー: {e}. スキップします。")
            else: print(f"警告: 指定されたファイルパス '{file_path}' が見つかりません。スキップします。")

    if not current_turn_parts and not api_contents_from_history:
         if user_prompt is not None or uploaded_file_parts: # Intended to send something, but it became empty
             return "エラー: 送信する有効なコンテンツがありません (テキストが空か、ファイル処理に失敗しました)。"
         else: # No history and no new input
             return "エラー: 送信するメッセージ履歴も現在の入力もありません。"

    # Prepare final_api_contents (prepending system instruction)
    final_api_contents = []
    if sys_ins_text:
        print(f"デバッグ: Prepending system instruction to contents in send_to_gemini.")
        final_api_contents.append(Content(role="user", parts=[Part(text=sys_ins_text)]))
        # Optional: Add a model acknowledgment
        # final_api_contents.append(Content(role="model", parts=[Part(text="了解しました。システム指示に従います。")]))

    final_api_contents.extend(api_contents_from_history)

    if current_turn_parts: # Add current user's turn if there are any parts
        final_api_contents.append(Content(role="user", parts=current_turn_parts))

    if not final_api_contents:
        return "エラー: 最終的な送信コンテンツが空です。"

    tools_list = []
    if "2.5-pro" in selected_model.lower() or "2.5-flash" in selected_model.lower():
        try:
            google_search_tool = Tool(google_search=GoogleSearch())
            tools_list.append(google_search_tool)
            print("情報: Google検索グラウンディング (google-genai SDK) がセットアップされました。")
        except Exception as e:
            print(f"警告: GoogleSearch Toolのセットアップ中にエラー (google-genai SDK): {e}")

    formatted_safety_settings = []
    if config_manager.SAFETY_CONFIG:
        try:
            # Create a list of Dictionaries with string enum names
            formatted_safety_settings_for_api = []
            for category_enum, threshold_enum in config_manager.SAFETY_CONFIG.items():
                category_str = category_enum.name
                threshold_str = threshold_enum.name
                formatted_safety_settings_for_api.append({
                    "category": category_str,
                    "threshold": threshold_str
                })
            print(f"デバッグ: formatted_safety_settings_for_api (list of dicts with strings): {formatted_safety_settings_for_api}")
            if not formatted_safety_settings_for_api:
                formatted_safety_settings = None # Keep 'formatted_safety_settings' as the variable name for consistency if it's used later, or switch to new name
            else:
                formatted_safety_settings = formatted_safety_settings_for_api # Use the new list of dicts
        except AttributeError as ae:
            print(f"警告: categoryまたはthresholdに .name 属性がありません。category: {type(category_enum)}, threshold: {type(threshold_enum)}. Error: {ae}")
            formatted_safety_settings = None
        except Exception as e_ss:
            print(f"警告: Error processing safety settings for send_to_gemini: {e_ss}. Safety settings may not be applied.")
            formatted_safety_settings = None
    else:
        formatted_safety_settings = None

    generation_config_args = {}
    if tools_list:
        generation_config_args["tools"] = tools_list
    if formatted_safety_settings: # This will now be the list of dicts or None
        generation_config_args["safety_settings"] = formatted_safety_settings

    active_generation_config = None
    if generation_config_args:
        try:
            active_generation_config = GenerateContentConfig(**generation_config_args)
            print(f"デバッグ: GenerateContentConfig created with args: {generation_config_args}")
        except Exception as e:
            print(f"警告: GenerateContentConfig の作成中にエラー: {e}. 引数なしで試行します。")
            try:
                active_generation_config = GenerateContentConfig()
            except Exception as e_cfg_fallback:
                 print(f"警告: フォールバック GenerateContentConfig の作成中にもエラー: {e_cfg_fallback}.")

    print(f"Gemini (google-genai, client.models.generate_content) へ送信開始... モデル: {selected_model}, contents長: {len(final_api_contents)}")
    try:
        gen_content_args = {
            "model": selected_model,
            "contents": final_api_contents,
        }
        if active_generation_config:
            gen_content_args["config"] = active_generation_config # Changed key

        response = _gemini_client.models.generate_content(**gen_content_args)

    except google.api_core.exceptions.ResourceExhausted as e:
        return f"エラー: Gemini API リソース枯渇 (google-genai): {e}"
    except Exception as e:
        import traceback
        print(f"Gemini API (google-genai) 呼び出し中に予期しないエラー: {traceback.format_exc()}")
        return f"エラー: Gemini APIとの通信中に予期しないエラー (google-genai): {e}"

    final_text_response = None
    try:
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            text_parts = [part.text for part in response.candidates[0].content.parts if hasattr(part, 'text')]
            final_text_response = "".join(text_parts)
        if final_text_response is None or not final_text_response.strip():
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback and response.prompt_feedback.block_reason:
                return f"応答取得エラー: プロンプトがブロックされました。理由: {response.prompt_feedback.block_reason}"
            if final_text_response is None :
                 final_text_response = "応答にテキストコンテンツが見つかりませんでした。"
    except Exception as e:
        print(f"応答テキストの処理中にエラー: {e}")
        if hasattr(response, 'prompt_feedback') and response.prompt_feedback and response.prompt_feedback.block_reason:
            return f"応答取得エラー ({e}) ブロック理由: {response.prompt_feedback.block_reason}"
        return f"応答取得エラー ({e}) ブロック理由は不明"

    return final_text_response.strip() if final_text_response is not None else "応答生成失敗 (空の応答)"

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

    # Prepare api_contents_from_history (history only)
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

    # If history is empty, or last message was model's, add a placeholder user message.
    # This placeholder becomes the "current turn" for the alarm.
    current_alarm_turn_content = api_contents_from_history # Start with history
    if not current_alarm_turn_content or (current_alarm_turn_content and current_alarm_turn_content[-1].role == "model"):
        placeholder_text = "（時間になりました。アラームメッセージをお願いします。）" if not current_alarm_turn_content else "（続けて）"
        # If api_contents_from_history was empty, this makes current_alarm_turn_content have one user message.
        # If api_contents_from_history ended with model, this adds a user message.
        current_alarm_turn_content.append(Content(role="user", parts=[Part(text=placeholder_text)]))
        print(f"情報: API呼び出し用に形式的なユーザー入力 ('{placeholder_text}') を追加しました。")

    if not current_alarm_turn_content:
         return "【アラームエラー】内部エラー: 送信コンテンツ空"

    # Prepare final_api_contents (prepending system instruction)
    final_api_contents = []
    if sys_ins_text:
        print(f"デバッグ (alarm): Prepending system instruction to contents.")
        final_api_contents.append(Content(role="user", parts=[Part(text=sys_ins_text)]))
    final_api_contents.extend(current_alarm_turn_content)

    if not final_api_contents:
        return "【アラームエラー】最終送信コンテンツ空"

    # Prepare formatted_safety_settings for API (list of dicts with string enum names)
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
                formatted_safety_settings = None # Keep 'formatted_safety_settings' as the variable name for consistency or switch
            else:
                formatted_safety_settings = formatted_safety_settings_for_api # Use the new list of dicts
        except AttributeError as ae:
            print(f"警告 (alarm): categoryまたはthresholdに .name 属性がありません。category: {type(category_enum)}, threshold: {type(threshold_enum)}. Error: {ae}")
            formatted_safety_settings = None
        except Exception as e_ss_alarm:
            print(f"警告 (alarm): Error processing safety settings: {e_ss_alarm}. Safety settings may not be applied.")
            formatted_safety_settings = None
    else:
        formatted_safety_settings = None

    generation_config_args = {}
    if formatted_safety_settings: # This will now be the list of dicts or None
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
            gen_content_args["config"] = active_generation_config # Changed key

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
    Generates an image using an Imagen model and saves it to a local path.

    Args:
        prompt (str): The text prompt for image generation.
        output_image_filename_suggestion (str): A suggestion for the output image filename.

    Returns:
        tuple: (generated_text, image_path)
               generated_text (str or None): Text response (usually None or error message for Imagen).
               image_path (str or None): Path to the saved image, or None if generation failed.
    """
    if _gemini_client is None:
        return "エラー: Geminiクライアントが初期化されていません。APIキーを設定してください。", None

    generated_text: Optional[str] = None
    image_path: Optional[str] = None
    model_name = 'imagen-3.0-generate-002'

    try:
        print(f"--- Imagen 画像生成開始 (model: {model_name}) --- プロンプト: '{prompt[:100]}...'")

        img_gen_config = GenerateImagesConfig(
            number_of_images=1,
        )

        response = _gemini_client.models.generate_images(
            model=model_name,
            prompt=prompt,
            config=img_gen_config
        )

        if response.generated_images:
            generated_image_data = response.generated_images[0].image.image_bytes

            save_dir = "chat_attachments/generated_images/"
            os.makedirs(save_dir, exist_ok=True)

            base_name, ext = os.path.splitext(output_image_filename_suggestion)
            if not ext or ext.lower() not in ['.png', '.jpg', '.jpeg', '.webp']:
                 ext = ".png"

            base_name = re.sub(r'[^\w\s-]', '', base_name).strip()
            base_name = re.sub(r'[-\s]+', '_', base_name)
            if not base_name:
                base_name = "generated_image"

            unique_id = uuid.uuid4().hex[:8]
            image_filename = f"{base_name}_{unique_id}{ext}"
            image_path = os.path.join(save_dir, image_filename)

            try:
                image_pil = Image.open(BytesIO(generated_image_data))

                if ext.lower() in ['.jpg', '.jpeg']:
                    if image_pil.mode == 'RGBA' or (image_pil.mode == 'P' and 'transparency' in image_pil.info):
                        image_pil = image_pil.convert('RGB')
                    image_pil.save(image_path, format='JPEG')
                elif ext.lower() == '.webp':
                    image_pil.save(image_path, format='WEBP')
                else:
                    image_pil.save(image_path, format='PNG')

                print(f"生成された画像を '{image_path}' に保存しました。")
                generated_text = None
            except Exception as img_e:
                error_msg = f"画像データの処理または保存中にエラー: {img_e}"
                print(f"エラー: {error_msg}")
                traceback.print_exc()
                image_path = None
                generated_text = error_msg
        else:
            image_path = None
            generated_text = "画像が生成されませんでした。モデルからの応答に画像が含まれていません。"
            # Check for more specific error information in the response if available
            if hasattr(response, 'error') and response.error:
                 generated_text += f" APIエラー詳細: {str(response.error)}"
            elif hasattr(response, 'errors') and response.errors:
                 generated_text += f" APIエラー詳細: {str(response.errors)}"
            print(f"警告: {generated_text}")

    except google.api_core.exceptions.GoogleAPIError as e:
        error_msg = f"エラー: Imagen APIとの通信中にエラーが発生しました: {e}"
        print(error_msg)
        traceback.print_exc()
        generated_text = error_msg
        image_path = None
    except Exception as e:
        error_msg = f"エラー: Imagen画像生成中に予期しないエラーが発生しました: {e}"
        print(error_msg)
        traceback.print_exc()
        generated_text = error_msg
        image_path = None

    return generated_text, image_path