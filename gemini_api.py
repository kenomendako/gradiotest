import google.genai as genai
import os
import io
import json # json は直接使われないが、一般的なので残しておく
import traceback
from typing import List # Optional は使われなくなったので削除
from PIL import Image

import config_manager
from utils import save_message_to_log, load_chat_log
from character_manager import get_character_files_paths
from agent.graph import app # ★ LangGraphアプリケーションをインポート

# APIキーが設定されたかどうかを示すフラグ
_gemini_client_configured = False

def configure_google_api(api_key_name: str):
    global _gemini_client_configured
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        _gemini_client_configured = False
        return False, f"APIキー名 '{api_key_name}' に有効なキーが設定されていません。"
    try:
        # google-generativeai ライブラリの推奨に従い genai.configure() を使用
        genai.configure(api_key=api_key)
        print(f"Google GenAI configured successfully for API key '{api_key_name}'.")
        _gemini_client_configured = True
        return True, None
    except Exception as e:
        _gemini_client_configured = False
        return False, f"APIキー '{api_key_name}' での genai.configure 中にエラー: {e}"

# 新しいLangGraphエージェント呼び出し関数
def invoke_nexus_agent(character_name: str, model_name: str, parts: list, api_history_limit_option: str, api_key_name: str):
    # APIキー設定（各ノードがこれを利用する前に、ここで一度設定する）
    ok, msg = configure_google_api(api_key_name)
    if not ok:
        return f"エラー: APIキーの設定に失敗しました: {msg}", None

    if not _gemini_client_configured: # 設定失敗時だけでなく、未設定の場合もチェック
        return f"エラー: Google APIキーが設定されていません。", None

    try:
        log_file, sys_prompt_file, _, _ = get_character_files_paths(character_name)

        raw_history = load_chat_log(log_file, character_name)

        formatted_history = []
        for h_item in raw_history:
            formatted_history.append({
                "role": h_item["role"],
                "parts": [h_item["content"]]
            })

        limit = 0
        if api_history_limit_option and api_history_limit_option.isdigit():
            limit = int(api_history_limit_option)

        if limit > 0 and len(formatted_history) > limit:
            formatted_history = formatted_history[-limit:]

        initial_state = {
            "input_parts": parts,
            "chat_history": formatted_history,
        }

        print(f"--- LangGraphエージェント呼び出し (Character: {character_name}, UI Model: {model_name}) ---")
        final_state = app.invoke(initial_state)
        print("--- LangGraphエージェント実行完了 ---")

        response_text = final_state.get("final_response", "[エージェントからの応答がありませんでした]")

        user_input_text = ""
        for p in parts:
            if isinstance(p, str):
                user_input_text = p
                break
        if not user_input_text and parts:
             user_input_text = "[画像またはファイル入力]"

        if user_input_text:
             save_message_to_log(log_file, character_name, user_input_text, response_text)

        return response_text, None

    except Exception as e:
        traceback.print_exc()
        return f"エラー: エージェントの実行中にエラーが発生しました: {e}", None

# 既存の send_multimodal_to_gemini 関数 (直接モデルを呼び出すバージョン)
def send_multimodal_to_gemini(character_name: str, model_name: str, parts: list, api_history_limit_option: str, api_key_name: str):
    ok, msg = configure_google_api(api_key_name)
    if not ok:
        return f"エラー: APIキーの設定に失敗しました: {msg}", None

    if not _gemini_client_configured:
         return "エラー: Google APIキーが設定されていません。", None

    try:
        log_file, sys_prompt_file, _, _ = get_character_files_paths(character_name)
        raw_history = load_chat_log(log_file, character_name) # load_chat_log は content を持つ辞書のリスト

        limit = 0
        if api_history_limit_option and api_history_limit_option.isdigit():
            limit = int(api_history_limit_option)

        if limit > 0 and len(raw_history) > limit:
            raw_history = raw_history[-limit:]

        system_instruction_text = ""
        if sys_prompt_file and os.path.exists(sys_prompt_file):
            with open(sys_prompt_file, 'r', encoding='utf-8') as f:
                system_instruction_text = f.read()

        # APIに渡す形式の履歴を作成
        # genai.GenerativeModel.generate_content() は、'role' と 'parts' を持つ辞書のリストを期待
        # 'parts' は、文字列、Imageオブジェクト、または Part オブジェクトのリスト
        model_history_for_direct_call = []
        for h_item in raw_history:
            model_history_for_direct_call.append({
                "role": h_item["role"],
                "parts": [h_item["content"]] # content を文字列 part としてリストに格納
            })

        user_message_parts_for_direct_call = []
        for part_data in parts:
            # 文字列もImageオブジェクトも直接partsリストに追加できる
            user_message_parts_for_direct_call.append(part_data)

        if not user_message_parts_for_direct_call:
            return "エラー: 送信するコンテンツがありません。", None

        model_to_call_name = f"models/{model_name}"
        try:
            gen_model = genai.GenerativeModel(
                model_to_call_name,
                system_instruction=system_instruction_text if system_instruction_text else None
            )
        except Exception as e:
            return f"エラー: モデル '{model_to_call_name}' の初期化に失敗しました: {e}", None

        # 履歴と新しいユーザーメッセージを結合してAPIに渡す
        messages_for_api_direct_call = model_history_for_direct_call + [{'role': 'user', 'parts': user_message_parts_for_direct_call}]

        response = gen_model.generate_content(messages_for_api_direct_call)

        user_input_text = ""
        for p in parts:
            if isinstance(p, str):
                user_input_text = p
                break
        if not user_input_text and parts:
             user_input_text = "[画像またはファイル入力]"
        if user_input_text:
             save_message_to_log(log_file, character_name, user_input_text, response.text)

        return response.text, None

    except Exception as e:
        traceback.print_exc()
        # response オブジェクトが存在し、prompt_feedback がある場合、それもエラーメッセージに含める
        error_message = f"エラー: モデル '{model_name}' との通信中に予期しないエラーが発生しました: {e}"
        if 'response' in locals() and hasattr(response, 'prompt_feedback'):
            error_message += f"\nプロンプトフィードバック: {response.prompt_feedback}"
        return error_message, None
