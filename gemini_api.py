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

def get_model_token_limits(model_name: str, api_key: str) -> Optional[Dict[str, int]]:
    if model_name in utils._model_token_limits_cache:
        return utils._model_token_limits_cache[model_name]
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return None
    try:
        client = genai.Client(api_key=api_key)
        model_info = client.models.get(model=f"models/{model_name}")
        if model_info and hasattr(model_info, 'input_token_limit') and hasattr(model_info, 'output_token_limit'):
            limits = {"input": model_info.input_token_limit, "output": model_info.output_token_limit}
            utils._model_token_limits_cache[model_name] = limits
            return limits
        return None
    except Exception as e:
        print(f"モデル情報の取得中にエラー: {e}")
        return None

def _convert_lc_to_gg_for_count(messages: List[Union[SystemMessage, HumanMessage, AIMessage]]) -> List[Dict]:
    contents = []
    for msg in messages:
        role = "model" if isinstance(msg, AIMessage) else "user"
        sdk_parts = []
        if isinstance(msg.content, str):
            sdk_parts.append({"text": msg.content})
        elif isinstance(msg.content, list):
            for part_data in msg.content:
                if not isinstance(part_data, dict): continue
                part_type = part_data.get("type")
                if part_type == "text":
                    sdk_parts.append({"text": part_data.get("text", "")})
                elif part_type == "image_url":
                    url_data = part_data.get("image_url", {}).get("url", "")
                    if url_data.startswith("data:"):
                        try:
                            header, encoded = url_data.split(",", 1)
                            mime_type = header.split(":")[1].split(";")[0]
                            sdk_parts.append({"inline_data": {"mime_type": mime_type, "data": encoded}})
                        except: pass
                elif part_type == "media":
                     sdk_parts.append({"inline_data": {"mime_type": part_data.get("mime_type", "application/octet-stream"),"data": part_data.get("data", "")}})
        if sdk_parts: contents.append({"role": role, "parts": sdk_parts})
    return contents

def count_tokens_from_lc_messages(messages: List, model_name: str, api_key: str) -> int:
    if not messages: return 0
    try:
        # ★★★ ここからがAttributeErrorの修正箇所 ★★★
        # genai.configure() を使うのではなく、プロジェクトの規律通り
        # genai.Client() を使ってAPIを呼び出す
        client = genai.Client(api_key=api_key)

        contents_for_api = _convert_lc_to_gg_for_count(messages)

        # LangChainのSystemMessageをgoogle-genaiが扱える形式に変換するロジック
        final_contents_for_api = []
        if contents_for_api and contents_for_api[0]['role'] == 'user' and isinstance(messages[0], SystemMessage):
            system_instruction_parts = contents_for_api[0]['parts']
            final_contents_for_api.append({"role": "user", "parts": system_instruction_parts})
            final_contents_for_api.append({"role": "model", "parts": [{"text": "OK"}]})
            final_contents_for_api.extend(contents_for_api[1:])
        else:
            final_contents_for_api = contents_for_api

        result = client.models.count_tokens(
            model=f"models/{model_name}",
            contents=final_contents_for_api
        )
        return result.total_tokens
        # ★★★ 修正箇所ここまで ★★★
    except Exception as e:
        print(f"トークン計算エラー: {e}")
        traceback.print_exc()
        return -1

