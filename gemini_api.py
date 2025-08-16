#
# gemini_api.py の内容を、この最終版テキストで完全に置き換えてください
#
import traceback
from typing import Any, List, Union, Optional, Dict, Iterator
import os
import json
import character_manager
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
    LangGraphの思考プロセスをストリーミングで返す。(v20: ポップアップFIX)
    """
    from agent.graph import app
    import time
    from google.api_core.exceptions import ResourceExhausted, InternalServerError
    from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

    # ... (引数の展開、履歴構築、initial_state定義の部分は変更なし) ...
    # --- 引数を辞書から展開 ---
    character_to_respond = agent_args["character_to_respond"]
    api_key_name = agent_args["api_key_name"]
    api_history_limit = agent_args["api_history_limit"]
    debug_mode = agent_args["debug_mode"]
    history_log_path = agent_args["history_log_path"]
    user_prompt_parts = agent_args["user_prompt_parts"]
    soul_vessel_character = agent_args["soul_vessel_character"]
    active_participants = agent_args["active_participants"]
    shared_location_name = agent_args["shared_location_name"]
    shared_scenery_text = agent_args["shared_scenery_text"]

    all_participants_list = [soul_vessel_character] + active_participants
    effective_settings = config_manager.get_effective_settings(
        character_to_respond,
        use_common_prompt=(len(all_participants_list) <= 1)
    )
    model_name = effective_settings["model_name"]
    api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)

    if not api_key or api_key.startswith("YOUR_API_KEY"):
        yield {"final_output": {"response": f"[エラー: APIキー '{api_key_name}' が有効ではありません。]"}}
        return

    messages = []
    responding_ai_log_f, _, _, _, _ = character_manager.get_character_files_paths(character_to_respond)
    if responding_ai_log_f and os.path.exists(responding_ai_log_f):
        own_history_raw = utils.load_chat_log(responding_ai_log_f, character_to_respond)
        messages = utils.convert_raw_log_to_lc_messages(own_history_raw, character_to_respond)

    if history_log_path and os.path.exists(history_log_path):
        snapshot_history_raw = utils.load_chat_log(history_log_path, soul_vessel_character)
        snapshot_messages = utils.convert_raw_log_to_lc_messages(snapshot_history_raw, character_to_respond)
        if snapshot_messages and messages:
            first_snapshot_user_message_content = ""
            if isinstance(snapshot_messages[0], HumanMessage):
                first_snapshot_user_message_content = snapshot_messages[0].content.split("（")[0].strip()
            if first_snapshot_user_message_content:
                for i in range(len(messages) - 1, -1, -1):
                    if isinstance(messages[i], HumanMessage):
                        own_log_user_content = messages[i].content.split("（")[0].strip()
                        if own_log_user_content == first_snapshot_user_message_content:
                            messages = messages[:i]
                            break
            messages.extend(snapshot_messages)
        elif snapshot_messages:
            messages = snapshot_messages
    limit = int(api_history_limit) if api_history_limit.isdigit() else 0
    if limit > 0 and len(messages) > limit * 2:
        messages = messages[-(limit * 2):]

    # 5. ユーザーの最新の発言（テキスト＋ファイル）を履歴の最後に追加する
    if user_prompt_parts:
        messages.append(HumanMessage(content=user_prompt_parts))

    initial_state = {
        "messages": messages, "character_name": character_to_respond, "api_key": api_key,
        "tavily_api_key": config_manager.TAVILY_API_KEY, "model_name": model_name,
        "send_core_memory": effective_settings.get("send_core_memory", True),
        "send_scenery": effective_settings.get("send_scenery", True),
        "send_notepad": effective_settings.get("send_notepad", True), "debug_mode": debug_mode,
        "location_name": shared_location_name, "scenery_text": shared_scenery_text,
        "all_participants": all_participants_list
    }

    # --- エージェント実行ループ ---
    max_retries = 3
    final_state = None
    last_message = None
    tool_popups = [] # ポップアップメッセージを収集するリスト

    for attempt in range(max_retries):
        # ... (リトライ機構は変更なし) ...
        is_final_attempt = (attempt == max_retries - 1)
        try:
            print(f"--- エージェント実行試行: {attempt + 1}/{max_retries} ---")
            for update in app.stream(initial_state, {"recursion_limit": 15}):
                yield {"stream_update": update}
                final_state = update

                # ▼▼▼【ここからが修正箇所】▼▼▼
                # ストリームの途中でツール使用を検知し、ポップアップメッセージを収集
                node_name = list(update.keys())[0]
                if node_name == "safe_tool_node":
                    tool_messages = update[node_name].get("messages", [])
                    for tool_msg in tool_messages:
                        if isinstance(tool_msg, ToolMessage):
                            display_text = utils.format_tool_result_for_ui(tool_msg.name, tool_msg.content)
                            if display_text:
                                tool_popups.append(display_text)
                # ▲▲▲【修正ここまで】▲▲▲

            # ... (ループ内の残りの部分は変更なし) ...
            if final_state and isinstance(final_state, dict):
                agent_final_state = final_state.get("agent", {})
                last_message = next(reversed(agent_final_state.get("messages", [])), None)
            if isinstance(last_message, AIMessage) and (last_message.content or last_message.tool_calls):
                print(f"--- 試行 {attempt + 1}: 有効な応答を受信しました。 ---"); break
            if isinstance(last_message, AIMessage):
                finish_reason = last_message.response_metadata.get('finish_reason', '')
                if finish_reason == 'STOP':
                    if not is_final_attempt: print(f"--- [警告] 試行 {attempt + 1}: AIが空応答 (STOP)。リトライします... ---"); time.sleep(1); continue
                else: print(f"--- 試行 {attempt + 1}: リトライ対象外 ({finish_reason}) で終了。 ---"); break
        except InternalServerError:
            if not is_final_attempt: print(f"--- [警告] 試行 {attempt + 1}: 500エラー。リトライします... ---"); time.sleep((attempt + 1) * 2); continue
            else: final_state = {"response": "[APIエラー: サーバー内部エラー(500)が頻発しました。]"}; break
        except ResourceExhausted as e:
            if "PerMinute" in str(e) and not is_final_attempt: print(f"--- [警告] 試行 {attempt + 1}: レート制限。61秒待機... ---"); time.sleep(61); continue
            final_state = {"response": "[APIエラー: リソース上限に達しました。]"}; break
        except Exception as e:
            final_state = {"response": f"[エージェント実行エラー: {e}]"}; traceback.print_exc(); break

    # --- 最終的な出力を整形して返す ---
    final_response = {}
    if final_state and isinstance(final_state, dict):
        # ... (final_responseの構築部分は変更なし) ...
        final_response["response"] = final_state.get("response", "")
        final_response["location_name"] = final_state.get("context_generator", {}).get("location_name", "（不明）")
        final_response["scenery"] = final_state.get("context_generator", {}).get("scenery_text", "（不明）")
        final_response_text = ""
        if isinstance(last_message, AIMessage):
            # ▼▼▼【ここからが修正箇所】▼▼▼
            content = last_message.content
            if isinstance(content, str):
                final_response_text = content.strip()
            elif isinstance(content, list):
                # 応答がパーツのリストである場合、テキスト部分を結合する
                text_parts = []
                for part in content:
                    if isinstance(part, str):
                        text_parts.append(part)
                    elif isinstance(part, dict) and 'text' in part:
                        text_parts.append(part['text'])
                final_response_text = "".join(text_parts).strip()
            # ▲▲▲【修正ここまで】▲▲▲

            if not final_response_text and not last_message.tool_calls:
                finish_reason = last_message.response_metadata.get('finish_reason', '')
                if finish_reason == 'SAFETY': final_response_text = "[エラー: 応答が安全フィルターにブロックされました。]"
                elif finish_reason == 'RECITATION': final_response_text = "[エラー: 応答が引用要件によりブロックされました。]"
                else: final_response_text = "[エラー: AIからの有効な応答がありませんでした。]"
        if not final_response.get("response"): final_response["response"] = final_response_text
    if not final_response: final_response["response"] = "[エラー: 不明な理由でエージェントが完了しませんでした。]"

    final_response["tool_popups"] = tool_popups # 収集したポップアップを最終結果に含める

    yield {"final_output": final_response}

def count_input_tokens(**kwargs):
    character_name = kwargs.get("character_name")
    api_key_name = kwargs.get("api_key_name")
    api_history_limit = kwargs.get("api_history_limit")
    parts = kwargs.get("parts", [])

    api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"): return "トークン数: (APIキーエラー)"

    try:
        # ▼▼▼【修正の核心】▼▼▼
        # kwargs辞書からcharacter_nameを削除したコピーを作成し、それを渡す
        # これで'character_name'が重複して渡されるのを防ぐ
        kwargs_for_settings = kwargs.copy()
        kwargs_for_settings.pop("character_name", None)

        effective_settings = config_manager.get_effective_settings(character_name, **kwargs_for_settings)
        # ▲▲▲ 修正ここまで ▲▲▲

        model_name = effective_settings.get("model_name") or config_manager.DEFAULT_MODEL_GLOBAL
        messages: List[Union[SystemMessage, HumanMessage, AIMessage]] = []

        # --- システムプロンプトの構築 ---
        from agent.prompts import CORE_PROMPT_TEMPLATE
        from agent.graph import all_tools
        char_prompt_path = os.path.join(constants.CHARACTERS_DIR, character_name, "SystemPrompt.txt")
        character_prompt = ""
        if os.path.exists(char_prompt_path):
            with open(char_prompt_path, 'r', encoding='utf-8') as f: character_prompt = f.read().strip()
        core_memory = ""
        if effective_settings.get("send_core_memory", True):
            core_memory_path = os.path.join(constants.CHARACTERS_DIR, character_name, "core_memory.txt")
            if os.path.exists(core_memory_path):
                with open(core_memory_path, 'r', encoding='utf-8') as f: core_memory = f.read().strip()
        notepad_section = ""
        if effective_settings.get("send_notepad", True):
            _, _, _, _, notepad_path = character_manager.get_character_files_paths(character_name)
            if notepad_path and os.path.exists(notepad_path):
                with open(notepad_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    notepad_content = content if content else "（メモ帳は空です）"
                    notepad_section = f"\n### 短期記憶（メモ帳）\n{notepad_content}\n"

        tools_list_str = "\n".join([f"- `{tool.name}({', '.join(tool.args.keys())})`: {tool.description}" for tool in all_tools])
        class SafeDict(dict):
            def __missing__(self, key): return f'{{{key}}}'
        prompt_vars = {
            'character_name': character_name, 'character_prompt': character_prompt, 'core_memory': core_memory,
            'notepad_section': notepad_section, 'tools_list': tools_list_str
        }
        system_prompt_text = CORE_PROMPT_TEMPLATE.format_map(SafeDict(prompt_vars))
        if effective_settings.get("send_scenery", True):
            system_prompt_text += "\n\n---\n【現在の場所と情景】\n（トークン計算ではAPIコールを避けるため、実際の情景は含めず、存在することを示すプレースホルダのみ考慮）\n- 場所の名前: サンプル\n- 場所の定義: サンプル\n- 今の情景: サンプル\n---"
        messages.append(SystemMessage(content=system_prompt_text))

        # --- 履歴の構築 ---
        log_file, _, _, _, _ = character_manager.get_character_files_paths(character_name)
        raw_history = utils.load_chat_log(log_file, character_name)
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
