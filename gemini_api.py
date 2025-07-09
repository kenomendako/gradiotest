# gemini_api.py (v7: Correctly using client.models.get)

import google.genai as genai
import os
import io
import json
import traceback
from typing import List, Union, Optional, Dict
from PIL import Image
import base64
import re

import config_manager
import utils
from character_manager import get_character_files_paths
from agent.graph import app
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

_model_token_limits_cache: Dict[str, Dict[str, int]] = {}

def get_model_token_limits(model_name: str, api_key: str) -> Optional[Dict[str, int]]:
    """【最終修正】公式サンプルコードに従い、client.models.get() を使用してトークン上限を正しく取得する"""
    if model_name in _model_token_limits_cache:
        return _model_token_limits_cache[model_name]

    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return None

    try:
        # ▼▼▼ 修正箇所 ▼▼▼
        # client.models.list() の代わりに、公式推奨の client.models.get() を使用する
        print(f"--- モデル情報取得 API呼び出し (Model: {model_name}) ---")
        client = genai.Client(api_key=api_key)

        # get()メソッドは 'models/' プレフィックスを付けて呼び出すのが最も確実
        target_model_name = f"models/{model_name}"
        model_info = client.models.get(model=target_model_name)

        if model_info and hasattr(model_info, 'input_token_limit') and hasattr(model_info, 'output_token_limit'):
            limits = {
                "input": model_info.input_token_limit,
                "output": model_info.output_token_limit
            }
            _model_token_limits_cache[model_name] = limits
            print(f"  - モデル '{model_name}' の情報を取得。上限: {limits}")
            return limits

        print(f"  - 警告: モデル情報から上限トークン数を取得できませんでした (Model: {model_name})。")
        return None
        # ▲▲▲ 修正ここまで ▲▲▲

    except Exception as e:
        print(f"モデル情報の取得中にエラーが発生しました (Model: {model_name}): {e}")
        # traceback.print_exc() # デバッグ時以外はコメントアウトしても良い
        return None

# (以降の関数は、前回の修正のままで完成していますので、変更ありません)
def _build_lc_messages_from_ui(
    character_name: str,
    parts: list,
    api_history_limit_option: str,
    send_notepad_to_api: bool # ★★★ この引数を追加 ★★★
) -> List[Union[SystemMessage, HumanMessage, AIMessage]]:
    messages: List[Union[SystemMessage, HumanMessage, AIMessage]] = []
    log_file, sys_prompt_file, _, _, notepad_path = get_character_files_paths(character_name) # notepad_path を取得

    # メモ帳の内容を読み込む
    notepad_content = ""
    if notepad_path and os.path.exists(notepad_path): # notepad_path が None でないことも確認
        with open(notepad_path, 'r', encoding='utf-8') as f:
            notepad_content = f.read().strip()

    # システムプロンプトを読み込む
    system_prompt_content = ""
    if sys_prompt_file and os.path.exists(sys_prompt_file): # sys_prompt_file が None でないことも確認
        with open(sys_prompt_file, 'r', encoding='utf-8') as f:
            system_prompt_content = f.read().strip()

    full_system_prompt = system_prompt_content

    # ★★★ ここからが修正箇所 ★★★
    # スイッチがONの場合のみ、メモ帳の内容を結合する
    if send_notepad_to_api and notepad_content: # notepad_content が空でないことも確認
        full_system_prompt += f"\n\n---\n【現在のメモ帳の内容】\n{notepad_content}\n---"
    # ★★★ 修正ここまで ★★★

    if full_system_prompt: # full_system_prompt が空でない場合のみ追加
        messages.append(SystemMessage(content=full_system_prompt))

    # log_file は既に上で取得済み
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

def count_tokens_from_lc_messages(messages: List, model_name: str, api_key: str) -> int:
    if not messages: return 0
    try:
        contents_for_api, system_instruction_for_api = _convert_lc_messages_to_gg_contents(messages)
        final_contents_for_api = []
        if system_instruction_for_api:
            final_contents_for_api.append({"role": "user", "parts": system_instruction_for_api["parts"]})
            final_contents_for_api.append({"role": "model", "parts": [{"text": "承知いたしました。"}]})
        final_contents_for_api.extend(contents_for_api)
        if not final_contents_for_api: return 0
        client = genai.Client(api_key=api_key)
        model_to_use = f"models/{model_name}"
        response = client.models.count_tokens(model=model_to_use, contents=final_contents_for_api)
        return response.total_tokens
    except Exception as e:
        print(f"トークン計算エラー (from messages): {e}")
        return -1

def count_input_tokens(
    character_name: str,
    model_name: str,
    parts: list,
    api_history_limit_option: str,
    api_key_name: str,
    send_notepad_to_api: bool # ★★★ この引数を追加 ★★★
) -> int:
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return -1 # APIキーが無効なら-1（エラーを示す特別な値）
    try:
        # ★★★ 呼び出し時に引数を渡す ★★★
        lc_messages = _build_lc_messages_from_ui(character_name, parts, api_history_limit_option, send_notepad_to_api)
        return count_tokens_from_lc_messages(lc_messages, model_name, api_key)
    except Exception as e:
        print(f"トークン計算エラー (model: {model_name}, char: {character_name}): {e}")
        traceback.print_exc()
        return -2

# ★★★ 引数に send_notepad_to_api を追加 ★★★
def invoke_nexus_agent(
    character_name: str,
    model_name: str,
    parts: list,
    api_history_limit_option: str,
    api_key_name: str,
    send_notepad_to_api: bool # ★★★ この引数を追加 ★★★
):
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return {"error": f"APIキー '{api_key_name}' が有効ではありません。"}
    try:
        # ★★★ 呼び出し時に引数を渡す ★★★
        messages = _build_lc_messages_from_ui(character_name, parts, api_history_limit_option, send_notepad_to_api)
        initial_state = {
            "messages": messages,
            "character_name": character_name,
            "api_key": api_key,
            "final_model_name": model_name,
            "final_token_count": 0
        }
        print(f"--- LangGraphエージェント呼び出し (Character: {character_name}, Final Model by User: {model_name}) ---")
        final_state = app.invoke(initial_state)
        print("--- LangGraphエージェント実行完了 ---")
        return final_state
    except Exception as e:
        traceback.print_exc()
        return {"error": f"エージェントの実行中にエラーが発生しました: {e}"}

def send_multimodal_to_gemini(character_name: str, model_name: str, parts: list, api_history_limit_option: str, api_key_name: str):
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return f"エラー: APIキー名 '{api_key_name}' に有効なキーが設定されていません。", None
    try:
        log_file, sys_prompt_file, _, _, _ = get_character_files_paths(character_name) # 戻り値の数を5に変更
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
            messages_for_api_direct_call.append({"role": h_item["role"], "parts": [{'text': h_item["content"]}]})
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
        response = client_for_direct_call.models.generate_content(model=model_to_call_name, contents=messages_for_api_direct_call)
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
