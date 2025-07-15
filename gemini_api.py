# gemini_api.py (vFinal-3: The Restoration)

import google.genai as genai
import os
import io
import json
import traceback
from typing import List, Union, Optional, Dict, Generator, Any
from PIL import Image
import base64
import re

import config_manager
import utils
from character_manager import get_character_files_paths
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

#
# このファイルは、google-genai SDKに準拠したストリーミングと、
# 欠落していたトークン計算機能を完全に復元した、真の最終版です。
#

# ★★★ 欠落していた get_model_token_limits 関数を完全に復元 ★★★
def get_model_token_limits(model_name: str, api_key: str) -> Optional[Dict[str, int]]:
    """モデルの入力・出力トークン上限を取得する（キャッシュ機能付き）"""
    # この関数は、最初にユーザーから提供されたXMLファイルに存在したものを、
    # 完全に復元したものです。
    if model_name in utils._model_token_limits_cache: # キャッシュ先をutilsに変更
        return utils._model_token_limits_cache[model_name]
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return None
    try:
        print(f"--- モデル情報取得 API呼び出し (Model: {model_name}) ---")
        client = genai.Client(api_key=api_key)
        model_info = client.models.get(model=f"models/{model_name}")
        if model_info and hasattr(model_info, 'input_token_limit') and hasattr(model_info, 'output_token_limit'):
            limits = {
                "input": model_info.input_token_limit,
                "output": model_info.output_token_limit
            }
            utils._model_token_limits_cache[model_name] = limits
            print(f"  - モデル '{model_name}' の情報を取得。上限: {limits}")
            return limits
        print(f"  - 警告: モデル情報から上限トークン数を取得できませんでした (Model: {model_name})。")
        return None
    except Exception as e:
        print(f"モデル情報の取得中にエラーが発生しました (Model: {model_name}): {e}")
        return None

def _convert_lc_messages_to_gg_contents(messages: List[Union[SystemMessage, HumanMessage, AIMessage]]) -> (List[Dict], Optional[Dict]):
    """LangChainメッセージをGoogle AI SDK形式に変換するヘルパー関数"""
    contents = []
    system_instruction = None
    if messages and isinstance(messages[0], SystemMessage):
        system_instruction = {"parts": [{"text": messages[0].content}]}
        messages = messages[1:]
    for msg in messages:
        role = "model" if isinstance(msg, AIMessage) else "user"
        sdk_parts = []
        if isinstance(msg.content, str):
            sdk_parts.append({"text": msg.content})
        elif isinstance(msg.content, list):
            for part_data in msg.content:
                if part_data["type"] == "text":
                    sdk_parts.append({"text": part_data["text"]})
                elif part_data["type"] == "image_url":
                    data_uri = part_data["image_url"]
                    match = re.match(r"data:(image/\w+);base64,(.*)", data_uri)
                    if match:
                        mime_type, base64_data = match.groups()
                        try:
                            img_byte = base64.b64decode(base64_data)
                            sdk_parts.append({'inline_data': {'mime_type': mime_type, 'data': img_byte}})
                        except base64.binascii.Error as e:
                            print(f"警告: Base64デコードエラー。スキップ。URI: {data_uri[:50]}..., Error: {e}")
                    else:
                        print(f"警告: 不正なData URI形式。スキップ。URI: {data_uri[:50]}...")
        if sdk_parts:
            contents.append({"role": role, "parts": sdk_parts})
    return contents, system_instruction