# ★★★★★ ここからが最重要修正箇所 ★★★★★
def invoke_nexus_agent(*args: Any) -> Dict[str, str]:
    (textbox_content, chatbot_history, current_character_name,
     current_api_key_name_state, file_input_list, add_timestamp_checkbox,
     api_history_limit_state) = args

    # ★★★ ここからが新しい設定読み込み処理 ★★★
    effective_settings = config_manager.get_effective_settings(current_character_name)

    current_model_name = effective_settings["model_name"]
    send_thoughts_state = effective_settings["send_thoughts"]
    send_notepad_state = effective_settings["send_notepad"]
    use_common_prompt_state = effective_settings["use_common_prompt"]
    send_core_memory_state = effective_settings["send_core_memory"]
    send_scenery_state = effective_settings["send_scenery"]

    api_key = config_manager.API_KEYS.get(current_api_key_name_state)
    # ★★★ ここまで ★★★
    is_internal_call = textbox_content and textbox_content.startswith("（システム：")
    default_error_response = {"response": "", "location_name": "（エラー）", "scenery": "（エラー）"}

    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return {**default_error_response, "response": f"[エラー: APIキー '{current_api_key_name_state}' が有効ではありません。]"}

    user_input_text = textbox_content.strip() if textbox_content else ""
    if not user_input_text and not file_input_list and not is_internal_call:
         return {**default_error_response, "response": "[エラー: テキスト入力またはファイル添付がありません]"}

    messages = []
    log_file, _, _, _, _ = get_character_files_paths(current_character_name)
    raw_history = utils.load_chat_log(log_file, current_character_name)
    limit = int(api_history_limit_state) if api_history_limit_state.isdigit() else 0
    if limit > 0 and len(raw_history) > limit * 2: raw_history = raw_history[-(limit * 2):]
    for h_item in raw_history:
        role, content = h_item.get('role'), h_item.get('content', '').strip()
        if not content: continue
        if role in ['model', 'assistant', current_character_name]:
            final_content = content if send_thoughts_state else utils.remove_thoughts_from_text(content)
            if final_content: messages.append(AIMessage(content=final_content))
        elif role in ['user', 'human']: messages.append(HumanMessage(content=content))

    user_message_parts = []
    if user_input_text: user_message_parts.append({"type": "text", "text": user_input_text})
    if file_input_list:
        for file_obj in file_input_list:
            filepath = file_obj.name
            try:
                kind = filetype.guess(filepath); mime_type = kind.mime if kind else None
                if mime_type and (mime_type.startswith("image/") or mime_type.startswith("audio/") or mime_type.startswith("video/")):
                    with open(filepath, "rb") as f: file_data = base64.b64encode(f.read()).decode("utf-8")
                    if mime_type.startswith("image/"):
                         user_message_parts.append({"type": "image_url", "image_url": { "url": f"data:{mime_type};base64,{file_data}"}})
                    else:
                         user_message_parts.append({"type": "media", "mime_type": mime_type, "data": file_data})
                else:
                    with open(filepath, 'r', encoding='utf-8') as f: text_content = f.read()
                    user_message_parts.append({"type": "text", "text": f"--- 添付ファイル「{os.path.basename(filepath)}」の内容 ---\n{text_content}\n--- ファイル内容ここまで ---"})
            except Exception as e: print(f"警告: ファイル '{os.path.basename(filepath)}' の処理に失敗。スキップ。エラー: {e}")
    if user_message_parts: messages.append(HumanMessage(content=user_message_parts))

    initial_state = {
        "messages": messages, "character_name": current_character_name, "api_key": api_key,
        "tavily_api_key": config_manager.TAVILY_API_KEY, "model_name": current_model_name,
        "send_core_memory": send_core_memory_state,
        "send_scenery": send_scenery_state,
        "send_notepad": send_notepad_state, # ★★★ この行を追加 ★★★
        "location_name": "（初期化中）", "scenery_text": "（初期化中）"
    }
    try:
        final_state = app.invoke(initial_state)
        final_response_text = ""
        if not is_internal_call and final_state['messages'] and isinstance(final_state['messages'][-1], AIMessage):
            final_response_text = final_state['messages'][-1].content
        location_name = final_state.get('location_name', '（場所不明）')
        scenery_text = final_state.get('scenery_text', '（情景不明）')
        return {"response": final_response_text, "location_name": location_name, "scenery": scenery_text}
    except Exception as e:
        traceback.print_exc(); return {**default_error_response, "response": f"[エージェント実行エラー: {e}]"}

# ★★★★★ 修正箇所ここまで ★★★★★

