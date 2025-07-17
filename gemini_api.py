# gemini_api.py の内容を、以下の、最終版で、完全に、置き換えてください

import traceback
from typing import Any, List, Union, Optional, Dict
import os
import io
import base64
import re
from PIL import Image
import google.genai as genai

from agent.graph import app
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
import config_manager
import utils
import mem0_manager
from character_manager import get_character_files_paths

# (このファイル内の他の関数は変更ありません)

def invoke_nexus_agent(*args: Any) -> str:
    (textbox_content, chatbot_history, current_character_name, current_model_name,
     current_api_key_name_state, file_input_list, add_timestamp_checkbox,
     send_thoughts_state, api_history_limit_state,
     send_notepad_state, use_common_prompt_state) = args

    api_key = config_manager.API_KEYS.get(current_api_key_name_state)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return f"[エラー: APIキー '{current_api_key_name_state}' が有効ではありません。]"

    user_input_text = textbox_content.strip() if textbox_content else ""
    if not user_input_text:
         return "[エラー: テキスト入力がありません]"

    messages = []
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

    messages.append(HumanMessage(content=user_input_text))

    # ★★★ ここを修正: initial_stateにmodel_nameを追加 ★★★
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
            mem0_instance.add([
                {"role": "user", "content": user_input_text},
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
