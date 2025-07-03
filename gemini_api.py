import google.genai as genai
import os
import io
import json
import traceback
from typing import List
from PIL import Image

import config_manager
# ★ save_message_to_log を直接呼び出すので、utils全体をインポート
import utils # 変更点: utils全体をインポート
from character_manager import get_character_files_paths
from agent.graph import app # LangGraphアプリケーションをインポート

# LangGraphエージェント呼び出し関数
def invoke_nexus_agent(character_name: str, model_name: str, parts: list, api_history_limit_option: str, api_key_name: str):
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return f"エラー: APIキー名 '{api_key_name}' に有効なキーが設定されていません。", None
    try:
        log_file, _, _, _ = get_character_files_paths(character_name)
        # raw_history は utils.load_chat_log を使う
        raw_history = utils.load_chat_log(log_file, character_name)


        formatted_history = []
        for h_item in raw_history:
            formatted_history.append({
                "role": h_item["role"],
                "parts": [{'text': h_item["content"]}]
            })

        limit = 0
        if api_history_limit_option and api_history_limit_option.isdigit():
            limit = int(api_history_limit_option)
        # 以前のコメントに基づき、limit*2 は適用しない形を維持
        if limit > 0 and len(formatted_history) > limit:
            formatted_history = formatted_history[-limit:]

        initial_state = {
            "input_parts": parts,
            "chat_history": formatted_history,
            "api_key": api_key,
        }
        print(f"--- LangGraphエージェント呼び出し (Character: {character_name}, UI Model: {model_name}) ---")
        final_state = app.invoke(initial_state)
        print("--- LangGraphエージェント実行完了 ---")
        response_text = final_state.get("final_response", "[エージェントからの応答がありませんでした]")

        # --- ログ保存ロジック修正 ---
        user_input_text = ""
        for p in parts:
            if isinstance(p, str):
                user_input_text += p + "\n"
        user_input_text = user_input_text.strip()

        # 添付ファイル情報もログに追加 (ファイル名を取得)
        attached_file_names = []
        for p in parts:
            if not isinstance(p, str):
                if hasattr(p, 'name'): # gradio の FileData オブジェクトなど
                    attached_file_names.append(os.path.basename(p.name))
                elif isinstance(p, Image.Image) and hasattr(p, 'filename') and p.filename:
                     attached_file_names.append(os.path.basename(p.filename))
                # Image.Imageでファイル名がない場合はログに含めない（以前は"[インライン画像]"としていたが、ユーザー入力テキストとの区別のため）

        if attached_file_names:
            user_input_text += "\n[ファイル添付: " + ", ".join(attached_file_names) + "]"

        # ユーザー入力が空でない場合のみログ保存
        if user_input_text.strip() or attached_file_names: # 添付ファイルだけでもログるように変更
            user_header = utils._get_user_header_from_log(log_file, character_name)
            # 1. ユーザーの発言を保存
            utils.save_message_to_log(log_file, user_header, user_input_text.strip())
            # 2. AIの応答を保存
            utils.save_message_to_log(log_file, f"## {character_name}:", response_text)
        # --- 修正ここまで ---

        return response_text, None

    except Exception as e:
        traceback.print_exc()
        return f"エラー: エージェントの実行中にエラーが発生しました: {e}", None


# 通常チャット用の関数
def send_multimodal_to_gemini(character_name: str, model_name: str, parts: list, api_history_limit_option: str, api_key_name: str):
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return f"エラー: APIキー名 '{api_key_name}' に有効なキーが設定されていません。", None

    try:
        log_file, sys_prompt_file, _, _ = get_character_files_paths(character_name)
        raw_history = utils.load_chat_log(log_file, character_name)

        limit = 0
        if api_history_limit_option and api_history_limit_option.isdigit():
            limit = int(api_history_limit_option)
        if limit > 0 and len(raw_history) > limit * 2:
            raw_history = raw_history[-(limit*2):]

        messages_for_api_direct_call = []
        if sys_prompt_file and os.path.exists(sys_prompt_file):
            with open(sys_prompt_file, 'r', encoding='utf-8') as f:
                system_instruction_text = f.read()
            if system_instruction_text:
                messages_for_api_direct_call.append({'role': 'user', 'parts': [{'text': system_instruction_text}]})
                messages_for_api_direct_call.append({'role': 'model', 'parts': [{'text': "承知いたしました。"}]})

        for h_item in raw_history:
            messages_for_api_direct_call.append({
                "role": h_item["role"],
                "parts": [{'text': h_item["content"]}]
            })

        user_message_parts_for_payload = []
        for part_data in parts:
            if isinstance(part_data, str):
                user_message_parts_for_payload.append({'text': part_data})
            elif isinstance(part_data, Image.Image):
                img_byte_arr = io.BytesIO()
                save_image = part_data.convert('RGB') if part_data.mode in ('RGBA', 'P') else part_data
                save_image.save(img_byte_arr, format='JPEG')
                user_message_parts_for_payload.append({
                    'inline_data': {'mime_type': 'image/jpeg', 'data': img_byte_arr.getvalue()}
                })

        if not user_message_parts_for_payload:
            return "エラー: 送信するコンテンツがありません。", None

        messages_for_api_direct_call.append({'role': 'user', 'parts': user_message_parts_for_payload})

        model_to_call_name = f"models/{model_name}"
        client_for_direct_call = genai.Client(api_key=api_key)
        response = client_for_direct_call.models.generate_content(
            model=model_to_call_name,
            contents=messages_for_api_direct_call
        )

        generated_text = "[応答なし]"
        if hasattr(response, 'text') and response.text:
            generated_text = response.text
        elif response.prompt_feedback and response.prompt_feedback.block_reason:
            generated_text = f"[応答ブロック: 理由: {response.prompt_feedback.block_reason}]"

        # --- ログ保存ロジック修正 ---
        user_input_text = ""
        for p in parts:
            if isinstance(p, str):
                user_input_text += p + "\n"
        user_input_text = user_input_text.strip()

        attached_file_names = []
        for p in parts:
            if not isinstance(p, str):
                if hasattr(p, 'name'):
                    attached_file_names.append(os.path.basename(p.name))
                elif isinstance(p, Image.Image) and hasattr(p, 'filename') and p.filename:
                     attached_file_names.append(os.path.basename(p.filename))

        if attached_file_names:
            user_input_text += "\n[ファイル添付: " + ", ".join(attached_file_names) + "]"

        if user_input_text.strip() or attached_file_names: # 添付ファイルだけでもログる
            user_header = utils._get_user_header_from_log(log_file, character_name)
            # 1. ユーザーの発言を保存
            utils.save_message_to_log(log_file, user_header, user_input_text.strip())
            # 2. AIの応答を保存
            utils.save_message_to_log(log_file, f"## {character_name}:", generated_text)
        # --- 修正ここまで ---

        return generated_text, None

    except Exception as e:
        traceback.print_exc()
        error_message = f"エラー: モデル '{model_name}' との通信中に予期しないエラーが発生しました: {e}"
        if 'response' in locals() and hasattr(response, 'prompt_feedback') and response.prompt_feedback: # responseが未定義の場合を考慮
            error_message += f"\nプロンプトフィードバック: {response.prompt_feedback}"
        return error_message, None
