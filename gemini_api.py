# -*- coding: utf-8 -*-
# ##############################################################################
# #   AIへの最重要指示: このファイルは `google-genai` SDK を使用します。
# #   詳細は `AI_DEVELOPMENT_GUIDELINES.md` を参照してください。
# ##############################################################################
from google import genai
import os
import json
import traceback
from typing import Optional, List, Dict
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

# --- メインのAPI送信関数 ---
def send_to_gemini(system_prompt: str, chat_history: List[Dict[str, str]], user_prompt: str, model_name: str) -> tuple[Optional[str], Optional[str]]:
    try:
        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=system_prompt,
            safety_settings=config_manager.SAFETY_CONFIG
        )

        # 新SDKでは、単純な辞書のリストを渡す
        contents = chat_history + [{"role": "user", "parts": [user_prompt]}]

        response = model.generate_content(contents)

        return response.text.strip(), None # 画像パスは別途実装

    except Exception as e:
        print(f"Gemini API通信エラー: {e}")
        traceback.print_exc()
        return f"エラー: Gemini APIとの通信中に予期しないエラーが発生しました: {e}", None

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

        model = genai.GenerativeModel(
            model_name=alarm_model_name,
            system_instruction=system_prompt,
            safety_settings=config_manager.SAFETY_CONFIG
        )

        # 履歴構築
        chat_history = load_chat_log(log_file_path, character_name)
        history_for_api = chat_history[-(alarm_api_history_turns * 2):] if alarm_api_history_turns > 0 else []

        response = model.generate_content(history_for_api)
        return response.text.strip()

    except Exception as e:
        print(f"アラーム用モデル通信エラー: {e}")
        traceback.print_exc()
        return f"【アラームエラー】API通信失敗: {e}"
