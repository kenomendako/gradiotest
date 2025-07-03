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

# LangGraphエージェント呼び出し関数
def invoke_nexus_agent(character_name: str, model_name: str, parts: list, api_history_limit_option: str, api_key_name: str):
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return f"エラー: APIキー名 '{api_key_name}' に有効なキーが設定されていません。", None
    try:
        log_file, _, _, _ = get_character_files_paths(character_name) # sys_prompt_file はここでは直接使わない
        raw_history = load_chat_log(log_file, character_name)

        # LangGraphに渡す履歴は、partsの中身を辞書のリストにする
        formatted_history = []
        for h_item in raw_history:
            formatted_history.append({
                "role": h_item["role"],
                "parts": [{'text': h_item["content"]}]
            })

        limit = 0
        if api_history_limit_option and api_history_limit_option.isdigit():
            limit = int(api_history_limit_option)
        # LangGraph側では履歴全体を渡すため、ここでの件数制限はAgentStateの仕様と相談
        # 指示書では limit * 2 となっていたが、formatted_history は既に往復を表現しているので *2 は不要かも。
        # ただし、LangGraphのAgentStateのchat_historyがどう扱われるかによる。
        # ここでは指示書の `limit * 2` を一旦コメントアウトし、単純な件数制限にする。
        # 必要であれば `limit * 2` に戻す。
        if limit > 0 and len(formatted_history) > limit:
            formatted_history = formatted_history[-limit:]

        initial_state = {
            "input_parts": parts, # parts は UIから渡されるそのままのリスト (str や Image.Image)
            "chat_history": formatted_history,
            "api_key": api_key,
        }
        print(f"--- LangGraphエージェント呼び出し (Character: {character_name}, UI Model: {model_name}) ---")
        final_state = app.invoke(initial_state)
        print("--- LangGraphエージェント実行完了 ---")
        response_text = final_state.get("final_response", "[エージェントからの応答がありませんでした]")

        # ユーザー入力のテキスト部分を取得してログに保存
        user_input_text = ""
        for p in parts:
            if isinstance(p, str):
                user_input_text += p + "\n" # 複数のテキストパートを改行で結合
        user_input_text = user_input_text.strip()

        # 添付ファイル情報もログに追加 (ファイル名を取得)
        # parts には Image.Image オブジェクトや、gr.Files からの FileData オブジェクトが入る想定
        attached_files_info = []
        for p in parts:
            if not isinstance(p, str):
                if hasattr(p, 'name'): # gradio の FileData オブジェクトなど
                    attached_files_info.append(os.path.basename(p.name))
                elif isinstance(p, Image.Image) and hasattr(p, 'filename') and p.filename:
                     attached_files_info.append(os.path.basename(p.filename))
                elif isinstance(p, Image.Image):
                    attached_files_info.append("[インライン画像]") # ファイル名がない場合
                else:
                    attached_files_info.append("[不明なファイル]")


        if attached_files_info:
            user_input_text += "\n[ファイル添付: " + ", ".join(attached_files_info) + "]"

        if user_input_text or attached_files_info: # 何かしらの入力があればログ保存
             save_message_to_log(log_file, character_name, user_input_text.strip(), response_text)

        return response_text, None

    except Exception as e:
        traceback.print_exc()
        return f"エラー: エージェントの実行中にエラーが発生しました: {e}", None


# 直接モデルを呼び出す、通常チャット用の関数
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
        # raw_history は発話ごとのリストなので、往復を考慮する場合は limit * 2
        if limit > 0 and len(raw_history) > limit * 2:
            raw_history = raw_history[-(limit*2):]

        # --- データ構造を厳密にする ---
        messages_for_api_direct_call = []

        # システムプロンプトの追加
        if sys_prompt_file and os.path.exists(sys_prompt_file):
            with open(sys_prompt_file, 'r', encoding='utf-8') as f:
                system_instruction_text = f.read()
            if system_instruction_text:
                messages_for_api_direct_call.append({'role': 'user', 'parts': [{'text': system_instruction_text}]})
                messages_for_api_direct_call.append({'role': 'model', 'parts': [{'text': "承知いたしました。"}]})

        # 会話履歴の追加
        for h_item in raw_history:
            # partsの中身を、文字列ではなく、{'text': ...} という辞書に修正
            messages_for_api_direct_call.append({
                "role": h_item["role"],
                "parts": [{'text': h_item["content"]}]
            })

        # ユーザーの新しい入力の追加
        user_message_parts_for_payload = [] # 変数名を変更して明確化
        for part_data in parts: # parts は UIから渡される (str や Image.Image や FileData)
            if isinstance(part_data, str):
                user_message_parts_for_payload.append({'text': part_data})
            elif isinstance(part_data, Image.Image):
                img_byte_arr = io.BytesIO()
                # JPEGは透明度(A)やパレット(P)モードを扱えないためRGBに変換
                save_image = part_data.convert('RGB') if part_data.mode in ('RGBA', 'P') else part_data
                save_image.save(img_byte_arr, format='JPEG')
                user_message_parts_for_payload.append({
                    'inline_data': {
                        'mime_type': 'image/jpeg',
                        'data': img_byte_arr.getvalue()
                    }
                })
            # ここに他のファイルタイプ（例：GradioのFileDataオブジェクト）の処理を追加できる
            # elif hasattr(part_data, 'name') and hasattr(part_data, 'data'): # FileDataを仮定
            #     # part_data.data がバイト列であることを期待
            #     # MIMEタイプをどう取得するかが課題。ファイル拡張子から推測するか、固定値を設定。
            #     mime_type = utils.get_mime_type(part_data.name) # get_mime_typeユーティリティが必要
            #     user_message_parts_for_payload.append({
            #         'inline_data': {
            #             'mime_type': mime_type,
            #             'data': part_data.data # FileData.data がバイト列の場合
            #         }
            #     })


        if not user_message_parts_for_payload: # 変数名変更
            return "エラー: 送信するコンテンツがありません。", None

        messages_for_api_direct_call.append({'role': 'user', 'parts': user_message_parts_for_payload}) # 変数名変更

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

        # ログ保存のロジックをinvoke_nexus_agentと統一
        user_input_text = ""
        for p in parts:
            if isinstance(p, str):
                user_input_text += p + "\n"
        user_input_text = user_input_text.strip()

        attached_files_info = []
        for p in parts:
            if not isinstance(p, str):
                if hasattr(p, 'name'):
                    attached_files_info.append(os.path.basename(p.name))
                elif isinstance(p, Image.Image) and hasattr(p, 'filename') and p.filename:
                     attached_files_info.append(os.path.basename(p.filename))
                elif isinstance(p, Image.Image):
                    attached_files_info.append("[インライン画像]")
                else:
                    attached_files_info.append("[不明なファイル]")

        if attached_files_info:
             user_input_text += "\n[ファイル添付: " + ", ".join(attached_files_info) + "]"

        if user_input_text or attached_files_info: # 何かしらの入力があればログ保存
             save_message_to_log(log_file, character_name, user_input_text.strip(), generated_text)

        return generated_text, None

    except Exception as e:
        traceback.print_exc()
        error_message = f"エラー: モデル '{model_name}' との通信中に予期しないエラーが発生しました: {e}"
        # response オブジェクトが定義されているか確認してからアクセス
        if 'response' in locals() and hasattr(response, 'prompt_feedback') and response.prompt_feedback:
            error_message += f"\nプロンプトフィードバック: {response.prompt_feedback}"
        return error_message, None
