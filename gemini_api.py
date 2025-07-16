# gemini_api.py の内容を、以下の、最終版で、完全に、置き換えてください

import traceback
from typing import Any, List, Union, Optional, Dict
import os
import io
import base64
import re
from PIL import Image
import google.genai as genai

from agent.graph import app
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
import config_manager
import utils
import mem0_manager # ★★★ この行を追加 ★★★
from character_manager import get_character_files_paths

# ★★★ ここから、失われた、関数を、復元 ★★★

def get_model_token_limits(model_name: str, api_key: str) -> Optional[Dict[str, int]]:
    """モデルの入力・出力トークン上限を取得する（キャッシュ機能付き）"""
    if model_name in utils._model_token_limits_cache:
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

def _convert_lc_to_gg_for_count(messages: List[Union[SystemMessage, HumanMessage, AIMessage]]) -> List[Dict]:
    """トークン計算のためにLangChainメッセージをGoogle AI SDK形式に変換する"""
    contents = []
    # SystemMessageも変換対象に含める
    for msg in messages:
        role = "model" if isinstance(msg, AIMessage) else "user"
        sdk_parts = []
        if isinstance(msg.content, str):
            sdk_parts.append({"text": msg.content})
        elif isinstance(msg.content, list):
             for part_data in msg.content:
                if part_data.get("type") == "text":
                    sdk_parts.append({"text": part_data["text"]})
        if sdk_parts:
            contents.append({"role": role, "parts": sdk_parts})
    return contents

def count_tokens_from_lc_messages(messages: List, model_name: str, api_key: str) -> int:
    """LangChainメッセージリストからトークン数を計算する"""
    if not messages: return 0
    try:
        client = genai.Client(api_key=api_key)
        contents = _convert_lc_to_gg_for_count(messages)

        # SystemMessageはuser/modelのペアに変換しないと正確に数えられない場合がある
        final_contents_for_api = []
        system_instruction = None
        if contents and contents[0]['role'] == 'user' and isinstance(messages[0], SystemMessage):
             system_instruction = contents[0]['parts']
             # システムプロンプトをuser/modelの会話として扱う
             final_contents_for_api.append({"role": "user", "parts": system_instruction})
             final_contents_for_api.append({"role": "model", "parts": [{"text": "OK"}]})
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
    """UIからの入力全体を評価してトークン数を計算する"""
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"): return -1

    from agent.prompts import ACTOR_PROMPT_TEMPLATE
    messages: List[Union[SystemMessage, HumanMessage, AIMessage]] = []

    # システムプロンプトの構築
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

    # 履歴の追加
    log_file, _, _, _, _ = get_character_files_paths(character_name)
    raw_history = utils.load_chat_log(log_file, character_name)
    limit = int(api_history_limit_option) if api_history_limit_option.isdigit() else 0
    if limit > 0 and len(raw_history) > limit * 2: raw_history = raw_history[-(limit * 2):]
    for h_item in raw_history:
        role, content = h_item.get('role'), h_item.get('content', '').strip()
        if not content: continue
        if role in ['model', 'assistant', character_name]: messages.append(AIMessage(content=content))
        elif role in ['user', 'human']: messages.append(HumanMessage(content=content))

    # ユーザーの最新入力の追加
    user_message_content_parts = []
    text_buffer = []
    for part_item in parts:
        if isinstance(part_item, str): text_buffer.append(part_item)
        elif isinstance(part_item, Image.Image):
            if text_buffer:
                user_message_content_parts.append({"type": "text", "text": "\n".join(text_buffer).strip()})
                text_buffer = []
            buffered = io.BytesIO()
            save_image = part_item.convert('RGB') if part_item.mode in ('RGBA', 'P') and (part_item.format or 'PNG').upper() == 'JPEG' else part_item
            save_image.save(buffered, format=(part_item.format or 'PNG'))
            img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
            mime_type = f"image/{(part_item.format or 'PNG').lower()}"
            user_message_content_parts.append({"type": "image_url", "image_url": f"data:{mime_type};base64,{img_base64}"})
    if text_buffer:
        user_message_content_parts.append({"type": "text", "text": "\n".join(text_buffer).strip()})

    if user_message_content_parts:
        content = user_message_content_parts[0]["text"] if len(user_message_content_parts) == 1 and user_message_content_parts[0]["type"] == "text" else user_message_content_parts
        messages.append(HumanMessage(content=content))

    return count_tokens_from_lc_messages(messages, model_name, api_key)

# ★★★ 復元ここまで ★★★


# 新しいエージェント呼び出し関数 (これは変更なし)
def invoke_nexus_agent(*args: Any) -> str:
    (textbox_content, chatbot_history, current_character_name, current_model_name,
     current_api_key_name_state, file_input_list, add_timestamp_checkbox,
     send_thoughts_state, api_history_limit_state,
     send_notepad_state, use_common_prompt_state) = args

    api_key = config_manager.API_KEYS.get(current_api_key_name_state)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return f"[エラー: APIキー '{current_api_key_name_state}' が有効ではありません。]"

    user_input_text = textbox_content.strip() if textbox_content else ""
    if not user_input_text:
         return "[エラー: テキスト入力がありません]"

    messages = []
    log_file, _, _, _, _ = get_character_files_paths(current_character_name)
    raw_history = utils.load_chat_log(log_file, current_character_name)
    limit = int(api_history_limit_state) if api_history_limit_state.isdigit() else 0
    if limit > 0 and len(raw_history) > limit * 2:
        raw_history = raw_history[-(limit * 2):]
    for h_item in raw_history:
        role, content = h_item.get('role'), h_item.get('content', '').strip()
        if not content: continue
        if role in ['model', 'assistant', current_character_name]:
            messages.append(AIMessage(content=content))
        elif role in ['user', 'human']:
            messages.append(HumanMessage(content=content))

    messages.append(HumanMessage(content=user_input_text))

    initial_state = {
        "messages": messages,
        "character_name": current_character_name,
        "api_key": api_key,
        "tavily_api_key": config_manager.TAVILY_API_KEY,
    }

    try:
        final_state = app.invoke(initial_state)
        final_response_message = final_state['messages'][-1]

        try:
            mem0_instance = mem0_manager.get_mem0_instance(current_character_name, api_key)
            mem0_instance.add([
                {"role": "user", "content": user_input_text},
                {"role": "assistant", "content": final_response_message.content}
            ], user_id=current_character_name)
            print("--- mem0への記憶成功 ---")
        except Exception as e:
            print(f"--- mem0への記憶中にエラー: {e} ---")
            traceback.print_exc()

        return final_response_message.content
    except Exception as e:
        print(f"--- エージェント実行エラー ---")
        traceback.print_exc()
        return f"[エージェント実行エラー: {e}]"
