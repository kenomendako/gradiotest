# gemini_api.py (v3: Project Guideline Compliance Fix)

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

# _build_lc_messages_from_ui と _convert_lc_messages_to_gg_contents は前回の修正のままで問題ありません
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
        if not contents_for_api and not system_instruction_for_api: return 0
        if not contents_for_api and system_instruction_for_api: return 0 # 実際には system_instruction のみでもトークン数はあるが、ここではUI起因の入力としては稀なので0扱い

        # ▼▼▼ 修正箇所 ▼▼▼
        # プロジェクトのルールに従い、genai.Client をインスタンス化して使用する
        client = genai.Client(api_key=api_key)
        # AI_DEVELOPMENT_GUIDELINES.md では client.models.generate_content() となっているので、
        # count_tokens も client.models.count_tokens() が適切。
        model_to_use = f"models/{model_name}" # count_tokens APIは 'models/' プレフィックスが必要

        response = client.models.count_tokens( # client.count_tokens から client.models.count_tokens へ
            model=model_to_use, # `model` パラメータでモデル名を渡す
            contents=contents_for_api,
            system_instruction=system_instruction_for_api
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
            "api_key": api_key, # LangGraph内でClientを初期化する際に使用される
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

# 通常チャット用の関数も、プロジェクトの作法に準拠した形に修正
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
                system_instruction_text = f.read().strip() # strip() を追加
            if system_instruction_text:
                messages_for_api_direct_call.append({'role': 'user', 'parts': [{'text': system_instruction_text}]})
                messages_for_api_direct_call.append({'role': 'model', 'parts': [{'text': "承知いたしました。"}]})

        for h_item in raw_history:
            # ロールをSDKが期待する 'user' または 'model' に正規化
            sdk_role = "model" if h_item["role"] in ["model", "assistant", character_name] else "user"
            messages_for_api_direct_call.append({
                "role": sdk_role, # 正規化したロールを使用
                "parts": [{'text': h_item["content"]}]
            })

        user_message_parts_for_payload = []
        for part_data in parts:
            if isinstance(part_data, str):
                user_message_parts_for_payload.append({'text': part_data})
            elif isinstance(part_data, Image.Image):
                img_byte_arr = io.BytesIO()
                save_image = part_data.convert('RGB') if part_data.mode in ('RGBA', 'P') else part_data
                save_image.save(img_byte_arr, format='JPEG') # JPEG形式で統一
                user_message_parts_for_payload.append({'inline_data': {'mime_type': 'image/jpeg', 'data': img_byte_arr.getvalue()}})

        if not user_message_parts_for_payload:
            return "エラー: 送信するコンテンツがありません。", None

        messages_for_api_direct_call.append({'role': 'user', 'parts': user_message_parts_for_payload})

        # ▼▼▼ 修正箇所 ▼▼▼
        # プロジェクトのルールに従い、genai.Client をインスタンス化して使用する
        model_to_call_name = f"models/{model_name}" # generate_content APIは 'models/' プレフィックスが必要
        client_for_direct_call = genai.Client(api_key=api_key)
        # AI_DEVELOPMENT_GUIDELINES.md では client.models.generate_content()
        response = client_for_direct_call.models.generate_content( # client.generate_content から client.models.generate_content へ
            model=model_to_call_name, # `model` パラメータでモデル名を渡す
            contents=messages_for_api_direct_call
            # system_instruction は messages_for_api_direct_call に含めているのでここでは不要
        )
        # ▲▲▲ 修正ここまで ▲▲▲

        generated_text = "[応答なし]"
        # response.text が存在するか、より安全に確認
        if hasattr(response, 'text') and response.text:
            generated_text = response.text
        # response.parts が存在し、かつ空でないことを確認
        elif hasattr(response, 'parts') and response.parts:
             generated_text = "".join([part.text for part in response.parts if hasattr(part, 'text') and part.text])
        elif response.prompt_feedback and response.prompt_feedback.block_reason:
            generated_text = f"[応答ブロック: 理由: {response.prompt_feedback.block_reason}]"
        # さらに詳細な候補からの取得も考慮 (AI Studioの提案に近い形)
        elif hasattr(response, 'candidates') and response.candidates and \
             hasattr(response.candidates[0], 'content') and hasattr(response.candidates[0].content, 'parts') and \
             response.candidates[0].content.parts:
            generated_text = "".join([part.text for part in response.candidates[0].content.parts if hasattr(part, 'text') and part.text])


        user_input_text = "".join([p for p in parts if isinstance(p, str)])
        attached_file_names = []
        for p in parts: # 添付ファイル名の取得方法を少し変更
            if not isinstance(p, str):
                if hasattr(p, 'name'): # GradioのFileValueなど
                    attached_file_names.append(os.path.basename(p.name))
                elif isinstance(p, Image.Image) and hasattr(p, 'filename') and p.filename: # PIL Imageオブジェクトでfilename属性がある場合
                     attached_file_names.append(os.path.basename(p.filename))

        if attached_file_names:
            user_input_text += "\n[ファイル添付: " + ", ".join(attached_file_names) + "]"

        if user_input_text.strip(): # ユーザー入力テキストがある場合のみログ保存
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
