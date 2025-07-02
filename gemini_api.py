import google.genai as genai
# ContentとPartは、もはや我々が直接作る必要はない
# from google.ai.generativelanguage import Content, Part
import os
import io
import json
import traceback
from typing import Optional, List
from PIL import Image

import config_manager
from utils import save_message_to_log, load_chat_log
from character_manager import get_character_files_paths

_gemini_client = None

def configure_google_api(api_key_name: str):
    global _gemini_client
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        _gemini_client = None
        return False, f"APIキー名 '{api_key_name}' に有効なキーが設定されていません。"
    try:
        _gemini_client = genai.Client(api_key=api_key)
        print(f"Google GenAI Client initialized successfully for API key '{api_key_name}'.")
        return True, None
    except Exception as e:
        _gemini_client = None
        return False, f"APIキー '{api_key_name}' での genai.Client 初期化中にエラー: {e}"

def send_multimodal_to_gemini(character_name: str, model_name: str, parts: list, api_history_limit_option: str, api_key_name: str):
    configure_google_api(api_key_name)

    if not _gemini_client:
        return "エラー: Geminiクライアントが初期化されていません。UIから有効なAPIキーを選択してください。", None

    try:
        # --- 1. 履歴とシステムプロンプトを「辞書のリスト」として構築 ---
        log_file, sys_prompt_file, _, _ = get_character_files_paths(character_name)
        history = load_chat_log(log_file, character_name)
        if api_history_limit_option.isdigit():
            limit = int(api_history_limit_option)
            if len(history) > limit * 2:
                history = history[-(limit*2):]

        system_instruction = ""
        if sys_prompt_file and os.path.exists(sys_prompt_file):
            with open(sys_prompt_file, 'r', encoding='utf-8') as f:
                system_instruction = f.read()

        # Content/Partオブジェクトは一切使わない。全てを辞書とリストで構成する。
        final_contents = []
        if system_instruction:
            final_contents.append({'role': 'user', 'parts': [{'text': system_instruction}]})
            final_contents.append({'role': 'model', 'parts': [{'text': "承知いたしました。"}]})

        for msg in history:
            if msg.get('content'):
                final_contents.append({
                    'role': msg['role'],
                    'parts': [{'text': msg.get('content', '')}]
                })

        # --- 2. ユーザーの新しい入力も「辞書のリスト」として構築 ---
        user_parts = []
        for part in parts:
            if isinstance(part, str) and part:
                user_parts.append({'text': part})
            elif isinstance(part, Image.Image):
                img_byte_arr = io.BytesIO()
                save_image = part
                if part.mode in ('RGBA', 'P'):
                    save_image = part.convert('RGB')
                save_image.save(img_byte_arr, format='JPEG')
                user_parts.append({
                    'inline_data': {
                        'mime_type': 'image/jpeg',
                        'data': img_byte_arr.getvalue()
                    }
                })

        if user_parts:
            final_contents.append({'role': 'user', 'parts': user_parts})

        if not final_contents or (final_contents[-1]['role'] == 'model' and not user_parts):
            return "エラー: 送信するコンテンツがありません。", None

        # --- 3. 正しい関数を、正しいデータ形式で呼び出す ---
        response = _gemini_client.models.generate_content(
            model=f"models/{model_name}",
            contents=final_contents  # 辞書とリストで構成されたペイロード
        )

        return response.text, None

    except Exception as e:
        traceback.print_exc()
        return f"エラー: モデル '{model_name}' との通信中に予期しないエラーが発生しました: {e}", None
