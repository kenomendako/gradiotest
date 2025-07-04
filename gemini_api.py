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
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage # SystemMessage をインポート

# LangGraphエージェント呼び出し関数
def invoke_nexus_agent(character_name: str, model_name: str, parts: list, api_history_limit_option: str, api_key_name: str):
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return f"エラー: APIキー名 '{api_key_name}' に有効なキーが設定されていません。", None
    try:
        log_file, sys_prompt_file, _, _ = get_character_files_paths(character_name) # sys_prompt_file を取得

        messages = [] # 型ヒントを List[Union[SystemMessage, HumanMessage, AIMessage]] のように後で修正する可能性

        # 1. システムプロンプトを読み込み、SystemMessageとして追加
        system_prompt_content = ""
        if sys_prompt_file and os.path.exists(sys_prompt_file):
            with open(sys_prompt_file, 'r', encoding='utf-8') as f:
                system_prompt_content = f.read().strip()

        if system_prompt_content:
            messages.append(SystemMessage(content=system_prompt_content))
        else:
            # システムプロンプトがない場合でも、空のSystemMessageを追加するか、あるいは何もしないか。
            # Geminiの厳密な形式に従うなら、何らかのSystemMessageが先頭にあることが望ましいかもしれない。
            # ここでは、ファイルが存在し内容がある場合のみ追加する。
            print(f"警告: キャラクター '{character_name}' のシステムプロンプトファイルが見つからないか空です。")

        # 2. 会話履歴をHumanMessageとAIMessageのペアとして追加
        raw_history = utils.load_chat_log(log_file, character_name)
        for h_item in raw_history:
            role = h_item.get('role')
            content = h_item.get('content', '').strip()
            if not content: # コンテンツが空のメッセージはスキップ
                continue

            if role == 'model' or role == 'assistant' or role == character_name:
                messages.append(AIMessage(content=content))
            elif role == 'user' or role == 'human':
                messages.append(HumanMessage(content=content))
            # 古い形式のシステムメッセージや不明なロールはここでは無視する方針

        # 3. API履歴制限の適用 (SystemMessageは常に保持)
        history_messages = []
        if messages and isinstance(messages[0], SystemMessage):
            history_messages.append(messages.pop(0)) # SystemMessageを一時的に取り出す

        limit = 0
        if api_history_limit_option and api_history_limit_option.isdigit():
            limit = int(api_history_limit_option)

        if limit > 0:
            if len(messages) > limit: # limit は Human/AIメッセージのペア数ではなく、総メッセージ数
                messages = messages[-limit:]

        # SystemMessageをリストの先頭に戻す
        if history_messages: # history_messages には SystemMessage が一つだけ入っている想定
            messages = history_messages + messages

        # 4. ユーザーの最新の入力をHumanMessageとして追加
        # parts は Gradio から渡される [text, Image, text, ...] のようなリスト
        # これを適切に HumanMessage の content に変換する
        # LangChain HumanMessage content は文字列かリスト[dict] (text or image)

        # マルチモーダル対応のためのcontentリスト
        user_message_content_parts = []
        text_buffer = []

        for part_item in parts:
            if isinstance(part_item, str):
                text_buffer.append(part_item)
            elif isinstance(part_item, Image.Image):
                if text_buffer: # 画像の前にテキストがあれば、それを先に追加
                    user_message_content_parts.append({"type": "text", "text": "\n".join(text_buffer).strip()})
                    text_buffer = [] # バッファをクリア

                # 画像をインラインデータとして追加 (base64エンコードはLangChain側で行われる想定)
                # LangChainのHumanMessageはPillow Imageオブジェクトを直接扱える
                user_message_content_parts.append({"type": "image_url", "image_url": part_item}) # Pillow Imageを直接渡す

        if text_buffer: # 最後に残ったテキストがあれば追加
            user_message_content_parts.append({"type": "text", "text": "\n".join(text_buffer).strip()})

        if user_message_content_parts:
            # HumanMessageのcontentは、単一の文字列か、辞書のリスト
            # user_message_content_partsが要素1つでそれがtextなら文字列、それ以外ならリスト
            if len(user_message_content_parts) == 1 and user_message_content_parts[0]["type"] == "text":
                messages.append(HumanMessage(content=user_message_content_parts[0]["text"]))
            else:
                messages.append(HumanMessage(content=user_message_content_parts))
        # 画像のみ、あるいはテキストのみの場合も上記で処理される

        initial_state = {
            "messages": messages, # 完成したメッセージリスト
            "character_name": character_name,
            "api_key": api_key,
            "final_model_name": model_name, # ★★★ UIで選択されたモデル名をstateに追加 ★★★
        }

        print(f"--- LangGraphエージェント呼び出し (Character: {character_name}, Final Model by User: {model_name}) ---")
        final_state = app.invoke(initial_state)
        print("--- LangGraphエージェント実行完了 ---")

        # 最後の、AIメッセージを、応答として、取得
        response_text = "[エージェントからの応答がありませんでした]" # デフォルト
        if final_state and final_state.get('messages') and isinstance(final_state['messages'][-1], AIMessage):
            response_text = final_state['messages'][-1].content
        elif final_state and final_state.get('messages') and final_state['messages'][-1]: # AIMessageでない場合もcontentを試みる
             response_text = str(final_state['messages'][-1].content if hasattr(final_state['messages'][-1], 'content') else final_state['messages'][-1])

        # ★★★【最後の真実】この、ブロック全体を、完全に、削除する ★★★
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
