import google.genai as genai
import os
import io
import json
import traceback
from typing import List
from PIL import Image

import config_manager
from utils import save_message_to_log, load_chat_log
from character_manager import get_character_files_paths
from agent.graph import app # LangGraphアプリケーションをインポート

# configure_google_api 関数は削除されました。
# _gemini_client_configured フラグも削除されました。

# 新しいLangGraphエージェント呼び出し関数
def invoke_nexus_agent(character_name: str, model_name: str, parts: list, api_history_limit_option: str, api_key_name: str):
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return f"エラー: APIキー名 '{api_key_name}' に有効なキーが設定されていません。", None

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
            "api_key": api_key, # ★APIキーをStateに追加
        }

        print(f"--- LangGraphエージェント呼び出し (Character: {character_name}, UI Model: {model_name}) ---")
        # LangGraphアプリケーションを実行
        final_state = app.invoke(initial_state)
        print("--- LangGraphエージェント実行完了 ---")

        response_text = final_state.get("final_response", "[エージェントからの応答がありませんでした]")

        user_input_text = ""
        for p in parts:
            if isinstance(p, str):
                user_input_text = p
                break
        if not user_input_text and parts: # テキストがないが画像などがある場合
             user_input_text = "[画像またはファイル入力]"

        if user_input_text: # 何かしらのユーザー入力があった場合のみログ保存
             save_message_to_log(log_file, character_name, user_input_text, response_text)

        return response_text, None

    except Exception as e:
        traceback.print_exc()
        return f"エラー: エージェントの実行中にエラーが発生しました: {e}", None

# 既存の send_multimodal_to_gemini 関数 (直接モデルを呼び出すバージョン)
# この関数も新しいAPIキー処理方法に合わせる
def send_multimodal_to_gemini(character_name: str, model_name: str, parts: list, api_history_limit_option: str, api_key_name: str):
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return f"エラー: APIキー名 '{api_key_name}' に有効なキーが設定されていません。", None

    try:
        log_file, sys_prompt_file, _, _ = get_character_files_paths(character_name)
        raw_history = load_chat_log(log_file, character_name)

        limit = 0
        if api_history_limit_option and api_history_limit_option.isdigit():
            limit = int(api_history_limit_option)

        if limit > 0 and len(raw_history) > limit:
            raw_history = raw_history[-limit:]

        system_instruction_text = ""
        if sys_prompt_file and os.path.exists(sys_prompt_file):
            with open(sys_prompt_file, 'r', encoding='utf-8') as f:
                system_instruction_text = f.read()

        model_history_for_direct_call = []
        for h_item in raw_history:
            model_history_for_direct_call.append({
                "role": h_item["role"],
                "parts": [h_item["content"]]
            })

        user_message_parts_for_direct_call = []
        for part_data in parts:
            user_message_parts_for_direct_call.append(part_data)

        if not user_message_parts_for_direct_call:
            return "エラー: 送信するコンテンツがありません。", None

        model_to_call_name = f"models/{model_name}"
        client_for_direct_call = genai.Client(api_key=api_key)

        # messages_for_api_direct_call を構築
        messages_for_api_direct_call = []
        if system_instruction_text:
            # システムプロンプトを会話の先頭に追加 (ユーザーロールとして)
            messages_for_api_direct_call.append({'role': 'user', 'parts': [{'text': system_instruction_text}]})
            # モデルからの応答を仮定して追加 (オプション、モデルの挙動による)
            messages_for_api_direct_call.append({'role': 'model', 'parts': [{'text': "承知いたしました。"}]}) # もしくは "OK." など

        messages_for_api_direct_call.extend(model_history_for_direct_call)
        messages_for_api_direct_call.append({'role': 'user', 'parts': user_message_parts_for_direct_call})

        try:
            # client.models.generate_content を直接呼び出す
            response = client_for_direct_call.models.generate_content(
                model=model_to_call_name,
                contents=messages_for_api_direct_call
            )
        except Exception as e:
            # エラーメッセージにモデル名を含める
            traceback.print_exc()
            return f"エラー: モデル '{model_to_call_name}' でのコンテンツ生成中にエラーが発生しました: {e}", None

        # response.text が存在するか確認
        generated_text = "[応答なし]"
        if hasattr(response, 'text') and response.text:
            generated_text = response.text
        elif response.prompt_feedback and response.prompt_feedback.block_reason:
            generated_text = f"[応答ブロック: 安全性設定により応答がブロックされました。理由: {response.prompt_feedback.block_reason}]"

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
        error_message = f"エラー: モデル '{model_name}' との通信中に予期しないエラーが発生しました: {e}"
        # response オブジェクトが定義されているか確認してからアクセス
        if 'response' in locals() and hasattr(response, 'prompt_feedback') and response.prompt_feedback:
            error_message += f"\nプロンプトフィードバック: {response.prompt_feedback}"
        return error_message, None
