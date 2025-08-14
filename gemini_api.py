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
import re

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
    (character_to_respond, api_key_name,
     api_history_limit, debug_mode,
     history_log_path, file_input_list, user_prompt_text,
     soul_vessel_character, active_participants) = args # 引数を追加

    from agent.graph import app
    import time
    from google.api_core.exceptions import ResourceExhausted, InternalServerError
    from langchain_core.messages import HumanMessage, AIMessage

    effective_settings = config_manager.get_effective_settings(character_to_respond)
    model_name = effective_settings["model_name"]
    api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)

    if not api_key or api_key.startswith("YOUR_API_KEY"):
        yield {"final_output": {"response": f"[エラー: APIキー '{api_key_name}' が有効ではありません。]"}}
        return

    # この時点では initial_state はまだ定義されていないので、先に履歴を構築する

    # --- ハイブリッド履歴構築ロジック (v16) ---
    from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

    messages = []

    # 1. 応答するAI自身の過去ログを読み込み、LangChainメッセージに変換
    responding_ai_log_f, _, _, _, _ = character_manager.get_character_files_paths(character_to_respond)
    if responding_ai_log_f and os.path.exists(responding_ai_log_f):
        own_history_raw = utils.load_chat_log(responding_ai_log_f, character_to_respond)
        messages = utils.convert_raw_log_to_lc_messages(own_history_raw)

    # 2. 今回の対話ターンのスナップショット（公式史）を読み込む
    turn_snapshot_history_raw = []
    main_character_name_for_snapshot = character_to_respond # デフォルトは自分
    if 'active_participants' in locals() and active_participants: # active_participantsが定義されていれば使う
        main_character_name_for_snapshot = soul_vessel_character

    if history_log_path and os.path.exists(history_log_path):
        turn_snapshot_history_raw = utils.load_chat_log(history_log_path, main_character_name_for_snapshot)

    # 3. 自分のログとスナップショットを結合し、重複を除去
    if turn_snapshot_history_raw:
        snapshot_messages = utils.convert_raw_log_to_lc_messages(turn_snapshot_history_raw)

        if snapshot_messages and messages:
            # スナップショットの最初のユーザー発言を探す
            first_snapshot_user_message_content = ''
            for msg in snapshot_messages:
                if isinstance(msg, HumanMessage):
                    # HumanMessageのcontentがリストの場合と文字列の場合を考慮
                    if isinstance(msg.content, list):
                        for part in msg.content:
                            if isinstance(part, dict) and part.get("type") == "text":
                                first_snapshot_user_message_content = part.get("text", "").strip()
                                break
                    elif isinstance(msg.content, str):
                        first_snapshot_user_message_content = msg.content.strip()
                    if first_snapshot_user_message_content:
                        break

            if first_snapshot_user_message_content:
                for i in range(len(messages) - 1, -1, -1):
                    msg = messages[i]
                    if isinstance(msg, HumanMessage):
                        # こちらもcontentがリストか文字列かを判定
                        msg_content_text = ""
                        if isinstance(msg.content, list):
                             for part in msg.content:
                                if isinstance(part, dict) and part.get("type") == "text":
                                    msg_content_text = part.get("text", "").strip()
                                    break
                        elif isinstance(msg.content, str):
                            msg_content_text = msg.content.strip()

                        if msg_content_text == first_snapshot_user_message_content:
                            messages = messages[:i] # 重複部分をカット
                            break
        messages.extend(snapshot_messages)

    # 4. 履歴制限を適用し、AIの連続応答を結合する
    limit = int(api_history_limit) if api_history_limit.isdigit() else 0
    if limit > 0 and len(messages) > limit * 2:
        messages = messages[-(limit * 2):]

    final_messages = utils.merge_consecutive_ais(messages)

    # 5. ユーザーの最新の発言を履歴の最後に追加する（ファイル添付情報も考慮）
    user_message_parts = []
    if user_prompt_text:
        user_message_parts.append({"type": "text", "text": user_prompt_text})
    if file_input_list:
        # (ファイル処理ロジックはここに実装)
        pass # このリクエストではファイル処理の実装はスコープ外

    if user_message_parts:
        # 最後のメッセージが同じユーザープロンプトなら置き換える（安全策）
        last_msg_is_same = False
        if (final_messages and isinstance(final_messages[-1], HumanMessage)):
            last_msg_content = final_messages[-1].content
            if isinstance(last_msg_content, str):
                last_msg_is_same = last_msg_content.strip() == user_prompt_text
            elif isinstance(last_msg_content, list):
                 # リスト内のテキスト部分を比較
                 text_in_last_msg = "".join([p.get("text", "") for p in last_msg_content if isinstance(p, dict) and p.get("type") == "text"]).strip()
                 text_in_current_prompt = "".join([p.get("text", "") for p in user_message_parts if isinstance(p, dict) and p.get("type") == "text"]).strip()
                 last_msg_is_same = text_in_last_msg == text_in_current_prompt

        if last_msg_is_same:
            final_messages[-1] = HumanMessage(content=user_message_parts)
        else:
            final_messages.append(HumanMessage(content=user_message_parts))

    # initial_state の定義
    initial_state = {
        "messages": final_messages,
        "character_name": character_to_respond,
        "api_key": api_key, "tavily_api_key": config_manager.TAVILY_API_KEY,
        "model_name": model_name, "send_core_memory": effective_settings.get("send_core_memory", True),
        "send_scenery": effective_settings.get("send_scenery", True), "send_notepad": effective_settings.get("send_notepad", True),
        "debug_mode": debug_mode,
        "soul_vessel_character": soul_vessel_character, # 追加
        "active_participants": active_participants      # 追加
    }

    # --- エージェント実行ループ (リトライ機構は維持) ---
    max_retries = 3
    final_state = None
    last_message = None

    for attempt in range(max_retries):
        is_final_attempt = (attempt == max_retries - 1)
        try:
            print(f"--- エージェント実行試行: {attempt + 1}/{max_retries} ---")
            for update in app.stream(initial_state, {"recursion_limit": 15}):
                yield {"stream_update": update}
                final_state = update

            if final_state and isinstance(final_state, dict):
                agent_final_state = final_state.get("agent", {})
                last_message = next(reversed(agent_final_state.get("messages", [])), None)

            if isinstance(last_message, AIMessage) and (last_message.content or last_message.tool_calls):
                print(f"--- 試行 {attempt + 1}: 有効な応答を受信しました。 ---")
                break

            if isinstance(last_message, AIMessage):
                finish_reason = last_message.response_metadata.get('finish_reason', '')
                if finish_reason == 'STOP':
                    print(f"--- [警告] 試行 {attempt + 1}: AIが空の応答を返しました (理由: STOP)。 ---")
                    if not is_final_attempt: time.sleep(1); continue
                else:
                    print(f"--- 試行 {attempt + 1}: リトライ対象外の理由 ({finish_reason}) で処理を終了します。 ---")
                    break
        except InternalServerError as e:
            # (500エラーのリトライ処理は変更なし)
            print(f"--- [警告] 試行 {attempt + 1}: 500 内部サーバーエラーが発生しました。 ---")
            if not is_final_attempt:
                wait_time = (attempt + 1) * 2
                print(f"    -> {wait_time}秒待機してリトライします...")
                time.sleep(wait_time)
                continue
            else:
                final_state = {"response": "[APIエラー: サーバー内部エラー(500)が繰り返し発生しました。時間をおいて再度お試しください。]"}
                break
        except ResourceExhausted as e:
            # (レート制限のリトライ処理は変更なし)
            error_str = str(e)
            if "PerMinute" in error_str:
                print(f"--- [警告] 試行 {attempt + 1}: 1分あたりの利用上限に達しました。 ---")
                if not is_final_attempt:
                    wait_time = 61
                    print(f"    -> {wait_time}秒待機してリトライします...")
                    time.sleep(wait_time)
                    continue
            final_state = {"response": "[APIエラー: 無料利用枠の1日あたりのリクエスト上限か、サーバーの負荷上限に達しました。]"}
            print(f"--- 回復不能なAPIリソース枯渇エラー: {e} ---")
            break
        except Exception as e:
            final_state = {"response": f"[エージェント実行エラー: {e}]"}
            traceback.print_exc()
            break

    # --- 最終的な出力を整形して返す (変更なし) ---
    final_response = {}
    if final_state and isinstance(final_state, dict):
        final_response["response"] = final_state.get("response", "")
        final_response["location_name"] = final_state.get("context_generator", {}).get("location_name", "（不明）")
        final_response["scenery"] = final_state.get("context_generator", {}).get("scenery_text", "（不明）")
        final_response_text = ""
        if isinstance(last_message, AIMessage):
            final_response_text = str(last_message.content or "").strip()
            if not final_response_text and not last_message.tool_calls:
                finish_reason = last_message.response_metadata.get('finish_reason', '')
                if finish_reason == 'SAFETY':
                    final_response_text = "[エラー: AIの応答が安全フィルターによってブロックされました。不適切な内容と判断された可能性があります。お手数ですが、表現を変えてもう一度お試しください。]"
                elif finish_reason == 'RECITATION':
                    final_response_text = "[エラー: AIの応答が、学習元データからの長すぎる引用と判断されたため、ブロックされました。]"
                else:
                    final_response_text = "[エラー: リトライを試みましたが、AIからの有効な応答がありませんでした。APIが不安定か、プロンプトが複雑すぎる可能性があります。]"
        if not final_response.get("response"):
            final_response["response"] = final_response_text
    if not final_response:
        final_response["response"] = "[エラー: 不明な理由でエージェントの実行が完了しませんでした。]"
    yield {"final_output": final_response}

