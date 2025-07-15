# gemini_api.py (vFinal: Streaming Support)

import google.genai as genai
import os
import io
import json
import traceback
from typing import List, Union, Optional, Dict, Generator
from PIL import Image
import base64
import re

import config_manager
import utils
from character_manager import get_character_files_paths
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

_model_token_limits_cache: Dict[str, Dict[str, int]] = {}

def get_model_token_limits(model_name: str, api_key: str) -> Optional[Dict[str, int]]:
    if model_name in _model_token_limits_cache: return _model_token_limits_cache[model_name]
    if not api_key or api_key.startswith("YOUR_API_KEY"): return None
    try:
        client = genai.Client(api_key=api_key)
        model_info = client.models.get(model=f"models/{model_name}")
        if model_info and hasattr(model_info, 'input_token_limit') and hasattr(model_info, 'output_token_limit'):
            limits = {"input": model_info.input_token_limit, "output": model_info.output_token_limit}
            _model_token_limits_cache[model_name] = limits
            return limits
    except Exception as e: print(f"モデル情報取得エラー: {e}")
    return None

def _build_lc_messages_from_ui(
    character_name: str, parts: list, api_history_limit_option: str, 
    send_notepad_to_api: bool, use_common_prompt: bool
) -> List[Union[SystemMessage, HumanMessage, AIMessage]]:
    # この関数は、LangGraphエージェントが内部で直接呼び出すためのものです。
    # ストリーミング非対応の元の invoke_nexus_agent からロジックを移植・維持します。
    from agent.prompts import ACTOR_PROMPT_TEMPLATE
    messages: List[Union[SystemMessage, HumanMessage, AIMessage]] = []
    
    char_prompt_path = os.path.join("characters", character_name, "SystemPrompt.txt")
    core_memory_path = os.path.join("characters", character_name, "core_memory.txt")
    
    character_prompt = ""
    if os.path.exists(char_prompt_path):
        with open(char_prompt_path, 'r', encoding='utf-8') as f: character_prompt = f.read().strip()
    
    core_memory = ""
    if os.path.exists(core_memory_path):
        with open(core_memory_path, 'r', encoding='utf-8') as f: core_memory = f.read().strip()

    final_system_prompt = ACTOR_PROMPT_TEMPLATE.format(
        character_name=character_name,
        character_prompt=character_prompt,
        core_memory=core_memory
    ) if use_common_prompt else character_prompt
    
    if send_notepad_to_api:
        _, _, _, _, notepad_path = get_character_files_paths(character_name)
        if notepad_path and os.path.exists(notepad_path):
            with open(notepad_path, 'r', encoding='utf-8') as f:
                notepad_content = f.read().strip()
                if notepad_content: final_system_prompt += f"\n\n---\n【現在のメモ帳の内容】\n{notepad_content}\n---"
    
    messages.append(SystemMessage(content=final_system_prompt))
    
    log_file, _, _, _, _ = get_character_files_paths(character_name)
    raw_history = utils.load_chat_log(log_file, character_name)
    limit = 0
    if api_history_limit_option.isdigit(): limit = int(api_history_limit_option)
    if limit > 0 and len(raw_history) > limit * 2: raw_history = raw_history[-(limit * 2):]
    
    for h_item in raw_history:
        role, content = h_item.get('role'), h_item.get('content', '').strip()
        if not content: continue
        if role == 'model' or role == 'assistant' or role == character_name: messages.append(AIMessage(content=content))
        elif role == 'user' or role == 'human': messages.append(HumanMessage(content=content))
        
    user_message_content_parts = []
    text_buffer = []
    for part_item in parts:
        if isinstance(part_item, str): text_buffer.append(part_item)
        elif isinstance(part_item, Image.Image):
            if text_buffer: user_message_content_parts.append({"type": "text", "text": "\n".join(text_buffer).strip()}); text_buffer = []
            buffered = io.BytesIO()
            save_image = part_item.convert('RGB') if part_item.mode in ('RGBA', 'P') and (part_item.format or 'PNG').upper() == 'JPEG' else part_item
            save_image.save(buffered, format=(part_item.format or 'PNG'))
            img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
            mime_type = f"image/{(part_item.format or 'PNG').lower()}"
            user_message_content_parts.append({"type": "image_url", "image_url": f"data:{mime_type};base64,{img_base64}"})
    if text_buffer: user_message_content_parts.append({"type": "text", "text": "\n".join(text_buffer).strip()})
    
    if user_message_content_parts:
        content = user_message_content_parts[0]["text"] if len(user_message_content_parts) == 1 and user_message_content_parts[0]["type"] == "text" else user_message_content_parts
        messages.append(HumanMessage(content=content))
        
    return messages

