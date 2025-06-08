# -*- coding: utf-8 -*-
import google.genai as genai
from google.genai import types
from google.genai.types import Tool, GoogleSearch, GenerateContentConfig, Content, Part, GenerateImagesConfig, FunctionDeclaration, FunctionCall
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
            with open(memory_json_path, "r", encoding="utf-8") as f: mem = json.load(f)
            m_api = {k: v for k, v in {
                "user_profile": mem.get("user_profile"), "self_identity": mem.get("self_identity"),
                "shared_language": mem.get("shared_language"), "current_context": mem.get("current_context"),
                "memory_summary": mem.get("memory_summary", [])[-config_manager.MEMORY_SUMMARY_LIMIT_FOR_API:]
            }.items() if v}
            if m_api: sys_ins_text += f"\n\n---\n## 参考記憶:\n{json.dumps(m_api, indent=2, ensure_ascii=False)}\n---"
        except Exception as e: print(f"記憶ファイル '{memory_json_path}' 読込/処理エラー: {e}")

    msgs = load_chat_log(log_file_path, character_name)
    if msgs and msgs[-1].get("role") == "user":
        print("情報: ログ末尾のユーザーメッセージを履歴から一時的に削除し、引数の内容で上書きします。")
        msgs = msgs[:-1]

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

    final_api_contents = []
    if sys_ins_text:
        final_api_contents.append(Content(role="user", parts=[Part(text=sys_ins_text)]))
        final_api_contents.append(Content(role="model", parts=[Part(text="了解しました。システム指示に従い、対話を開始します。")]))

    few_shot_example = [
        Content(role="user", parts=[Part(text="猫の絵を描いてくれる？")]),
        Content(role="model", parts=[Part(function_call=FunctionCall(
            name="generate_image",
            args={"prompt": "A cute fluffy cat sleeping on a bookshelf, warm and cozy atmosphere, detailed illustration"}
        ))]),
        Content(role="user", parts=[Part.from_function_response(
            name="generate_image",
            response={"result": "画像生成に成功しました。パス: path/to/example_cat_image.png。この事実に基づき、ユーザーへの応答メッセージだけを生成してください。"}
        )]),
        Content(role="model", parts=[Part(text="お任せください！本棚で眠る、ふわふわの猫ちゃんの絵を描いてみました。気に入ってくれると嬉しいな。")]),
    ]
    final_api_contents.extend(few_shot_example)

    final_api_contents.extend(api_contents_from_history)
    if current_turn_parts: final_api_contents.append(Content(role="user", parts=current_turn_parts))

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
                # --- ここからが【最終確定版の修正】 ---
                # candidate.text の代わりに、全パーツからテキストを確実に抽出する
                # part.text が None でないこともチェックし、TypeErrorを完全に防ぐ
                final_text_parts = [part.text for part in candidate.content.parts if hasattr(part, 'text') and part.text is not None]
                final_text = "".join(final_text_parts).strip()
                return final_text, image_path_for_final_return
                # --- ここまでが【最終確定版の修正】 ---

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

    model_name = "gemini-2.0-flash-preview-image-generation"

    try:
        print(f"--- Gemini 画像生成開始 (model: {model_name}, response_modalities) --- プロンプト: '{prompt[:100]}...'")

        contents = [Content(parts=[Part(text=prompt)])]

        active_generation_config = GenerateContentConfig(
            response_modalities=['TEXT', 'IMAGE']
        )

        response = _gemini_client.models.generate_content(
            model=model_name,
            contents=contents,
            config=active_generation_config
        )

        generated_text = None
        image_path = None

        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            for part_content in response.candidates[0].content.parts:
                if hasattr(part_content, 'text') and part_content.text:
                    current_part_text = part_content.text.strip()
                    if current_part_text:
                        if generated_text is None:
                            generated_text = current_part_text
                        else:
                            if not generated_text.endswith(current_part_text):
                               generated_text += "\n" + current_part_text
                        print(f"画像生成APIからテキスト部分を取得: {current_part_text[:100]}...")

                if hasattr(part_content, 'inline_data') and part_content.inline_data is not None:
                    if hasattr(part_content.inline_data, 'data') and part_content.inline_data.data:
                        print(f"画像生成APIから画像データ (MIME: {part_content.inline_data.mime_type}) を取得しました。")
                        image_data = part_content.inline_data.data

                        save_dir = "chat_attachments/generated_images/"
                        os.makedirs(save_dir, exist_ok=True)

                        base_name_suggestion, _ = os.path.splitext(output_image_filename_suggestion)
                        base_name = re.sub(r'[^\w\s-]', '', base_name_suggestion).strip()
                        base_name = re.sub(r'[-\s]+', '_', base_name)
                        if not base_name: base_name = "gemini_image"

                        unique_id = uuid.uuid4().hex[:8]
                        img_ext = ".png"
                        if part_content.inline_data.mime_type == "image/jpeg":
                            img_ext = ".jpg"
                        elif part_content.inline_data.mime_type == "image/webp":
                            img_ext = ".webp"
                        elif part_content.inline_data.mime_type == "image/png":
                            img_ext = ".png"

                        image_filename = f"{base_name}_{unique_id}{img_ext}"
                        temp_image_path = os.path.join(save_dir, image_filename)

                        try:
                            image = Image.open(BytesIO(image_data))
                            if img_ext == ".jpg" and image.mode == "RGBA":
                                image = image.convert("RGB")
                            image.save(temp_image_path)
                            image_path = temp_image_path
                            print(f"生成された画像を '{image_path}' に保存しました。")
                        except Exception as img_e:
                            print(f"エラー: 画像データの処理または保存中にエラーが発生しました: {img_e}")
                            error_for_text = f"画像処理エラー: {img_e}"
                            if generated_text is None:
                                generated_text = error_for_text
                            else:
                                generated_text += f"\n{error_for_text}"
                    else:
                        if part_content.inline_data is not None :
                            print("情報: part.inline_data は存在するものの、.data 属性がないか、または空です。")
                if image_path:
                    break
            if image_path is None and generated_text is None:
                 generated_text = "モデル応答にテキストまたは画像データが見つかりませんでした。"

        elif hasattr(response, 'prompt_feedback') and response.prompt_feedback.block_reason:
            error_message = f"画像生成エラー: プロンプトがブロックされました。理由: {response.prompt_feedback.block_reason}"
            print(error_message)
            generated_text = error_message
        else:
            error_message = "画像生成エラー: モデルから有効な応答がありませんでした (候補なし、または空のコンテンツ)。"
            print(error_message)
            generated_text = error_message

    except google.api_core.exceptions.GoogleAPIError as e:
        error_msg = f"エラー: Gemini APIとの通信中にエラーが発生しました (画像生成): {e}"
        print(error_msg)
        traceback.print_exc()
        generated_text = error_msg
        image_path = None
    except Exception as e:
        error_msg = f"エラー: Gemini画像生成中に予期しないエラーが発生しました: {e}"
        print(error_msg)
        traceback.print_exc()
        generated_text = error_msg
        image_path = None

    return generated_text, image_path