#
# gemini_api.py の内容を、この最終版テキストで完全に置き換えてください
#
import traceback
from typing import Any, List, Union, Optional, Dict, Iterator
import os
import json
import room_manager
import utils
import io
import base64
from PIL import Image
import google.genai as genai
import filetype
import httpx
from google.api_core.exceptions import ResourceExhausted
import re

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
import config_manager
import constants

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

# gemini_api.py の invoke_nexus_agent_stream を完全に置き換え

def invoke_nexus_agent_stream(agent_args: dict) -> Iterator[Dict[str, Any]]:
    """
    LangGraphの思考プロセスをストリーミングで返す。(v23: 辞書引数FIX)
    """
    from agent.graph import app
    import time
    from google.api_core.exceptions import ResourceExhausted, InternalServerError
    from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

    # --- 引数を辞書から展開 ---
    room_to_respond = agent_args["room_to_respond"]
    api_key_name = agent_args["api_key_name"]
    api_history_limit = agent_args["api_history_limit"]
    debug_mode = agent_args["debug_mode"]
    history_log_path = agent_args["history_log_path"]
    user_prompt_parts = agent_args["user_prompt_parts"]
    soul_vessel_room = agent_args["soul_vessel_room"]
    active_participants = agent_args["active_participants"]
    shared_location_name = agent_args["shared_location_name"]
    shared_scenery_text = agent_args["shared_scenery_text"]

    all_participants_list = [soul_vessel_room] + active_participants
    effective_settings = config_manager.get_effective_settings(
        room_to_respond,
        use_common_prompt=(len(all_participants_list) <= 1)
    )
    model_name = effective_settings["model_name"]
    api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)

    if not api_key or api_key.startswith("YOUR_API_KEY"):
        yield {"final_output": {"response": f"[エラー: APIキー '{api_key_name}' が有効ではありません。]"}}
        return

    # --- ハイブリッド履歴構築ロジック ---
    messages = []
    responding_ai_log_f, _, _, _, _ = room_manager.get_room_files_paths(room_to_respond)
    if responding_ai_log_f and os.path.exists(responding_ai_log_f):
        own_history_raw = utils.load_chat_log(responding_ai_log_f)
        messages = utils.convert_raw_log_to_lc_messages(own_history_raw, room_to_respond)

    if history_log_path and os.path.exists(history_log_path):
        snapshot_history_raw = utils.load_chat_log(history_log_path)
        snapshot_messages = utils.convert_raw_log_to_lc_messages(snapshot_history_raw, room_to_respond)
        if snapshot_messages and messages:
            # スナップショットの最初のユーザー発言を取得
            first_snapshot_user_message_content = None
            for msg in snapshot_messages:
                if isinstance(msg, HumanMessage):
                    first_snapshot_user_message_content = msg.content
                    break

            # 自分の履歴(messages)の後方から、スナップショットの開始点と同じ発言を探す
            if first_snapshot_user_message_content:
                for i in range(len(messages) - 1, -1, -1):
                    if isinstance(messages[i], HumanMessage) and messages[i].content == first_snapshot_user_message_content:
                        # 発見したら、そこから後ろを一旦削除して、スナップショットで置き換える
                        messages = messages[:i]
                        break

            messages.extend(snapshot_messages)
        elif snapshot_messages:
            messages = snapshot_messages

    # if user_prompt_parts:
    #     messages.append(HumanMessage(content=user_prompt_parts))

    limit = int(api_history_limit) if api_history_limit.isdigit() else 0
    if limit > 0 and len(messages) > limit * 2:
        messages = messages[-(limit * 2):]

    initial_state = {
        "messages": messages, "room_name": room_to_respond,
        "api_key": api_key, "tavily_api_key": config_manager.TAVILY_API_KEY,
        "model_name": model_name, "send_core_memory": effective_settings.get("send_core_memory", True),
        "send_scenery": effective_settings.get("send_scenery", True), "send_notepad": effective_settings.get("send_notepad", True),
        "debug_mode": debug_mode, "location_name": shared_location_name,
        "scenery_text": shared_scenery_text, "all_participants": all_participants_list
    }

    # --- エージェント実行ループ ---
    max_retries = 3
    retry_delay = 5  # seconds

    for attempt in range(max_retries):
        try:
            # 思考プロセスをストリーミングで実行
            for update in app.stream(initial_state, stream_mode="values"):
                # UIにストリームの更新を通知 (現在は未使用だが将来のために残す)
                yield {"stream_update": update}

            # ストリームの最後の値が最終状態
            final_state = update

            # 最終的なAIの応答メッセージを取得
            final_message = final_state["messages"][-1]
            response_text = ""
            tool_popups = []

            if isinstance(final_message, AIMessage):
                response_text = final_message.content

            # ▼▼▼【ここからが修正の核心】▼▼▼
            # ツール実行結果のポップアップを生成
            # 今回の処理で新しく追加された全てのメッセージを対象とする
            initial_message_count = len(initial_state["messages"])
            new_messages = final_state["messages"][initial_message_count:]

            for msg in new_messages:
                if isinstance(msg, ToolMessage):
                    popup_text = utils.format_tool_result_for_ui(msg.name, str(msg.content))
                    if popup_text:
                        tool_popups.append(popup_text)
            # ▲▲▲【修正ここまで】▲▲▲

            yield {"final_output": {"response": response_text, "tool_popups": tool_popups}}
            return # 正常に終了したのでループを抜ける

        except (ResourceExhausted, InternalServerError) as e:
            # サーバー側のエラー (リソース枯渇や内部エラー)
            print(f"--- APIエラー (試行 {attempt + 1}/{max_retries}): {e} ---")
            if attempt < max_retries - 1:
                print(f"    - {retry_delay}秒待機してリトライします...")
                time.sleep(retry_delay)
                # 次のリトライのために遅延を増やす
                retry_delay *= 2
            else:
                error_message = f"[エラー: APIサーバーが応答しませんでした。時間をおいて再試行してください。詳細: {e}]"
                yield {"final_output": {"response": error_message, "tool_popups": []}}
                return

        except Exception as e:
            # その他の予期せぬエラー
            print(f"--- エージェント実行中に予期せぬエラーが発生しました ---")
            traceback.print_exc()
            error_message = f"[エラー: 内部処理で問題が発生しました。詳細はターミナルを確認してください。エラー: {e}]"
            yield {"final_output": {"response": error_message, "tool_popups": []}}
            return

