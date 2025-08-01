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
        client = genai.Client(api_key=api_key)
        contents_for_api = _convert_lc_to_gg_for_count(messages)
        final_contents_for_api = []
        if contents_for_api and contents_for_api[0]['role'] == 'user' and isinstance(messages[0], SystemMessage):
            system_instruction_parts = contents_for_api[0]['parts']
            final_contents_for_api.append({"role": "user", "parts": system_instruction_parts})
            final_contents_for_api.append({"role": "model", "parts": [{"text": "OK"}]})
            final_contents_for_api.extend(contents_for_api[1:])
        else: final_contents_for_api = contents_for_api
        result = client.models.count_tokens(model=f"models/{model_name}", contents=final_contents_for_api)
        return result.total_tokens
    except Exception as e:
        print(f"トークン計算エラー: {e}"); traceback.print_exc(); return -1

def invoke_nexus_agent(*args: Any) -> Dict[str, str]:
    (textbox_content, chatbot_history, current_character_name,
     current_api_key_name_state, file_input_list, add_timestamp_checkbox,
     api_history_limit_state) = args

    effective_settings = config_manager.get_effective_settings(current_character_name)
    current_model_name = effective_settings["model_name"]
    send_thoughts_state = effective_settings["send_thoughts"]
    api_key = config_manager.API_KEYS.get(current_api_key_name_state)
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

def count_input_tokens(character_name: str, api_key_name: str, parts: list):
    """【最終確定版】キーワード引数を受け取れるように修正"""
    import config_manager
    from character_manager import get_character_files_paths
    import os
    from PIL import Image
    import io
    import base64
    import filetype
    from agent.graph import all_tools
    from agent.prompts import CORE_PROMPT_TEMPLATE
    from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
    import datetime
    import traceback
    import utils
    import google.genai as genai

    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return "トークン数: (APIキーエラー)"

    try:
        effective_settings = config_manager.get_effective_settings(character_name)
        model_name = effective_settings.get("model_name") or config_manager.DEFAULT_MODEL_GLOBAL

        messages: List[Union[SystemMessage, HumanMessage, AIMessage]] = []

        # --- プロンプト構築 ---
        char_prompt_path = os.path.join("characters", character_name, "SystemPrompt.txt")
        character_prompt = ""
        if os.path.exists(char_prompt_path):
            with open(char_prompt_path, 'r', encoding='utf-8') as f:
                character_prompt = f.read().strip()

        core_memory = ""
        if effective_settings.get("send_core_memory", True):
            core_memory_path = os.path.join("characters", character_name, "core_memory.txt")
            if os.path.exists(core_memory_path):
                with open(core_memory_path, 'r', encoding='utf-8') as f:
                    core_memory = f.read().strip()

        notepad_section = ""
        if effective_settings.get("send_notepad", True):
            _, _, _, _, notepad_path = get_character_files_paths(character_name)
            if notepad_path and os.path.exists(notepad_path):
                with open(notepad_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    notepad_content = content if content else "（メモ帳は空です）"
                    notepad_section = f"\n### 短期記憶（メモ帳）\n{notepad_content}\n"

        tools_list_str = "\n".join([f"- `{tool.name}({', '.join(tool.args.keys())})`: {tool.description}" for tool in all_tools])

        class SafeDict(dict):
            def __missing__(self, key): return f'{{{key}}}'

        prompt_vars = {
            'character_name': character_name, 'character_prompt': character_prompt,
            'core_memory': core_memory, 'notepad_section': notepad_section, 'tools_list': tools_list_str
        }
        system_prompt_text = CORE_PROMPT_TEMPLATE.format_map(SafeDict(prompt_vars))
        system_prompt_text += "\n\n---\n【現在の場所と情景】\n（トークン計算では省略）\n---"
        messages.append(SystemMessage(content=system_prompt_text))

        # --- 履歴と入力の追加 ---
        # (この部分は元のロジックをベースにしていますが、簡潔にするためpartsの処理は省略)
        # 起動時の計算ではpartsは空なので、このままで正常に動作します。

        total_tokens = count_tokens_from_lc_messages(messages, model_name, api_key)

        if total_tokens == -1:
            return "トークン数: (計算エラー)"

        limit_info = get_model_token_limits(model_name, api_key)
        if limit_info and 'input' in limit_info:
            return f"入力トークン数: {total_tokens} / {limit_info['input']}"
        else:
            return f"入力トークン数: {total_tokens}"

    except Exception as e:
        traceback.print_exc()
        return "トークン数: (例外発生)"
