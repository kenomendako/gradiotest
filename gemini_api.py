# gemini_api.py の内容を、以下のコードで完全に置き換えてください

import traceback
from typing import Any, List, Union, Optional, Dict
import os
import io
import base64
import re
from PIL import Image
import google.genai as genai
import filetype

from agent.graph import app
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
import config_manager
import utils
import mem0_manager
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
                if isinstance(part_data, dict) and part_data.get("type") == "text":
                    sdk_parts.append({"text": part_data["text"]})
        if sdk_parts:
            contents.append({"role": role, "parts": sdk_parts})
    return contents

def count_tokens_from_lc_messages(messages: List, model_name: str, api_key: str) -> int:
    if not messages: return 0
    try:
        client = genai.Client(api_key=api_key)
        contents = _convert_lc_to_gg_for_count(messages)
        final_contents_for_api = []
        if contents and isinstance(messages[0], SystemMessage):
             system_instruction = contents[0]['parts']
             final_contents_for_api.extend([
                 {"role": "user", "parts": system_instruction},
                 {"role": "model", "parts": [{"text": "OK"}]}
             ])
             final_contents_for_api.extend(contents[1:])
        else:
            final_contents_for_api = contents
        result = client.models.count_tokens(model=f"models/{model_name}", contents=final_contents_for_api)
        return result.total_tokens
    except Exception as e:
        print(f"トークン計算エラー: {e}")
        return -1

def count_input_tokens(
    character_name: str, model_name: str, parts: list,
    api_history_limit_option: str, api_key_name: str,
    send_notepad_to_api: bool, use_common_prompt: bool
) -> int:
    from agent.graph import all_tools
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"): return -1

    from agent.prompts import CORE_PROMPT_TEMPLATE
    messages: List[Union[SystemMessage, HumanMessage, AIMessage]] = []

    char_prompt_path = os.path.join("characters", character_name, "SystemPrompt.txt")
    core_memory_path = os.path.join("characters", character_name, "core_memory.txt")
    character_prompt = ""
    if os.path.exists(char_prompt_path):
        with open(char_prompt_path, 'r', encoding='utf-8') as f: character_prompt = f.read().strip()
    core_memory = ""
    if os.path.exists(core_memory_path):
        with open(core_memory_path, 'r', encoding='utf-8') as f: core_memory = f.read().strip()

    if use_common_prompt:
        tools_list_str = "\n".join([f"- `{tool.name}({', '.join(tool.args.keys())})`: {tool.description}" for tool in all_tools])
        class SafeDict(dict):
            def __missing__(self, key): return f'{{{key}}}'
        prompt_vars = {
            'character_name': character_name, 'character_prompt': character_prompt,
            'core_memory': core_memory, 'tools_list': tools_list_str
        }
        final_system_prompt = CORE_PROMPT_TEMPLATE.format_map(SafeDict(prompt_vars))
    else:
        final_system_prompt = character_prompt

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
        if role in ['model', 'assistant', character_name]: messages.append(AIMessage(content=content))
        elif role in ['user', 'human']: messages.append(HumanMessage(content=content))

    user_message_content_parts = []
    text_buffer = []
    for part_item in parts:
        if isinstance(part_item, str): text_buffer.append(part_item)
        elif isinstance(part_item, Image.Image):
            if text_buffer:
                user_message_content_parts.append({"type": "text", "text": "\n".join(text_buffer).strip()})
                text_buffer = []
            buffered = io.BytesIO()
            save_image = part_item.convert('RGB') if part_item.mode in ('RGBA', 'P') else part_item
            image_format = part_item.format or 'PNG'
            save_image.save(buffered, format=image_format)
            img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
            mime_type = f"image/{image_format.lower()}"
            user_message_content_parts.append({"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{img_base64}"}})

    if text_buffer:
        user_message_content_parts.append({"type": "text", "text": "\n".join(text_buffer).strip()})
    if user_message_content_parts:
        content_for_lc = user_message_content_parts[0]["text"] if len(user_message_content_parts) == 1 and user_message_content_parts[0]["type"] == "text" else user_message_content_parts
        messages.append(HumanMessage(content=content_for_lc))

    return count_tokens_from_lc_messages(messages, model_name, api_key)


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
    log_file, _, _, _, _ = get_character_files_paths(current_character_name)
    raw_history = utils.load_chat_log(log_file, current_character_name)
    limit = int(api_history_limit_state) if api_history_limit_state.isdigit() else 0
    if limit > 0 and len(raw_history) > limit * 2:
        raw_history = raw_history[-(limit * 2):]
    for h_item in raw_history:
        role, content = h_item.get('role'), h_item.get('content', '').strip()
        if not content: continue
        if role in ['model', 'assistant', current_character_name]: messages.append(AIMessage(content=content))
        elif role in ['user', 'human']: messages.append(HumanMessage(content=content))

    user_message_parts = []
    if user_input_text:
        user_message_parts.append({"type": "text", "text": user_input_text})

    if file_input_list:
        # LangChainが内部で認証を済ませているので、ここでは何もしない
        for file_obj in file_input_list:
            filepath = file_obj.name
            print(f"  - ファイル添付を処理中: {filepath}")
            try:
                kind = filetype.guess(filepath)
                if kind is None:
                    raise TypeError("Cannot guess file type, attempting to read as text.")

                mime_type = kind.mime
                print(f"    - 検出されたMIMEタイプ: {mime_type}")

                if mime_type.startswith("image/"):
                    img = Image.open(filepath)
                    buffered = io.BytesIO()
                    img_format = img.format or 'PNG'
                    save_image = img.convert('RGB') if img.mode in ('RGBA', 'P') else img
                    save_image.save(buffered, format=img_format)
                    img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
                    user_message_parts.append({
                        "type": "image_url",
                        "image_url": { "url": f"data:{mime_type};base64,{img_base64}"}
                    })
                elif mime_type.startswith("audio/") or mime_type.startswith("video/"):
                    # ★★★ 変更点: 公式ドキュメント通りのトップレベル関数 genai.upload_file を使用 ★★★
                    uploaded_file = genai.upload_file(
                        path=filepath,
                        display_name=os.path.basename(filepath)
                    )
                    user_message_parts.append(uploaded_file)
                else:
                    raise TypeError("Unsupported MIME type, attempting to read as text.")

            except Exception as e:
                print(f"    - 警告: バイナリファイルとして処理中にエラー ({e})。テキストとして読み込みます。")
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        text_content = f.read()
                    user_message_parts.append({
                        "type": "text",
                        "text": f"--- 添付ファイル「{os.path.basename(filepath)}」の内容 ---\n{text_content}\n--- ファイル内容ここまで ---"
                    })
                except Exception as text_e:
                    print(f"    - 警告: ファイル '{os.path.basename(filepath)}' の読み込みに失敗しました。スキップします。エラー: {text_e}")

    if user_message_parts:
        messages.append(HumanMessage(content=user_message_parts))

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
            user_text_for_mem0 = "\n".join([part['text'] for part in user_message_parts if isinstance(part, dict) and part.get('type') == 'text' and part.get('text')])
            if user_text_for_mem0:
                mem0_instance.add([
                    {"role": "user", "content": user_text_for_mem0},
                    {"role": "assistant", "content": final_response_message.content}
                ], user_id=current_character_name)
                print("--- mem0への記憶成功 ---")
        except Exception as e:
            print(f"--- mem0への記憶中にエラー: {e} ---")

        return final_response_message.content
    except Exception as e:
        print(f"--- エージェント実行エラー ---")
        traceback.print_exc()
        return f"[エージェント実行エラー: {e}]"
