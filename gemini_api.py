# -*- coding: utf-8 -*-
# ##############################################################################
# #   AIへの最重要指示: このファイルは `google-genai` SDK を使用します。
# #   詳細は `AI_DEVELOPMENT_GUIDELINES.md` を参照してください。
# ##############################################################################
from google import genai
from google.genai import types
import os
import json
import traceback
from PIL import Image
from io import BytesIO
from typing import Optional, List, Dict, Any
import uuid
import config_manager
from utils import load_chat_log

# --- SDKの初期化 ---
def configure_google_api(api_key_name: str) -> tuple[bool, str]:
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return False, f"APIキー名 '{api_key_name}' の有効なキーが未設定です。"
    try:
        genai.configure(api_key=api_key)
        print(f"Google GenAI SDK for API key '{api_key_name}' configured successfully.")
        return True, ""
    except Exception as e:
        return False, f"SDK設定中にエラー: {e}"

# --- メインのAPI送信関数（画像生成対応） ---
def send_to_gemini(
    system_prompt: str,
    chat_history: List[Dict[str, Any]],
    user_prompt: str,
    model_name: str,
    generate_image: bool = False
) -> tuple[Optional[str], Optional[str]]:
    """
    Gemini APIにリクエストを送信し、テキスト応答と画像パス（要求時）を返す。
    """
    try:
        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=system_prompt,
            safety_settings=config_manager.SAFETY_CONFIG
        )

        # 画像生成を要求する場合、generation_configを設定
        generation_config = {"response_mime_type": "image/png"} if generate_image else {}

        contents = chat_history + [{"role": "user", "parts": [user_prompt]}]

        response = model.generate_content(
            contents,
            generation_config=generation_config
        )

        text_response = None
        image_path = None

        for part in response.parts:
            if "text" in part:
                text_response = part.text
            if "blob" in part and part.blob.mime_type.startswith("image/"):
                image_data = part.blob.data
                pil_img = Image.open(BytesIO(image_data))

                save_dir = os.path.join(os.path.dirname(__file__), "chat_attachments", "generated_images")
                os.makedirs(save_dir, exist_ok=True)

                unique_id = uuid.uuid4().hex[:8]
                image_filename = f"gemini_image_{unique_id}.png"
                image_path = os.path.join(save_dir, image_filename)

                pil_img.save(image_path, "PNG")
                print(f"生成された画像を '{image_path}' に保存しました。")

        return text_response.strip() if text_response else "", image_path

    except Exception as e:
        print(f"Gemini API通信エラー: {e}")
        traceback.print_exc()
        return f"エラー: Gemini APIとの通信中に予期しないエラーが発生しました: {e}", None

# --- UIハンドラが期待する画像生成関数（ラッパー） ---
def generate_image_with_gemini(prompt: str, output_image_filename_suggestion: str) -> tuple[Optional[str], Optional[str]]:
    """
    画像生成に特化したラッパー関数。内部でsend_to_geminiを呼び出す。
    モデルはFlashモデルに固定。
    """
    # ここではシステムプロンプトや履歴は空で、ユーザープロンプトのみを渡す
    model_name = "gemini-1.5-flash-latest" # お客様ご希望のモデル

    # 画像生成APIを呼び出す
    text_response, image_path = send_to_gemini(
        system_prompt="You are an image generation engine. Create an image based on the user\'s prompt.",
        chat_history=[],
        user_prompt=prompt,
        model_name=model_name,
        generate_image=True
    )

    if image_path:
        # ファイル名を提案されたものに変更する
        try:
            new_filename = f"{output_image_filename_suggestion}_{uuid.uuid4().hex[:8]}.png"
            new_image_path = os.path.join(os.path.dirname(image_path), new_filename)
            os.rename(image_path, new_image_path)
            return text_response or "画像生成に成功しました。", new_image_path
        except Exception as e:
            print(f"画像ファイルのリネーム中にエラー: {e}")
            return text_response or "画像生成には成功しましたが、リネームに失敗しました。", image_path
    else:
        return text_response or "画像生成に失敗しました。", None


# --- アラーム用のAPI送信関数 ---
def send_alarm_to_gemini(character_name: str, theme: str, flash_prompt_template: Optional[str], alarm_model_name: str, api_key_name: str, log_file_path: str, alarm_api_history_turns: int) -> str:
    if not configure_google_api(api_key_name):
        return "【アラームエラー】APIキー設定失敗"

    try:
        # システムプロンプト構築
        if flash_prompt_template:
            system_prompt = flash_prompt_template.replace("[キャラクター名]", character_name).replace("[テーマ内容]", theme)
        else:
            system_prompt = f"あなたはキャラクター「{character_name}」です。テーマ「{theme}」について、ユーザーに送る短いメッセージを生成してください。"

        # 履歴構築
        chat_history = load_chat_log(log_file_path, character_name)
        history_for_api = chat_history[-(alarm_api_history_turns * 2):] if alarm_api_history_turns > 0 else []

        # send_to_geminiを呼び出す
        text_response, _ = send_to_gemini(
            system_prompt=system_prompt,
            chat_history=history_for_api,
            user_prompt="", # アラームの場合は、履歴とシステムプロンプトで応答を生成
            model_name=alarm_model_name,
            generate_image=False # アラームでは画像生成しない
        )

        return text_response or "（応答がありませんでした）"

    except Exception as e:
        print(f"アラーム用モデル通信エラー: {e}")
        traceback.print_exc()
        return f"【アラームエラー】API通信失敗: {e}"