def count_input_tokens(**kwargs):
    character_name = kwargs.get("character_name")
    api_key_name = kwargs.get("api_key_name")
    api_history_limit = kwargs.get("api_history_limit")
    parts = kwargs.get("parts", [])

    api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"): return "トークン数: (APIキーエラー)"

    try:
        effective_settings = config_manager.get_effective_settings(character_name)
        # kwargsから渡された設定で上書き
        if kwargs.get("add_timestamp") is not None: effective_settings["add_timestamp"] = kwargs["add_timestamp"]
        if kwargs.get("send_thoughts") is not None: effective_settings["send_thoughts"] = kwargs["send_thoughts"]
        if kwargs.get("send_notepad") is not None: effective_settings["send_notepad"] = kwargs["send_notepad"]
        if kwargs.get("send_core_memory") is not None: effective_settings["send_core_memory"] = kwargs["send_core_memory"]
        if kwargs.get("send_scenery") is not None: effective_settings["send_scenery"] = kwargs["send_scenery"]

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
            _, _, _, _, notepad_path = get_character_files_paths(character_name)
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
        log_file, _, _, _, _ = get_character_files_paths(character_name)
        raw_history = utils.load_chat_log(log_file, character_name)
        limit = int(api_history_limit) if api_history_limit and api_history_limit.isdigit() else 0
        if limit > 0 and len(raw_history) > limit * 2:
            raw_history = raw_history[-(limit * 2):]

        for h_item in raw_history:
            content = h_item.get('content', '').strip()
            if not content: continue
            # トークン計算時は、思考ログは除去しない（APIに渡される状態を正確にシミュレートするため）
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