def count_input_tokens(**kwargs):
    room_name = kwargs.get("room_name")
    api_key_name = kwargs.get("api_key_name")
    api_history_limit = kwargs.get("api_history_limit")
    parts = kwargs.get("parts", [])

    api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"): return "トークン数: (APIキーエラー)"

    try:
        kwargs_for_settings = kwargs.copy()
        kwargs_for_settings.pop("room_name", None)
        kwargs_for_settings.pop("api_key_name", None)
        kwargs_for_settings.pop("api_history_limit", None)
        kwargs_for_settings.pop("parts", None)

        effective_settings = config_manager.get_effective_settings(room_name, **kwargs_for_settings)

        model_name = effective_settings.get("model_name") or config_manager.DEFAULT_MODEL_GLOBAL
        messages: List[Union[SystemMessage, HumanMessage, AIMessage]] = []

        # --- システムプロンプトの構築 ---
        from agent.prompts import CORE_PROMPT_TEMPLATE
        from agent.graph import all_tools
        room_prompt_path = os.path.join(constants.ROOMS_DIR, room_name, "SystemPrompt.txt")
        character_prompt = ""
        if os.path.exists(room_prompt_path):
            with open(room_prompt_path, 'r', encoding='utf-8') as f: character_prompt = f.read().strip()
        core_memory = ""
        if effective_settings.get("send_core_memory", True):
            core_memory_path = os.path.join(constants.ROOMS_DIR, room_name, "core_memory.txt")
            if os.path.exists(core_memory_path):
                with open(core_memory_path, 'r', encoding='utf-8') as f: core_memory = f.read().strip()
        notepad_section = ""
        if effective_settings.get("send_notepad", True):
            _, _, _, _, notepad_path = room_manager.get_room_files_paths(room_name)
            if notepad_path and os.path.exists(notepad_path):
                with open(notepad_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    notepad_content = content if content else "（メモ帳は空です）"
                    notepad_section = f"\n### 短期記憶（メモ帳）\n{notepad_content}\n"

        tools_list_str = "\n".join([f"- `{tool.name}({', '.join(tool.args.keys())})`: {tool.description}" for tool in all_tools])
        class SafeDict(dict):
            def __missing__(self, key): return f'{{{key}}}'
        prompt_vars = {
            'room_name': room_name, 'character_prompt': character_prompt, 'core_memory': core_memory,
            'notepad_section': notepad_section, 'tools_list': tools_list_str
        }
        system_prompt_text = CORE_PROMPT_TEMPLATE.format_map(SafeDict(prompt_vars))
        if effective_settings.get("send_scenery", True):
            system_prompt_text += "\n\n---\n【現在の場所と情景】\n（トークン計算ではAPIコールを避けるため、実際の情景は含めず、存在することを示すプレースホルダのみ考慮）\n- 場所の名前: サンプル\n- 場所の定義: サンプル\n- 今の情景: サンプル\n---"
        messages.append(SystemMessage(content=system_prompt_text))

        # --- 履歴の構築 ---
        log_file, _, _, _, _ = room_manager.get_room_files_paths(room_name)
        raw_history = utils.load_chat_log(log_file)
        limit = int(api_history_limit) if api_history_limit and api_history_limit.isdigit() else 0
        if limit > 0 and len(raw_history) > limit * 2:
            raw_history = raw_history[-(limit * 2):]

        for h_item in raw_history:
            content = h_item.get('content', '').strip()
            if not content: continue
            if h_item.get('responder', 'model') != 'user':
                 messages.append(AIMessage(content=content))
            else:
                 messages.append(HumanMessage(content=content))

        # --- 現在の入力の構築 ---
        if parts:
            formatted_parts = []
            for part in parts:
                if isinstance(part, str): formatted_parts.append({"type": "text", "text": part})
                elif isinstance(part, Image.Image):
                    try:
                        mime_type = Image.MIME.get(part.format, 'image/png')
                        buffered = io.BytesIO(); part.save(buffered, format=part.format or "PNG")
                        encoded_string = base64.b64encode(buffered.getvalue()).decode("utf-8")
                        formatted_parts.append({"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded_string}"}})
                    except Exception as img_e: print(f"画像変換エラー（トークン計算中）: {img_e}"); formatted_parts.append({"type": "text", "text": "[画像変換エラー]"})
            if formatted_parts: messages.append(HumanMessage(content=formatted_parts))

        # --- トークン数の計算 ---
        total_tokens = count_tokens_from_lc_messages(messages, model_name, api_key)

        limit_info = get_model_token_limits(model_name, api_key)
        if limit_info and 'input' in limit_info: return f"入力トークン数: {total_tokens} / {limit_info['input']}"
        else: return f"入力トークン数: {total_tokens}"

    except httpx.ReadError as e:
        print(f"トークン計算中にネットワーク読み取りエラー: {e}")
        return "トークン数: (ネットワークエラー)"
    except httpx.ConnectError as e:
        print(f"トークン計算中にAPI接続エラー: {e}")
        return "トークン数: (API接続エラー)"
    except Exception as e:
        print(f"トークン計算中に予期せぬエラー: {e}")
        traceback.print_exc()
        return "トークン数: (例外発生)"
