# gemini_api.py (堅牢化対応版)

import traceback
from typing import Any, List, Union, Optional, Dict
import os
import json
import io
import base64
from PIL import Image
import google.genai as genai
import filetype
import httpx  # エラーハンドリングのためにインポート
from google.api_core.exceptions import ResourceExhausted

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
import config_manager
import constants
import utils
from character_manager import get_character_files_paths

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
    # (この関数の中身は変更ありません)
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
    # (この関数の中身は変更ありませんが、呼び出し元でエラーが捕捉されるようになります)
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

def invoke_nexus_agent(*args: Any) -> Dict[str, Any]: # 戻り値の型ヒントを修正
    (textbox_content, current_character_name,
     current_api_key_name_state, file_input_list,
     api_history_limit_state, debug_mode_state) = args

    from agent.graph import app
    effective_settings = config_manager.get_effective_settings(current_character_name)
    current_model_name, send_thoughts_state = effective_settings["model_name"], effective_settings["send_thoughts"]
    api_key = config_manager.GEMINI_API_KEYS.get(current_api_key_name_state)
    # ▼▼▼ 戻り値のデフォルトに "tools_used" を追加 ▼▼▼
    default_error_response = {"response": "", "location_name": "（エラー）", "scenery": "（エラー）", "tools_used": []}

    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return {**default_error_response, "response": f"[エラー: APIキー '{current_api_key_name_state}' が有効ではありません。]"}

    # ... (この間の履歴読み込みやメッセージ構築のロジックは変更なし) ...
    user_input_text = textbox_content.strip() if textbox_content else ""
    is_internal_call = user_input_text.startswith("（システム")
    if not user_input_text and not file_input_list and not is_internal_call:
         return {**default_error_response, "response": "[エラー: テキスト入力またはファイル添付がありません]"}
    messages = []
    log_file, _, _, _, _ = get_character_files_paths(current_character_name)
    raw_history = utils.load_chat_log(log_file, current_character_name)
    limit = 0
    if api_history_limit_state.isdigit():
        limit = int(api_history_limit_state)
    if limit > 0 and len(raw_history) > limit * 2: raw_history = raw_history[-(limit * 2):]
    for h_item in raw_history:
        role, content = h_item.get('role'), h_item.get('content', '').strip()
        if not content: continue
        if role in ['model', 'assistant', current_character_name]:
            final_content = content if send_thoughts_state else utils.remove_thoughts_from_text(content)
            if final_content: messages.append(AIMessage(content=final_content))
        elif role in ['user', 'human']: messages.append(HumanMessage(content=content))
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
                elif mime_type.startswith(("audio/", "video/")):
                     with open(filepath, "rb") as f: file_data = base64.b64encode(f.read()).decode("utf-8")
                     user_message_parts.append({"type": "media", "mime_type": mime_type, "data": file_data})
                else:
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
        "location_name": "（初期化中）", "scenery_text": "（初期化中）",
        "debug_mode": debug_mode_state
    }

    try:
        # ▼▼▼ forループによるリトライ機構を完全に削除 ▼▼▼
        # app.invokeは一度だけ呼び出す
        final_state = app.invoke(initial_state)

        # 応答が空だった場合のチェックはここで行う
        final_response_text = ""
        if final_state['messages'] and isinstance(final_state['messages'][-1], AIMessage):
            final_response_text = str(final_state['messages'][-1].content or "").strip()

        # もしLangChainの内部リトライが尽きて応答が空だった場合、
        # ユーザーに状況を伝えるメッセージを設定する
        if not final_response_text:
             print("--- [警告] LangChainの内部リトライが尽き、AIから有効な応答を得られませんでした。---")
             # ここでツール呼び出しがなかったことを確認してからメッセージを出す
             is_tool_call = False
             if final_state['messages'] and isinstance(final_state['messages'][-1], AIMessage):
                 if final_state['messages'][-1].tool_calls:
                     is_tool_call = True

             if not is_tool_call:
                 final_response_text = "[エラー: AIとの通信が一時的に不安定になっているようです。しばらくしてから、もう一度お試しください。]"
        # ▲▲▲ 修正ここまで ▲▲▲

        tools_used_summary = []
        for message in final_state.get('messages', []):
            if isinstance(message, AIMessage) and message.tool_calls:
                for tool_call in message.tool_calls:
                    # (このforループの中身は変更なし)
                    tool_name = tool_call.get('name', '不明なツール')
                    args = tool_call.get('args', {})
                    display_text = ""
                    if tool_name == 'set_current_location':
                        location = args.get('location_id', '不明な場所')
                        display_text = f'現在地を「{location}」に設定しました。'
                    elif tool_name == 'set_timer':
                        duration = str(args.get('duration_minutes', '?')).split('.')[0]
                        display_text = f"タイマーをセットしました（{duration}分）"
                    elif tool_name == 'set_pomodoro_timer':
                        work = str(args.get('work_minutes', '?')).split('.')[0]
                        brk = str(args.get('break_minutes', '?')).split('.')[0]
                        cycles = str(args.get('cycles', '?')).split('.')[0]
                        display_text = f"ポモドーロタイマーをセットしました（{work}分・{brk}分・{cycles}セット）"
                    elif tool_name == 'web_search_tool':
                        query = args.get('query', '...')
                        display_text = f'Webで「{query}」を検索しました。'
                    elif tool_name == 'add_to_notepad':
                        entry = args.get('entry', '...')
                        display_text = f'メモ帳に「{entry[:30]}...」を追加しました。'
                    elif tool_name == 'update_notepad':
                        new_entry = args.get('new_entry', '...')
                        display_text = f'メモ帳を「{new_entry[:30]}...」に更新しました。'
                    elif tool_name == 'delete_from_notepad':
                        entry = args.get('entry_to_delete', '...')
                        display_text = f'メモ帳から「{entry[:30]}...」を削除しました。'
                    elif tool_name == 'generate_image':
                        display_text = '新しい画像を生成しました。'
                    else:
                        args_to_display = {k: v for k, v in args.items() if k not in ['character_name', 'api_key', 'tavily_api_key']}
                        if args_to_display:
                            args_str = ", ".join([f"{k}='{str(v)[:20]}...'" for k, v in args_to_display.items()])
                            display_text = f'{tool_name} を実行しました ({args_str})'
                        else:
                            display_text = f'{tool_name} を実行しました。'
                    tools_used_summary.append(f"🛠️ {display_text}")

        location_name = final_state.get('location_name', '（場所不明）')
        scenery_text = final_state.get('scenery_text', '（情景不明）')
        return {"response": final_response_text, "location_name": location_name, "scenery": scenery_text, "tools_used": tools_used_summary}

    except ResourceExhausted as e:
        if "PerDay" in str(e):
            print("--- [APIエラー検知] 1日のリクエスト上限に達しました ---")
            error_message = "[APIエラー: 無料利用枠の1日あたりのリクエスト上限に達しました。]"
            return {**default_error_response, "response": error_message}
        else:
            # LangChainの内部リトライが尽きた最終的な例外
            print(f"--- [APIエラー検知] リソース上限エラー（リトライ最終失敗）: {e} ---")
            error_message = "[APIエラー: AIとの通信が一時的に混み合っているようです。しばらくしてから、もう一度お試しください。]"
            return {**default_error_response, "response": error_message}
    except Exception as e:
        traceback.print_exc()
        return {**default_error_response, "response": f"[エージェント実行エラー: {e}]"}