def stream_nexus_agent(
    textbox_content: str, chatbot_history: list, current_character_name: str, 
    current_model_name: str, current_api_key_name_state: str, file_input_list: list, 
    add_timestamp_checkbox: bool, send_thoughts_state: bool, api_history_limit_state: str,
    send_notepad_state: bool, use_common_prompt_state: bool
) -> Generator[str, None, None]:
    
    api_key = config_manager.API_KEYS.get(current_api_key_name_state)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        yield f"[エラー: APIキー '{current_api_key_name_state}' が有効ではありません。]"
        return

    # partsの再構築
    parts_for_api = []
    if textbox_content: parts_for_api.append(textbox_content)
    if file_input_list:
        for file_wrapper in file_input_list:
            if not file_wrapper: continue
            try: parts_for_api.append(Image.open(file_wrapper.name))
            except Exception:
                try:
                    with open(file_wrapper.name, 'r', encoding='utf-8') as f: parts_for_api.append(f.read())
                except Exception as e2: print(f"ファイル処理エラー: {e2}")

    messages = _build_lc_messages_from_ui(
        character_name=current_character_name,
        parts=parts_for_api,
        api_history_limit_option=api_history_limit_state,
        send_notepad_to_api=send_notepad_state,
        use_common_prompt=use_common_prompt_state
    )

    try:
        llm = ChatGoogleGenerativeAI(model=current_model_name, google_api_key=api_key, convert_system_message_to_human=True)
        for chunk in llm.stream(messages):
            yield chunk.content
    except Exception as e:
        traceback.print_exc()
        yield f"[APIストリーミングエラー: {e}]"

# (count_tokens_from_lc_messages と count_input_tokens は最初のXMLファイルから復元)
def count_tokens_from_lc_messages(messages: List, model_name: str, api_key: str) -> int:
    if not messages: return 0
    try:
        from agent.graph import _convert_lc_messages_to_gg_contents # 内部関数を借用
        contents_for_api, system_instruction_for_api = _convert_lc_messages_to_gg_contents(messages)
        final_contents_for_api = []
        if system_instruction_for_api:
            final_contents_for_api.append({"role": "user", "parts": system_instruction_for_api["parts"]})
            final_contents_for_api.append({"role": "model", "parts": [{"text": "承知いたしました。"}]})
        final_contents_for_api.extend(contents_for_api)
        if not final_contents_for_api: return 0
        client = genai.Client(api_key=api_key)
        return client.models.count_tokens(model=f"models/{model_name}", contents=final_contents_for_api).total_tokens
    except Exception as e:
        print(f"トークン計算エラー: {e}")
        return -1

def count_input_tokens(
    character_name: str, model_name: str, parts: list, 
    api_history_limit_option: str, api_key_name: str, 
    send_notepad_to_api: bool, use_common_prompt: bool
) -> int:
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"): return -1
    try:
        lc_messages = _build_lc_messages_from_ui(character_name, parts, api_history_limit_option, send_notepad_to_api, use_common_prompt)
        return count_tokens_from_lc_messages(lc_messages, model_name, api_key)
    except Exception as e:
        print(f"トークン計算エラー: {e}"); traceback.print_exc()
        return -2

# invoke_nexus_agentはストリーミングに移行したため、このファイルからは不要になるが、
# 依存関係の破壊を防ぐため、互換性維持のためのダミーとして残すか、
# stream_nexus_agentに完全に移行する。今回は後者を選択し、この関数は削除。
# ただし、他のモジュールからの呼び出しが残っているとエラーになるため、
# 呼び出し元（ui_handlers.py）を修正済み。
