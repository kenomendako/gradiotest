# gemini_api.py (v4: Token Counting Guideline Compliance Fix)

import google.genai as genai
import os
import io
import json
import traceback
from typing import List, Union
from PIL import Image
import base64
import re

import config_manager
import utils
from character_manager import get_character_files_paths
from agent.graph import app
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

# _build_lc_messages_from_ui, _convert_lc_messages_to_gg_contents は変更なし
def _build_lc_messages_from_ui(character_name: str, parts: list, api_history_limit_option: str) -> List[Union[SystemMessage, HumanMessage, AIMessage]]:
    messages: List[Union[SystemMessage, HumanMessage, AIMessage]] = []

    _, sys_prompt_file, _, _ = get_character_files_paths(character_name)
    system_prompt_content = ""
    if sys_prompt_file and os.path.exists(sys_prompt_file):
        with open(sys_prompt_file, 'r', encoding='utf-8') as f:
            system_prompt_content = f.read().strip()
    if system_prompt_content:
        messages.append(SystemMessage(content=system_prompt_content))

    log_file, _, _, _ = get_character_files_paths(character_name)
    raw_history = utils.load_chat_log(log_file, character_name)

    history_for_limit_check = []
    for h_item in raw_history:
        role = h_item.get('role')
        content = h_item.get('content', '').strip()
        if not content: continue
        if role == 'model' or role == 'assistant' or role == character_name:
            history_for_limit_check.append(AIMessage(content=content))
        elif role == 'user' or role == 'human':
            history_for_limit_check.append(HumanMessage(content=content))

    limit = 0
    if api_history_limit_option.isdigit():
        limit = int(api_history_limit_option)
    if limit > 0 and len(history_for_limit_check) > limit * 2:
        history_for_limit_check = history_for_limit_check[-(limit * 2):]
    messages.extend(history_for_limit_check)

    user_message_content_parts = []
    text_buffer = []
    for part_item in parts:
        if isinstance(part_item, str):
            text_buffer.append(part_item)
        elif isinstance(part_item, Image.Image):
            if text_buffer:
                user_message_content_parts.append({"type": "text", "text": "\n".join(text_buffer).strip()})
                text_buffer = []
            buffered = io.BytesIO()
            image_format = part_item.format or 'PNG'
            save_image = part_item.convert('RGB') if part_item.mode in ('RGBA', 'P') and image_format.upper() == 'JPEG' else part_item
            save_image.save(buffered, format=image_format)
            img_byte = buffered.getvalue()
            img_base64 = base64.b64encode(img_byte).decode('utf-8')
            mime_type = f"image/{image_format.lower()}"
            user_message_content_parts.append({"type": "image_url", "image_url": f"data:{mime_type};base64,{img_base64}"})

    if text_buffer:
        user_message_content_parts.append({"type": "text", "text": "\n".join(text_buffer).strip()})

    if user_message_content_parts:
        content = user_message_content_parts[0]["text"] if len(user_message_content_parts) == 1 and user_message_content_parts[0]["type"] == "text" else user_message_content_parts
        messages.append(HumanMessage(content=content))

    return messages

def _convert_lc_messages_to_gg_contents(messages: List) -> (list, dict):
    contents = []
    system_instruction = None
    for msg in messages:
        if isinstance(msg, SystemMessage):
            if system_instruction is None:
                system_instruction = {"parts": [{"text": msg.content}]}
            continue
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
                            print(f"警告: Base64デコードエラー。スキップします。URI: {data_uri[:50]}..., Error: {e}")
                    else:
                        print(f"警告: 不正なData URI形式です。スキップします。URI: {data_uri[:50]}...")
        if sdk_parts:
            contents.append({"role": role, "parts": sdk_parts})
    return contents, system_instruction

def count_input_tokens(character_name: str, model_name: str, parts: list, api_history_limit_option: str, api_key_name: str) -> int:
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return -1

    try:
        lc_messages = _build_lc_messages_from_ui(character_name, parts, api_history_limit_option)
        if not lc_messages: return 0

        contents_for_api, system_instruction_for_api = _convert_lc_messages_to_gg_contents(lc_messages)

        # ▼▼▼ 修正箇所 ▼▼▼
        # system_instruction を count_tokens が受け入れられる形式に変換する
        final_contents_for_api = []
        if system_instruction_for_api:
            # システムプロンプトをユーザーからの最初の指示として扱う
            final_contents_for_api.append({
                "role": "user",
                "parts": system_instruction_for_api["parts"]
            })
            # それに対するAIの応答をシミュレート
            final_contents_for_api.append({
                "role": "model",
                "parts": [{"text": "承知いたしました。"}]
            })

        # 残りの会話履歴を結合
        final_contents_for_api.extend(contents_for_api)

        # すべてが空の場合は0を返す
        if not final_contents_for_api: return 0

        client = genai.Client(api_key=api_key)
        model_to_use = f"models/{model_name}"

        # 修正された引数でAPIを呼び出す
        response = client.models.count_tokens(
            model=model_to_use,
            contents=final_contents_for_api # system_instruction の代わりに結合したリストを渡す
        )
        # ▲▲▲ 修正ここまで ▲▲▲

        return response.total_tokens
    except Exception as e:
        print(f"トークン計算エラー (model: {model_name}, char: {character_name}): {e}")
        traceback.print_exc()
        return -2

def invoke_nexus_agent(character_name: str, model_name: str, parts: list, api_history_limit_option: str, api_key_name: str):
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return f"エラー: APIキー名 '{api_key_name}' に有効なキーが設定されていません。", None
    try:
        messages = _build_lc_messages_from_ui(character_name, parts, api_history_limit_option)
        initial_state = {
            "messages": messages,
            "character_name": character_name,
            "api_key": api_key,
            "final_model_name": model_name,
        }
        print(f"--- LangGraphエージェント呼び出し (Character: {character_name}, Final Model by User: {model_name}) ---")
        final_state = app.invoke(initial_state)
        print("--- LangGraphエージェント実行完了 ---")
        response_text = "[エージェントからの応答がありませんでした]"
        if final_state and final_state.get('messages') and isinstance(final_state['messages'][-1], AIMessage):
            response_text = final_state['messages'][-1].content
        elif final_state and final_state.get('messages') and final_state['messages'][-1]:
             response_text = str(final_state['messages'][-1].content if hasattr(final_state['messages'][-1], 'content') else final_state['messages'][-1])
        return response_text, None
    except Exception as e:
        traceback.print_exc()
        return f"エラー: エージェントの実行中にエラーが発生しました: {e}", None

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
                user_message_parts_for_payload.append({'inline_data': {'mime_type': 'image/jpeg', 'data': img_byte_arr.getvalue()}})
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

        user_input_text = "".join([p for p in parts if isinstance(p, str)])
        attached_file_names = [os.path.basename(p.name) for p in parts if not isinstance(p, str) and hasattr(p, 'name')]
        if attached_file_names:
            user_input_text += "\n[ファイル添付: " + ", ".join(attached_file_names) + "]"

        if user_input_text.strip():
            user_header = utils._get_user_header_from_log(log_file, character_name)
            utils.save_message_to_log(log_file, user_header, user_input_text.strip())
            utils.save_message_to_log(log_file, f"## {character_name}:", generated_text)
        return generated_text, None
    except Exception as e:
        traceback.print_exc()
        error_message = f"エラー: モデル '{model_name}' との通信中に予期しないエラーが発生しました: {e}"
        if 'response' in locals() and hasattr(response, 'prompt_feedback') and response.prompt_feedback:
            error_message += f"\nプロンプトフィードバック: {response.prompt_feedback}"
        return error_message, None