def count_input_tokens(**kwargs):
    character_name = kwargs.get("character_name")
    api_key_name = kwargs.get("api_key_name")
    api_history_limit = kwargs.get("api_history_limit") # 新しい引数を受け取る
    parts = kwargs.get("parts", [])

    api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"): return "トークン数: (APIキーエラー)"

    try:
        effective_settings = config_manager.get_effective_settings(character_name)
        if kwargs.get("add_timestamp") is not None: effective_settings["add_timestamp"] = kwargs["add_timestamp"]
        if kwargs.get("send_thoughts") is not None: effective_settings["send_thoughts"] = kwargs["send_thoughts"]
        if kwargs.get("send_notepad") is not None: effective_settings["send_notepad"] = kwargs["send_notepad"]
        if kwargs.get("send_core_memory") is not None: effective_settings["send_core_memory"] = kwargs["send_core_memory"]
        if kwargs.get("send_scenery") is not None: effective_settings["send_scenery"] = kwargs["send_scenery"]

        model_name = effective_settings.get("model_name") or config_manager.DEFAULT_MODEL_GLOBAL
        messages: List[Union[SystemMessage, HumanMessage, AIMessage]] = []

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

        log_file, _, _, _, _ = get_character_files_paths(character_name)
        raw_history = utils.load_chat_log(log_file, character_name)

        limit = 0
        if api_history_limit and api_history_limit.isdigit():
            limit = int(api_history_limit)

        if limit > 0 and len(raw_history) > limit * 2:
            raw_history = raw_history[-(limit * 2):]

        for h_item in raw_history:
            role, content = h_item.get('role'), h_item.get('content', '').strip()
            if not content: continue
            if role in ['model', 'assistant', character_name]:
                final_content = content if effective_settings.get("send_thoughts", True) else utils.remove_thoughts_from_text(content)
                if final_content: messages.append(AIMessage(content=final_content))
            elif role in ['user', 'human']: messages.append(HumanMessage(content=content))

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

        total_tokens = count_tokens_from_lc_messages(messages, model_name, api_key)
        if total_tokens == -1: return "トークン数: (計算エラー)"

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
