# gemini_api.py

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
    """モデルのトークン数上限を取得し、キャッシュする"""
    if model_name in _model_token_limits_cache:
        return _model_token_limits_cache[model_name]

    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return None

    try:
        print(f"--- モデル情報取得 API呼び出し (Model: {model_name}) ---")
        # AI_DEVELOPMENT_GUIDELINES.md に従い、genai.Clientインスタンスを明示的に渡す
        # genai.get_model は client 引数を取らない場合があるため、
        # genai.GenerativeModel(model_name, client=...).get_model_info() のような代替手段も検討できるが、
        # まずはドキュメントで推奨される genai.get_model を試す。
        # clientの渡し方はSDKバージョンによる。もしエラーなら client=genai.Client(api_key=api_key) を試す。
        # 最新のgoogle-generativeaiでは、model_infoは以下のように取得する
        model_service_client = genai.services.ModelServiceClient(client_options={"api_key": api_key})
        model_info_response = model_service_client.get_model(name=f"models/{model_name}")

        if model_info_response and hasattr(model_info_response, 'input_token_limit') and hasattr(model_info_response, 'output_token_limit'):
            limits = {
                "input": model_info_response.input_token_limit,
                "output": model_info_response.output_token_limit
            }
            _model_token_limits_cache[model_name] = limits
            return limits
        return None
    except Exception as e:
        print(f"モデル情報の取得に失敗しました (Model: {model_name}): {e}")
        # AI Studioのコードではここで client=genai.Client(api_key=api_key) を使っていたので、それに準拠する
        try:
            # AI Studioのコードにより近い形での再試行
            client = genai.Client(api_key=api_key)
            model_info_direct = client.get_model(f"models/{model_name}")
            if model_info_direct and hasattr(model_info_direct, 'input_token_limit') and hasattr(model_info_direct, 'output_token_limit'):
                limits = {
                    "input": model_info_direct.input_token_limit,
                    "output": model_info_direct.output_token_limit
                }
                _model_token_limits_cache[model_name] = limits
                return limits
            return None
        except Exception as e2:
            print(f"モデル情報の取得に再試行も失敗しました (Model: {model_name}): {e2}")
            return None


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
        return -1 # UIでエラーと区別するため-2ではなく-1を返す（count_input_tokensと合わせる）

def count_input_tokens(character_name: str, model_name: str, parts: list, api_history_limit_option: str, api_key_name: str) -> int:
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return -1 # APIキー無効
    try:
        lc_messages = _build_lc_messages_from_ui(character_name, parts, api_history_limit_option)
        # count_tokens_from_lc_messages の返り値が -1 の場合は計算エラーなので、-2 として返す
        calculated_tokens = count_tokens_from_lc_messages(lc_messages, model_name, api_key)
        if calculated_tokens == -1: # count_tokens_from_lc_messages 内部でのエラー
             return -2 # 計算エラー
        return calculated_tokens
    except Exception as e:
        print(f"トークン計算エラー (model: {model_name}, char: {character_name}): {e}")
        traceback.print_exc()
        return -2 # 計算エラー

def invoke_nexus_agent(character_name: str, model_name: str, parts: list, api_history_limit_option: str, api_key_name: str):
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        # エージェント呼び出しの戻り値の型を AgentState に合わせるか、エラー情報を明確にする
        # ここではAI Studioの提案通り辞書でエラーを返す
        return {"error": f"APIキー '{api_key_name}' が有効ではありません。"}
    try:
        messages = _build_lc_messages_from_ui(character_name, parts, api_history_limit_option)
        initial_state = {
            "messages": messages,
            "character_name": character_name,
            "api_key": api_key,
            "final_model_name": model_name,
            "final_token_count": 0 # AgentState に合わせて初期化
        }
        print(f"--- LangGraphエージェント呼び出し (Character: {character_name}, Final Model by User: {model_name}) ---")
        final_state = app.invoke(initial_state) # final_state は AgentState 型を期待
        print("--- LangGraphエージェント実行完了 ---")
        # final_state は AgentState なので、そのまま返す
        return final_state
    except Exception as e:
        traceback.print_exc()
        # エラー時も AgentState の型に近い形で返すか、エラー専用の情報を返す
        return {"error": f"エージェントの実行中にエラーが発生しました: {e}"}


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
```