def _build_and_prepare_messages_for_api(*args: Any) -> (List[Dict], Optional[Dict]):
    """UIハンドラからの引数を基にAPI用のメッセージを構築する"""
    (textbox_content, chatbot_history, current_character_name, 
     current_model_name, current_api_key_name_state, file_input_list, 
     add_timestamp_checkbox, send_thoughts_state, api_history_limit_state,
     send_notepad_state, use_common_prompt_state) = args
    from agent.prompts import ACTOR_PROMPT_TEMPLATE
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

    messages: List[Union[SystemMessage, HumanMessage, AIMessage]] = []
    char_prompt_path = os.path.join("characters", current_character_name, "SystemPrompt.txt")
    core_memory_path = os.path.join("characters", current_character_name, "core_memory.txt")
    character_prompt = ""
    if os.path.exists(char_prompt_path):
        with open(char_prompt_path, 'r', encoding='utf-8') as f: character_prompt = f.read().strip()
    core_memory = ""
    if os.path.exists(core_memory_path):
        with open(core_memory_path, 'r', encoding='utf-8') as f: core_memory = f.read().strip()
    final_system_prompt = ACTOR_PROMPT_TEMPLATE.format(character_name=current_character_name, character_prompt=character_prompt, core_memory=core_memory) if use_common_prompt_state else character_prompt
    if send_notepad_state:
        _, _, _, _, notepad_path = get_character_files_paths(current_character_name)
        if notepad_path and os.path.exists(notepad_path):
            with open(notepad_path, 'r', encoding='utf-8') as f:
                notepad_content = f.read().strip()
                if notepad_content: final_system_prompt += f"\n\n---\n【現在のメモ帳の内容】\n{notepad_content}\n---"
    messages.append(SystemMessage(content=final_system_prompt))
    log_file, _, _, _, _ = get_character_files_paths(current_character_name)
    raw_history = utils.load_chat_log(log_file, current_character_name)
    limit = int(api_history_limit_state) if api_history_limit_state.isdigit() else 0
    if limit > 0 and len(raw_history) > limit * 2: raw_history = raw_history[-(limit * 2):]
    for h_item in raw_history:
        role, content = h_item.get('role'), h_item.get('content', '').strip()
        if not content: continue
        if role in ['model', 'assistant', current_character_name]: messages.append(AIMessage(content=content))
        elif role in ['user', 'human']: messages.append(HumanMessage(content=content))
        
    user_message_content_parts = []
    text_buffer = []
    for part_item in parts_for_api:
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
        
    return _convert_lc_messages_to_gg_contents(messages)

def stream_nexus_agent(*args: Any) -> Generator[str, None, None]:
    api_key = config_manager.API_KEYS.get(args[4])
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        yield f"[エラー: APIキー '{args[4]}' が有効ではありません。]"
        return

    contents, system_instruction = _build_and_prepare_messages_for_api(*args)
    model_name = args[3]

    try:
        client = genai.Client(api_key=api_key)

        # system_instruction は辞書形式かNoneのため、テキスト部分を安全に抽出
        system_instruction_text = system_instruction['parts'][0]['text'] if system_instruction else None

        # google.genai.types を使って設定を構成
        from google.genai import types
        generation_config = types.GenerateContentConfig(
            system_instruction=system_instruction_text,
            safety_settings=config_manager.SAFETY_CONFIG
        )

        # client.models.generate_content を呼び出す
        response = client.models.generate_content(
            model=f"models/{model_name}",
            contents=contents,
            generation_config=generation_config,
            stream=True
        )

        for chunk in response:
            if chunk.text:
                yield chunk.text
    except Exception as e:
        traceback.print_exc()
        yield f"[APIストリーミングエラー: {e}]"

def count_tokens_from_lc_messages(messages: List, model_name: str, api_key: str) -> int:
    if not messages: return 0
    try:
        client = genai.Client(api_key=api_key)
        contents, system_instruction = _convert_lc_messages_to_gg_contents(messages)

        # system_instruction を user/model のやり取りに変換する既存ロジックを維持
        if system_instruction:
            contents.insert(0, {"role": "user", "parts": system_instruction['parts']})
            contents.insert(1, {"role": "model", "parts": [{"text": "OK"}]})

        # client.models.count_tokens を呼び出す
        result = client.models.count_tokens(
            model=f"models/{model_name}",
            contents=contents
        )
        return result.total_tokens
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
    final_system_prompt = ACTOR_PROMPT_TEMPLATE.format(character_name=character_name, character_prompt=character_prompt, core_memory=core_memory) if use_common_prompt else character_prompt
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

    return count_tokens_from_lc_messages(messages, model_name, api_key)
