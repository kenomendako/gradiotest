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
        # agentノードの最終状態から、最後のメッセージを取得
        agent_final_state = final_state.get("agent", {})
        last_message = next(reversed(agent_final_state.get("messages", [])), None)

        final_response_text = ""
        if isinstance(last_message, AIMessage):
            final_response_text = str(last_message.content or "").strip()

            # ▼▼▼ ここからが修正の核心 ▼▼▼
            # 応答が空で、ツール呼び出しもない場合、その理由を調査する
            if not final_response_text and not last_message.tool_calls:
                finish_reason = ""
                # response_metadataから終了理由を取得
                if hasattr(last_message, 'response_metadata') and isinstance(last_message.response_metadata, dict):
                    finish_reason = last_message.response_metadata.get('finish_reason', '')

                if finish_reason == 'SAFETY':
                    print("--- [警告] AIの応答が安全フィルターによってブロックされました ---")
                    final_response_text = "[エラー: AIの応答が安全フィルターによってブロックされました。不適切な内容と判断された可能性があります。お手数ですが、表現を変えてもう一度お試しください。]"
                elif finish_reason == 'RECITATION':
                     print("--- [警告] AIの応答が引用フィルターによってブロックされました ---")
                     final_response_text = "[エラー: AIの応答が、学習元データからの長すぎる引用と判断されたため、ブロックされました。]"
                else:
                    print(f"--- [警告] AIが空の応答を返しました (終了理由: {finish_reason or '不明'}) ---")
                    final_response_text = "[エラー: AIが予期せず空の応答を返しました。通信が不安定か、AIが応答を生成できなかった可能性があります。]"
            # ▲▲▲ 修正ここまで ▲▲▲

        else: # last_message が AIMessage でない場合 (通常は起こらない)
             final_response_text = final_state.get("response", "[エラー: AIから予期せぬ形式の応答がありました。]")

        final_response["response"] = final_response_text
        final_response["location_name"] = final_state.get("context_generator", {}).get("location_name", "（不明）")
        final_response["scenery"] = final_state.get("context_generator", {}).get("scenery_text", "（不明）")

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
