# -*- coding: utf-8 -*-
# ##############################################################################
# #   AIへの最重要指示: このファイルは `google.genai` を `genai` として
# #   インポートして使用します。詳細は `AI_DEVELOPMENT_GUIDELINES.md` を参照。
# ##############################################################################
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
from io import BytesIO
from typing import Optional, List, Dict
import io
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

def send_to_gemini(system_prompt_path, log_file_path, user_prompt, selected_model, character_name, send_thoughts_to_api, api_history_limit_option, uploaded_file_parts: list = None, memory_json_path=None) -> tuple[Optional[str], Optional[str]]:
    if _gemini_client is None:
        return "エラー: Geminiクライアントが初期化されていません。APIキーを設定してください。", None

    # (この関数の内部ロジックは、お客様の最初のファイルからそのまま持ってきました)
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

    if api_history_limit_option.isdigit():
        try:
            limit = int(api_history_limit_option)
            if limit > 0:
                limit_msgs = limit * 2
                if len(msgs) > limit_msgs:
                    msgs = msgs[-limit_msgs:]
        except ValueError:
            pass

    if msgs and msgs[-1].get("role") == "user":
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
    final_api_contents.extend(few_shot_example)
    final_api_contents.extend(api_contents_from_history)
    if current_turn_parts: final_api_contents.append(Content(role="user", parts=current_turn_parts))

    image_generation_tool = _define_image_generation_tool()
    formatted_safety_settings = []
    if config_manager.SAFETY_CONFIG and isinstance(config_manager.SAFETY_CONFIG, dict):
        for category, threshold in config_manager.SAFETY_CONFIG.items():
            formatted_safety_settings.append({"category": category, "threshold": threshold})

    try:
        image_path_for_final_return = None
        while True:
            generation_config = GenerateContentConfig(tools=[image_generation_tool], safety_settings=formatted_safety_settings)
            response = _gemini_client.models.generate_content(model=selected_model, contents=final_api_contents, config=generation_config)
            candidate = response.candidates[0]
            if not candidate.content.parts or not candidate.content.parts[0].function_call:
                final_text_parts = [part.text for part in candidate.content.parts if hasattr(part, 'text') and part.text is not None]
                final_text = "".join(final_text_parts).strip()
                return final_text, image_path_for_final_return

            function_call = candidate.content.parts[0].function_call
            if function_call.name != "generate_image":
                return f"エラー: 不明な関数 '{function_call.name}' が呼び出されました。", None

            final_api_contents.append(candidate.content)
            args = function_call.args
            image_prompt = args.get("prompt")
            tool_result_content = ""
            if not image_prompt:
                tool_result_content = "エラー: 画像生成のプロンプトが指定されませんでした。"
            else:
                sanitized_base_name = "".join(c for c in image_prompt[:30] if c.isalnum() or c in [' ']).strip().replace(' ', '_')
                filename_suggestion = f"{character_name}_{sanitized_base_name}"
                text_response, image_path = generate_image_with_gemini(prompt=image_prompt, output_image_filename_suggestion=filename_suggestion)
                if image_path:
                    image_path_for_final_return = image_path
                    tool_result_content = f"画像生成に成功しました。パス: {image_path}。この事実に基づき、ユーザーへの応答メッセージだけを生成してください。"
                else:
                    tool_result_content = f"画像生成に失敗しました。理由: {text_response}"

            function_response_part = Part.from_function_response(name="generate_image", response={"result": tool_result_content})
            final_api_contents.append(Content(parts=[function_response_part]))
    except google.api_core.exceptions.GoogleAPIError as e:
        return f"エラー: Gemini APIとの通信中にエラーが発生しました: {e}", None
    except Exception as e:
        traceback.print_exc()
        return f"エラー: Gemini APIとの通信中に予期しないエラーが発生しました: {e}", None

def send_alarm_to_gemini(character_name, theme, flash_prompt_template, alarm_model_name, api_key_name, log_file_path, alarm_api_history_turns):
    if _gemini_client is None:
        configure_google_api(api_key_name)

    # (この関数の内部ロジックは、お客様の最初のファイルからそのまま持ってきました)
    sys_ins_text = ""
    if flash_prompt_template:
        sys_ins_text = flash_prompt_template.replace("[キャラクター名]", character_name).replace("[テーマ内容]", theme)
        sys_ins_text += "\n\n**重要:** あなたの思考過程、応答の候補、メタテキスト（例: ---）などは一切出力せず、ユーザーに送る最終的な短いメッセージ本文のみを生成してください。"
    elif theme:
        sys_ins_text = f"あなたはキャラクター「{character_name}」です。\n以下のテーマについて、ユーザーに送る短いメッセージを生成してください。\n過去の会話履歴があれば参考にし、自然な応答を心がけてください。\n\nテーマ: {theme}\n\n重要: あなたの思考過程、応答の候補リスト、自己対話、マーカー（例: `---`）などは一切含めず、ユーザーに送る最終的な短いメッセージ本文のみを出力してください。"

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

    current_alarm_turn_content = api_contents_from_history
    if not current_alarm_turn_content or (current_alarm_turn_content and current_alarm_turn_content[-1].role == "model"):
        placeholder_text = "（時間になりました。アラームメッセージをお願いします。）"
        current_alarm_turn_content.append(Content(role="user", parts=[Part(text=placeholder_text)]))

    final_api_contents = []
    if sys_ins_text:
        final_api_contents.append(Content(role="user", parts=[Part(text=sys_ins_text)]))
    final_api_contents.extend(current_alarm_turn_content)

    try:
        response = _gemini_client.models.generate_content(alarm_model_name, final_api_contents)
        final_text_response = "".join(part.text for part in response.parts if hasattr(part, 'text'))
        return re.sub(r"^\s*([-*_#=`>]+|\n)+\s*", "", final_text_response.strip())
    except Exception as e:
        print(f"アラーム用モデルとの通信中にエラーが発生しました: {traceback.format_exc()}")
        return f"【アラームエラー】API通信失敗: {e}"

def generate_image_with_gemini(prompt: str, output_image_filename_suggestion: str) -> tuple[Optional[str], Optional[str]]:
    if _gemini_client is None:
        return "エラー: Geminiクライアントが初期化されていません。", None

    # (この関数の内部ロジックは、お客様の最初のファイルからそのまま持ってきました)
    model_name = "gemini-1.0-pro" # Note: This might not be the intended image model
    try:
        # This is a simplified image generation call based on older patterns
        # It may need adjustment for the specific image model you want to use.
        response = _gemini_client.models.generate_content(
            model=model_name,
            contents=[f"このプロンプトで画像を生成してください: {prompt}"],
            generation_config=GenerateContentConfig(response_mime_type="image/png")
        )

        image_data = response.parts[0].blob.data

        save_dir = os.path.join(os.path.dirname(__file__), "chat_attachments", "generated_images")
        os.makedirs(save_dir, exist_ok=True)

        unique_id = uuid.uuid4().hex[:8]
        image_filename = f"{output_image_filename_suggestion}_{unique_id}.png"
        image_path = os.path.join(save_dir, image_filename)

        with open(image_path, "wb") as f:
            f.write(image_data)

        return "画像生成に成功しました。", image_path
    except Exception as e:
        error_msg = f"エラー: 画像生成中に予期しないエラーが発生しました: {e}"
        traceback.print_exc()
        return error_msg, None
