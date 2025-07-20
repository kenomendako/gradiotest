import base64
import os
import traceback
from typing import Any

from langchain_core.messages import HumanMessage, AIMessage
from PIL import Image

import config_manager
import mem0_manager
import utils
from agent.graph import app
from character_manager import get_character_files_paths


def invoke_nexus_agent(*args: Any) -> str:
    (textbox_content, chatbot_history, current_character_name, current_model_name,
     current_api_key_name_state, file_input_list, add_timestamp_checkbox,
     send_thoughts_state, api_history_limit_state,
     send_notepad_state, use_common_prompt_state) = args

    api_key = config_manager.API_KEYS.get(current_api_key_name_state)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return f"[エラー: APIキー '{current_api_key_name_state}' が有効ではありません。]"

    user_input_text = textbox_content.strip() if textbox_content else ""
    if not user_input_text and not file_input_list:
         return "[エラー: テキスト入力またはファイル添付がありません]"

    messages = []
    
    # 既存の履歴を追加
    log_file, _, _, _, _ = get_character_files_paths(current_character_name)
    raw_history = utils.load_chat_log(log_file, current_character_name)
    limit = int(api_history_limit_state) if api_history_limit_state.isdigit() else 0
    if limit > 0 and len(raw_history) > limit * 2:
        raw_history = raw_history[-(limit * 2):]
    for h_item in raw_history:
        role, content = h_item.get('role'), h_item.get('content', '').strip()
        if not content: continue
        if role in ['model', 'assistant', current_character_name]:
            messages.append(AIMessage(content=content))
        elif role in ['user', 'human']:
            messages.append(HumanMessage(content=content))

    # ★★★ ここからが修正箇所 ★★★
    # 今回のユーザー入力を、テキストとファイルの両方に対応して構築
    user_message_parts = []
    if user_input_text:
        # タイムスタンプはUIハンドラ側で処理済みのため、ここでは純粋なテキストのみを扱う
        user_message_parts.append({"type": "text", "text": user_input_text})

    if file_input_list:
        for file_obj in file_input_list:
            filepath = file_obj.name
            try:
                # まず画像として開いてみる
                img = Image.open(filepath)
                img.verify() # 画像データが有効か軽くチェック

                # 画像を再度開いてBase64エンコード
                with open(filepath, "rb") as image_file:
                    img_base64 = base64.b64encode(image_file.read()).decode('utf-8')

                # MIMEタイプを拡張子から推測
                ext = os.path.splitext(filepath)[1].lower()
                mime_type = f"image/{ext[1:]}" if ext in ['.png', '.jpg', '.jpeg', '.webp', '.gif'] else "image/png"

                user_message_parts.append({
                    "type": "image_url",
                    "image_url": { "url": f"data:{mime_type};base64,{img_base64}"}
                })
                print(f"  - 画像ファイル '{os.path.basename(filepath)}' を処理しました。")

            except Exception as e:
                # 画像として開けなかった場合は、テキストファイルとして試す
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        text_content = f.read()
                    # テキストファイルの内容をプロンプトに含める
                    user_message_parts.append({
                        "type": "text",
                        "text": f"--- 添付ファイル「{os.path.basename(filepath)}」の内容 ---\n{text_content}\n--- ファイル内容ここまで ---"
                    })
                    print(f"  - テキストファイル '{os.path.basename(filepath)}' を処理しました。")
                except Exception as text_e:
                    # テキストとしても読めなかった場合
                    print(f"  - 警告: ファイル '{os.path.basename(filepath)}' は画像でもテキストでもないためスキップします。エラー: {text_e}")

    if user_message_parts:
        messages.append(HumanMessage(content=user_message_parts))
    # ★★★ 修正ここまで ★★★

    initial_state = {
        "messages": messages,
        "character_name": current_character_name,
        "api_key": api_key,
        "tavily_api_key": config_manager.TAVILY_API_KEY,
        "model_name": current_model_name,
    }

    try:
        final_state = app.invoke(initial_state)
        final_response_message = final_state['messages'][-1]

        try:
            mem0_instance = mem0_manager.get_mem0_instance(current_character_name, api_key)
            # HumanMessageのcontentはリスト形式なので、テキスト部分だけを抽出
            # ファイルの内容もテキストとして含まれるため、これでOK
            user_text_for_mem0 = "\n".join([part['text'] for part in user_message_parts if part['type'] == 'text' and part.get('text')])
            if user_text_for_mem0: # テキストがある場合のみ記憶
                mem0_instance.add([
                    {"role": "user", "content": user_text_for_mem0},
                    {"role": "assistant", "content": final_response_message.content}
                ], user_id=current_character_name)
                print("--- mem0への記憶成功 ---")
        except Exception as e:
            print(f"--- mem0への記憶中にエラー: {e} ---")
            traceback.print_exc()

        return final_response_message.content
    except Exception as e:
        print(f"--- エージェント実行エラー ---")
        traceback.print_exc()
        return f"[エージェント実行エラー: {e}]"