def count_input_tokens(*args):
    (character_name, model_name, parts, api_history_limit_option, api_key_name, send_notepad_to_api, use_common_prompt, add_timestamp, send_thoughts, send_core_memory, send_scenery) = args
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"): return -1
    from agent.graph import all_tools
    from agent.prompts import CORE_PROMPT_TEMPLATE
    from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
    import datetime
    messages: List[Union[SystemMessage, HumanMessage, AIMessage]] = []
    char_prompt_path = os.path.join("characters", character_name, "SystemPrompt.txt")
    character_prompt = "";
    if os.path.exists(char_prompt_path):
        with open(char_prompt_path, 'r', encoding='utf-8') as f: character_prompt = f.read().strip()
    core_memory = ""
    if send_core_memory:
        core_memory_path = os.path.join("characters", character_name, "core_memory.txt")
        if os.path.exists(core_memory_path):
            with open(core_memory_path, 'r', encoding='utf-8') as f: core_memory = f.read().strip()
    tools_list_str = "\n".join([f"- `{tool.name}({', '.join(tool.args.keys())})`: {tool.description}" for tool in all_tools])
    class SafeDict(dict):
        def __missing__(self, key): return f'{{{key}}}'
    prompt_vars = {'character_name': character_name, 'character_prompt': character_prompt, 'core_memory': core_memory, 'tools_list': tools_list_str, 'space_definition': '（トークン計算では空間定義は省略）'}
    final_system_prompt = CORE_PROMPT_TEMPLATE.format_map(SafeDict(prompt_vars)) if use_common_prompt else character_prompt
    if send_notepad_to_api:
        _, _, _, _, notepad_path = get_character_files_paths(character_name)
        if notepad_path and os.path.exists(notepad_path):
            with open(notepad_path, 'r', encoding='utf-8') as f:
                notepad_content = f.read().strip()
                if notepad_content: final_system_prompt += f"\n\n---\n【現在のメモ帳の内容】\n{notepad_content}\n---"
    messages.append(SystemMessage(content=final_system_prompt))
    log_file, _, _, _, _ = get_character_files_paths(character_name)
    raw_history = utils.load_chat_log(log_file, character_name)
    limit = int(api_history_limit_option) if api_history_limit_option.isdigit() else 0
    if limit > 0 and len(raw_history) > limit * 2: raw_history = raw_history[-(limit * 2):]
    for h_item in raw_history:
        role, content = h_item.get('role'), h_item.get('content', '').strip()
        if not content: continue
        if role in ['model', 'assistant', character_name]:
            final_content = content if send_thoughts else utils.remove_thoughts_from_text(content)
            if final_content: messages.append(AIMessage(content=final_content))
        elif role in ['user', 'human']: messages.append(HumanMessage(content=content))
    user_message_content_parts = []
    text_buffer = []
    if parts:
        for part_item in parts:
            if isinstance(part_item, str): text_buffer.append(part_item)
            elif isinstance(part_item, Image.Image):
                if text_buffer: user_message_content_parts.append({"type": "text", "text": "\n".join(text_buffer).strip()}); text_buffer = []
                buffered = io.BytesIO(); save_image = part_item.convert('RGB') if part_item.mode in ('RGBA', 'P') else part_item
                image_format = part_item.format or 'PNG'; save_image.save(buffered, format=image_format)
                img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8'); mime_type = f"image/{image_format.lower()}"
                user_message_content_parts.append({"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{img_base64}"}})
            elif isinstance(part_item, dict) and part_item.get("type") == "media":
                 if text_buffer: user_message_content_parts.append({"type": "text", "text": "\n".join(text_buffer).strip()}); text_buffer = []
                 user_message_content_parts.append(part_item)
    if text_buffer:
        final_text = "\n".join(text_buffer).strip()
        if add_timestamp and final_text: final_text += f"\n\n{datetime.datetime.now().strftime('%Y-%m-%d (%a) %H:%M:%S')}"
        user_message_content_parts.append({"type": "text", "text": final_text})
    if user_message_content_parts: messages.append(HumanMessage(content=user_message_content_parts))
    return count_tokens_from_lc_messages(messages, model_name, api_key)
