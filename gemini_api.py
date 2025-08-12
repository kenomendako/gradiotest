#
# gemini_api.py の内容を、この最終版テキストで完全に置き換えてください
#
import traceback
from typing import Any, List, Union, Optional, Dict, Iterator
import os
import json
import io
import base64
from PIL import Image
import google.genai as genai
import filetype
import httpx
from google.api_core.exceptions import ResourceExhausted

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
import config_manager
import constants
import utils
from character_manager import get_character_files_paths

# (get_model_token_limits, _convert_lc_to_gg_for_count, count_tokens_from_lc_messages は変更なし)
def get_model_token_limits(model_name: str, api_key: str) -> Optional[Dict[str, int]]:
    if model_name in utils._model_token_limits_cache: return utils._model_token_limits_cache[model_name]
    if not api_key or api_key.startswith("YOUR_API_KEY"): return None
    try:
        client = genai.Client(api_key=api_key)
        model_info = client.models.get(model=f"models/{model_name}")
        if model_info and hasattr(model_info, 'input_token_limit') and hasattr(model_info, 'output_token_limit'):
            limits = {"input": model_info.input_token_limit, "output": model_info.output_token_limit}
            utils._model_token_limits_cache[model_name] = limits
            return limits
        return None
    except Exception as e: print(f"モデル情報の取得中にエラー: {e}"); return None

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
                if part_type == "text": sdk_parts.append({"text": part_data.get("text", "")})
                elif part_type == "image_url":
                    url_data = part_data.get("image_url", {}).get("url", "")
                    if url_data.startswith("data:"):
                        try:
                            header, encoded = url_data.split(",", 1); mime_type = header.split(":")[1].split(";")[0]
                            sdk_parts.append({"inline_data": {"mime_type": mime_type, "data": encoded}})
                        except: pass
                elif part_type == "media": sdk_parts.append({"inline_data": {"mime_type": part_data.get("mime_type", "application/octet-stream"),"data": part_data.get("data", "")}})
        if sdk_parts: contents.append({"role": role, "parts": sdk_parts})
    return contents

def count_tokens_from_lc_messages(messages: List, model_name: str, api_key: str) -> int:
    if not messages: return 0
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

def invoke_nexus_agent_stream(*args: Any) -> Iterator[Dict[str, Any]]:
    """
    LangGraphの思考プロセスをステップごとにストリーミングで返し、
    最終的な応答と状態も返すジェネレータ。(v2: アーキテクチャ修復版)
    """
    (textbox_content, current_character_name,
     current_api_key_name_state, file_input_list,
     api_history_limit_state, debug_mode_state) = args

    from agent.graph import app
    effective_settings = config_manager.get_effective_settings(current_character_name)
    current_model_name = effective_settings["model_name"]
    api_key = config_manager.GEMINI_API_KEYS.get(current_api_key_name_state)

    if not api_key or api_key.startswith("YOUR_API_KEY"):
        yield {"final_output": {"response": f"[エラー: APIキー '{current_api_key_name_state}' が有効ではありません。]"}}
        return

    user_input_text = textbox_content.strip() if textbox_content else ""
    is_internal_call = user_input_text.startswith("（システム")
    if not user_input_text and not file_input_list and not is_internal_call:
        yield {"final_output": {"response": "[エラー: テキスト入力またはファイル添付がありません]"}}
        return

    # --- 履歴と入力メッセージの構築 ---
    messages = []
    log_file, _, _, _, _ = get_character_files_paths(current_character_name)
    # ここでは、呼び出し元のキャラクター自身の履歴のみを取得する
    raw_history = utils.load_chat_log(log_file, current_character_name)
    limit = int(api_history_limit_state) if api_history_limit_state.isdigit() else 0
    if limit > 0 and len(raw_history) > limit * 2:
        raw_history = raw_history[-(limit * 2):]

    for h_item in raw_history:
        role, content = h_item.get('role'), h_item.get('content', '').strip()
        if not content: continue
        # ログから読み込む際は、思考ログは除去しない（AIの思考の文脈として重要）
        if h_item.get('responder', 'model') != 'user':
            messages.append(AIMessage(content=content))
        else:
            messages.append(HumanMessage(content=content))

    user_message_parts = []
    if user_input_text: user_message_parts.append({"type": "text", "text": user_input_text})
    if file_input_list:
        for file_obj in file_input_list:
            filepath = file_obj.name
            try:
                kind = filetype.guess(filepath); mime_type = kind.mime if kind else "application/octet-stream"
                if mime_type.startswith("image/"):
                    with open(filepath, "rb") as f: file_data = base64.b64encode(f.read()).decode("utf-8")
                    user_message_parts.append({"type": "image_url", "image_url": { "url": f"data:{mime_type};base64,{file_data}"}})
                else: # 音声・動画・テキストファイル
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f: text_content = f.read()
                    user_message_parts.append({"type": "text", "text": f"--- 添付ファイル「{os.path.basename(filepath)}」の内容 ---\n{text_content}\n--- ファイル内容ここまで ---"})
            except Exception as e: print(f"警告: ファイル '{os.path.basename(filepath)}' の処理に失敗。スキップ。エラー: {e}")
    if user_message_parts: messages.append(HumanMessage(content=user_message_parts))

    initial_state = {
        "messages": messages, "character_name": current_character_name, "api_key": api_key,
        "tavily_api_key": config_manager.TAVILY_API_KEY, "model_name": current_model_name,
        "send_core_memory": effective_settings.get("send_core_memory", True),
        "send_scenery": effective_settings.get("send_scenery", True),
        "send_notepad": effective_settings.get("send_notepad", True),
        "debug_mode": debug_mode_state
    }

    final_state = None
    try:
        # app.stream() を使って、各ステップの状態を受け取る
        for update in app.stream(initial_state):
            yield {"stream_update": update}
            final_state = update # 最後の更新が最終状態になる

    except ResourceExhausted as e:
        if "PerDay" in str(e):
            final_state = {"response": "[APIエラー: 無料利用枠の1日あたりのリクエスト上限に達しました。]"}
        else:
            final_state = {"response": "[APIエラー: AIとの通信が一時的に混み合っているようです。]"}
    except Exception as e:
        traceback.print_exc()
        final_state = {"response": f"[エージェント実行エラー: {e}]"}

    # --- 最終的な出力を整形して返す ---
    final_response = {}
    if final_state and isinstance(final_state, dict):
        last_message = next(reversed(final_state.get("agent", {}).get("messages", [])), None)
        final_response_text = ""
        if isinstance(last_message, AIMessage):
            final_response_text = str(last_message.content or "").strip()

        # 応答が空でも、ツール呼び出しがあれば成功と見なす
        if not final_response_text and isinstance(last_message, AIMessage) and last_message.tool_calls:
             final_response_text = "" # ツール呼び出しのみの場合はテキストは空

        elif not final_response_text:
             final_response_text = final_state.get("response", "[エラー: AIから予期せぬ形式の応答がありました。]")

        final_response["response"] = final_response_text
        final_response["location_name"] = final_state.get("context_generator", {}).get("location_name", "（不明）")
        final_response["scenery"] = final_state.get("context_generator", {}).get("scenery_text", "（不明）")

    yield {"final_output": final_response}
