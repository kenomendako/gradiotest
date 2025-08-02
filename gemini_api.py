import traceback
from typing import Any, List, Union, Optional, Dict
import os
import io
import base64
from PIL import Image
import google.genai as genai
import filetype

from agent.graph import app
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
import config_manager
import utils
from character_manager import get_character_files_paths

def invoke_nexus_agent(*args: Any) -> Dict[str, str]:
    # ★★★ UIから渡す引数を7つに削減 ★★★
    (textbox_content, chatbot_history, current_character_name,
     current_api_key_name_state, file_input_list, add_timestamp_checkbox,
     api_history_limit_state) = args

    # ★★★ 設定はconfig_managerから直接読み込む（変更なし、ただし重要）★★★
    effective_settings = config_manager.get_effective_settings(current_character_name)

    user_prompt_from_textbox = textbox_content.strip() if textbox_content else ""

    final_input_for_agent = {"text": user_prompt_from_textbox, "files": file_input_list or []}

    app = get_graph_for_character(current_character_name, current_api_key_name_state)

    config = {"configurable": {"character_name": current_character_name, "api_key_name": current_api_key_name_state}}

    response = app.invoke(final_input_for_agent, config)
    
    final_response_text = response.get("response", "[エージェントからの応答がありませんでした]")
    location_name = response.get("location_name", "（不明）")
    scenery = response.get("scenery", "（不明）")

    return {"response": final_response_text, "location_name": location_name, "scenery": scenery}


def count_input_tokens(character_name: str, api_key_name: str, parts: list):
    """【改修版】UIから大量の引数を渡さず、設定は内部で解決する"""
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"): return "トークン数: (APIキーエラー)"

    # ★★★ 設定はここで直接取得 ★★★
    effective_settings = config_manager.get_effective_settings(character_name)
    model_name = effective_settings["model_name"]
    send_core_memory = effective_settings["send_core_memory"]
    send_notepad_to_api = effective_settings["send_notepad"]
    use_common_prompt = effective_settings["use_common_prompt"]
    send_thoughts = effective_settings["send_thoughts"]
    send_scenery = effective_settings["send_scenery"]

    from agent.prompts import construct_prompt_for_character

    prompt_text, _ = construct_prompt_for_character(
        character_name=character_name,
        send_core_memory=send_core_memory,
        send_notepad_to_api=send_notepad_to_api,
        use_common_prompt=use_common_prompt,
        send_thoughts_to_api=send_thoughts,
        send_scenery_to_api=send_scenery
    )

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)

    processed_parts = []
    if prompt_text:
        processed_parts.append(prompt_text)

    for part in parts:
        if isinstance(part, str):
            processed_parts.append(part)
        elif isinstance(part, dict) and 'name' in part: # Gradio File object
            filepath = part['name']
            try:
                kind = filetype.guess(filepath)
                if kind and kind.mime.startswith("image/"):
                    processed_parts.append(Image.open(filepath))
                else: # Treat as text for token counting
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        processed_parts.append(f.read())
            except Exception:
                 with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        processed_parts.append(f.read())

    try:
        result = model.count_tokens(processed_parts)
        total_tokens = result.total_tokens
        return f"入力トークン数: {total_tokens}"
    except Exception as e:
        print(f"Token count error: {e}")
        return f"トークン数: (計算エラー)"
