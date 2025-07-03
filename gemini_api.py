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
from langchain_core.messages import HumanMessage, AIMessage # LangChainメッセージ形式をインポート

# LangGraphエージェント呼び出し関数
def invoke_nexus_agent(character_name: str, model_name: str, parts: list, api_history_limit_option: str, api_key_name: str):
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return f"エラー: APIキー名 '{api_key_name}' に有効なキーが設定されていません。", None
    try:
        log_file, _, _, _ = get_character_files_paths(character_name)
        raw_history = utils.load_chat_log(log_file, character_name) # utils.load_chat_log は [{'role': 'user', 'content': '...'}, ...] の形式を想定

        # ★ LangChain形式の、メッセージリストを、作成
        messages: list[HumanMessage | AIMessage] = [] # 型ヒント
        for h_item in raw_history:
            if h_item.get('role') == 'model' or h_item.get('role') == 'assistant' or h_item.get('role') == character_name: # 'assistant' やキャラ名もモデル側とみなす
                messages.append(AIMessage(content=h_item['content']))
            else: # 'user' or 'human' or その他はユーザーとみなす
                messages.append(HumanMessage(content=h_item['content']))

        # API履歴制限の適用 (メッセージオブジェクトのリストに対して行う)
        limit = 0
        if api_history_limit_option and api_history_limit_option.isdigit():
            limit = int(api_history_limit_option)

        if limit > 0: # 0の場合は制限なし（全履歴）と解釈
            # ユーザーとAIの発話ペアで1往復なので、limit * 2 の件数を残すのが一般的だが、
            # LangChainのメッセージリストでは単純に末尾からlimit件数で良い場合もある。
            # ここでは、user/aiのペアではなく、単純にメッセージ数で制限する。
            # もし往復で制限したいなら、raw_historyの段階で処理が必要。
            # 今回のAgentStateはmessagesのリストなので、単純にメッセージ数で制限。
            if len(messages) > limit: # limit はメッセージ数そのものとする
                 messages = messages[-limit:]


        # ユーザーの、最新の、入力を、追加
        # (この、部分は、テキストと、画像が、混在する場合の、処理が、必要になるが、一旦、テキストのみで)
        # parts は Gradio から渡される [text, Image, text, ...] のようなリスト
        # これを適切に HumanMessage の content に変換する
        # LangChain HumanMessage content は文字列かリスト[dict] (text or image)

        # まずは指示書通りテキストのみを連結
        user_input_text_parts = [p for p in parts if isinstance(p, str)]
        user_input_text = "\n".join(user_input_text_parts).strip()

        # TODO: 画像も parts に含まれる場合、HumanMessageのcontentをリスト形式にする必要がある
        # 例: HumanMessage(content=[{"type": "text", "text": "見て"}, {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}])
        # 今回はテキストのみを扱う
        if user_input_text: # テキスト入力がある場合のみメッセージ追加
            messages.append(HumanMessage(content=user_input_text))
        elif any(isinstance(p, Image.Image) for p in parts): # 画像のみの場合 (テキストなし)
            # 画像のみの場合の処理は現状のAgentStateとcall_model_nodeでは直接扱えない
            # perceive_input_nodeのような前処理が別途必要になるか、
            # HumanMessageに画像を含める対応が必要。
            # ここでは、テキストがない場合は空のHumanMessageを追加しないようにする。
            # あるいは、何らかのプレースホルダテキストを追加することも考えられる。
            # 今回は、テキストがなければメッセージを追加しない方針とする。
            # ただし、partsが空でない限り、何らかのユーザー入力があったとみなすため、
            # ログ保存のためにはuser_input_textを別途作成する必要がある。
            pass


        initial_state = {
            "messages": messages,
            "character_name": character_name,
            "api_key": api_key,
        }

        print(f"--- LangGraphエージェント呼び出し (Character: {character_name}, Model in UI: {model_name}) ---") # model_nameはLangGraph内では直接使われない
        final_state = app.invoke(initial_state)
        print("--- LangGraphエージェント実行完了 ---")

        # 最後の、AIメッセージを、応答として、取得
        response_text = "[エージェントからの応答がありませんでした]" # デフォルト
        if final_state and final_state.get('messages') and isinstance(final_state['messages'][-1], AIMessage):
            response_text = final_state['messages'][-1].content
        elif final_state and final_state.get('messages') and final_state['messages'][-1]: # AIMessageでない場合もcontentを試みる
             response_text = str(final_state['messages'][-1].content if hasattr(final_state['messages'][-1], 'content') else final_state['messages'][-1])


        # --- ログ保存ロジック (基本的に変更なしだが、user_input_textの扱いを再確認) ---
        # ユーザー入力テキスト (user_input_text) は上でpartsから作成済み
        # 添付ファイル情報もログに追加
        # この部分は、partsを元にUI表示用のユーザー発言を作成するのと同様のロジック
        log_user_input = ""
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
