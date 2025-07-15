# ui_handlers.py (完全な修正版)

import pandas as pd
from typing import List, Optional, Dict, Any, Tuple, Union
import gradio as gr
import datetime
import utils
import json
import traceback
import os
import shutil
import re # ★★★ これが、今回追加された、ただ一つの重要な行です ★★★
from PIL import Image
import base64
from langchain_core.messages import AIMessage
from langchain_core.messages import SystemMessage
import threading

import gemini_api
import mem0_manager
import rag_manager
import config_manager
import alarm_manager
import character_manager
from tools import memory_tools
from timers import UnifiedTimer
from character_manager import get_character_files_paths
from gemini_api import send_multimodal_to_gemini
from memory_manager import load_memory_data_safe, save_memory_data
from utils import load_chat_log, format_history_for_gradio, save_message_to_log, _get_user_header_from_log, save_log_file

def update_token_count(
    textbox_content: Optional[str],
    file_input_list: Optional[List[Any]],
    current_character_name: str,
    current_model_name: str,
    current_api_key_name_state: str,
    api_history_limit_state: str,
    send_notepad_state: bool,
    notepad_editor_content: str,
    use_common_prompt_state: bool
) -> str:
    """【改訂】基本入力トークン数を、モデルの上限と共に表示する"""
    if not all([current_character_name, current_model_name, current_api_key_name_state]):
        return "入力トークン数 (設定不足)"

    parts_for_api = []
    if textbox_content:
        parts_for_api.append(textbox_content)

    if file_input_list:
        for file_wrapper in file_input_list:
            if not file_wrapper:
                continue
            file_path = file_wrapper.name
            try:
                img = Image.open(file_path)
                parts_for_api.append(img)
            except Exception:
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        parts_for_api.append(f.read())
                except Exception as text_e:
                    print(f"トークン計算のためのファイル読み込みに失敗: {file_path}, Error: {text_e}")

    api_key = config_manager.API_KEYS.get(current_api_key_name_state)
    limits = gemini_api.get_model_token_limits(current_model_name, api_key)
    limit_str = f" / {limits['input']:,}" if limits and 'input' in limits else ""

    basic_tokens = gemini_api.count_input_tokens(
        character_name=current_character_name,
        model_name=current_model_name,
        parts=parts_for_api,
        api_history_limit_option=api_history_limit_state,
        api_key_name=current_api_key_name_state,
        send_notepad_to_api=False,
        use_common_prompt=use_common_prompt_state
    )

    if send_notepad_state and notepad_editor_content and notepad_editor_content.strip() and basic_tokens >= 0:
        try:
            api_key = config_manager.API_KEYS.get(current_api_key_name_state)
            if api_key and not api_key.startswith("YOUR_API_KEY"):
                notepad_prompt_segment = f"\n\n---\n【現在のメモ帳の内容】\n{notepad_editor_content.strip()}\n---"
                temp_messages_for_notepad_count = [SystemMessage(content=notepad_prompt_segment)]
                notepad_tokens = gemini_api.count_tokens_from_lc_messages(
                    temp_messages_for_notepad_count,
                    current_model_name,
                    api_key
                )
                if notepad_tokens >= 0:
                    basic_tokens += notepad_tokens
                else:
                    print(f"警告: メモ帳部分のトークン数計算に失敗しました。({notepad_tokens})")
            else:
                 print(f"警告: APIキーが無効なため、メモ帳部分のトークン数を計算できません。")
        except Exception as e:
            print(f"メモ帳のトークン数計算中に予期せぬエラー: {e}")
            traceback.print_exc()

    if basic_tokens >= 0:
        return f"**基本入力:** {basic_tokens:,}{limit_str} トークン"
    elif basic_tokens == -1:
        return "基本入力: (APIキー無効)"
    else:
        return "基本入力: (計算エラー)"

def handle_message_submission(*args: Any) -> Tuple[List[Dict[str, Union[str, tuple, None]]], gr.update, gr.update, str]:
    (textbox_content, chatbot_history, current_character_name, current_model_name,
     current_api_key_name_state, file_input_list, add_timestamp_checkbox,
     send_thoughts_state, api_history_limit_state,
     send_notepad_state,
     use_common_prompt_state
    ) = args

    log_f, _, _, _, _ = get_character_files_paths(current_character_name)
    user_prompt_from_textbox = textbox_content.strip() if textbox_content else ""
    parts_for_api = []
    attached_filenames_for_log = []

    if user_prompt_from_textbox:
        parts_for_api.append(user_prompt_from_textbox)
        urls = re.findall(r'(https?://\S+)', user_prompt_from_textbox)
        if urls:
            gr.Info(f"メッセージ内のURLを検出しました: {', '.join(urls)}")

    if file_input_list:
        for file_wrapper in file_input_list:
            if not file_wrapper: continue
            actual_file_path = file_wrapper.name
            original_filename = os.path.basename(actual_file_path)
            attached_filenames_for_log.append(original_filename)
            try:
                img = Image.open(actual_file_path)
                parts_for_api.append(img)
                print(f"  - '{original_filename}' を画像として正常に処理。")
            except Exception:
                try:
                    with open(actual_file_path, 'r', encoding='utf-8') as f:
                        file_content = f.read()
                    parts_for_api.append(file_content)
                    print(f"  - '{original_filename}' をテキストとして正常に処理。")
                except Exception as e2:
                    print(f"警告: ファイル '{original_filename}' の処理中にエラー: {e2}")

    if not parts_for_api:
        # notepad_editor の現在の内容を取得するロジックが必要だが、引数にないため空文字で代用
        token_display_on_error = update_token_count(None, None, current_character_name, current_model_name, current_api_key_name_state, api_history_limit_state, send_notepad_state, "", use_common_prompt_state)
        return chatbot_history, gr.update(), gr.update(value=None), token_display_on_error

    log_message_content = user_prompt_from_textbox
    if attached_filenames_for_log:
        log_message_content += "\n[ファイル添付: " + ", ".join(attached_filenames_for_log) + "]"
    timestamp = f"\n{datetime.datetime.now().strftime('%Y-%m-%d (%a) %H:%M:%S')}" if add_timestamp_checkbox else ""
    api_response_text = ""
    final_agent_state: Dict[str, Any] = {}

    # ★★★ ここからが try...except ブロック ★★★
    try:
        api_key = config_manager.API_KEYS.get(current_api_key_name_state)
        if not api_key or api_key.startswith("YOUR_API_KEY"):
            gr.Warning(f"APIキー '{current_api_key_name_state}' が有効ではありません。")
            # notepad_editor の現在の内容を取得するロジックが必要だが、引数にないため空文字で代用
            token_display_on_error = update_token_count(textbox_content, file_input_list, current_character_name, current_model_name, current_api_key_name_state, api_history_limit_state, send_notepad_state, "", use_common_prompt_state)
            return chatbot_history, gr.update(), gr.update(value=None), token_display_on_error

        os.environ['GOOGLE_API_KEY'] = api_key
        final_agent_state = gemini_api.invoke_nexus_agent(
            character_name=current_character_name,
            model_name=current_model_name,
            parts=parts_for_api,
            api_history_limit_option=api_history_limit_state,
            api_key_name=current_api_key_name_state,
            send_notepad_to_api=send_notepad_state,
            use_common_prompt=use_common_prompt_state
        )

        if final_agent_state.get("error"):
            api_response_text = f"[エラー: {final_agent_state['error']}]"
        elif final_agent_state and final_agent_state.get('messages'):
            last_message = final_agent_state['messages'][-1]
            if isinstance(last_message, AIMessage):
                content = last_message.content
                if isinstance(content, list):
                    text_parts = [part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"]
                    api_response_text = "\n".join(text_parts)
                elif isinstance(content, str):
                    api_response_text = content
                else:
                    api_response_text = str(content)
            else:
                api_response_text = str(last_message.content if hasattr(last_message, 'content') else last_message)

        # ★★★ 新しいツールコード実行ロジック（tryブロック内）★★★
        tool_code_match = re.search(r"<tool_code>(.*?)</tool_code>", api_response_text, re.DOTALL)
        tool_output_for_log = ""
        if tool_code_match:
            code_to_run = tool_code_match.group(1).strip()
            print(f"--- 検出されたツールコードを解析・実行します ---\n{code_to_run}\n------------------------------------")

            from tools.space_tools import set_current_location, find_location_id_by_name
            from tools.memory_tools import edit_memory
            available_tools = {
                "set_current_location": set_current_location,
                "find_location_id_by_name": find_location_id_by_name,
                "edit_memory": edit_memory
            }

            call_match = re.search(r"(\w+)\((.*)\)", code_to_run)
            if call_match:
                tool_name = call_match.group(1).strip()
                args_str = call_match.group(2).strip()
                if tool_name in available_tools:
                    try:
                        tool_args = {}
                        if args_str: # 引数がある場合のみ解析
                           # A='B', C=D のような形式に対応
                           arg_parts = re.split(r",\s*(?=\w+=)", args_str)
                           tool_args = {part.split('=', 1)[0].strip(): part.split('=', 1)[1].strip().strip("'\"") for part in arg_parts}

                        if 'character_name' not in tool_args:
                            tool_args['character_name'] = current_character_name
                        tool_to_call = available_tools[tool_name]
                        result = tool_to_call.invoke(tool_args)
                        tool_output_for_log = str(result)
                        print(f"--- ツール '{tool_name}' 実行成功。出力: {tool_output_for_log} ---")
                    except Exception as e_tool:
                        tool_output_for_log = f"【ツール実行エラー】: {e_tool}"
                        print(tool_output_for_log)
                        traceback.print_exc()
                else:
                    tool_output_for_log = f"【実行エラー】: 不明なツール '{tool_name}' です。"
            else:
                tool_output_for_log = f"【解析エラー】: 実行可能なコード形式ではありません。"

            api_response_text = re.sub(r"<tool_code>.*?</tool_code>", "", api_response_text, flags=re.DOTALL).strip()
            if tool_output_for_log:
                 api_response_text += f"\n\n*[システムログ: ツール実行結果: {tool_output_for_log}]*"
        # ★★★ 新しいロジックここまで ★★★

        final_log_message = log_message_content.strip() + timestamp
        if final_log_message.strip():
            user_header = _get_user_header_from_log(log_f, current_character_name)
            utils.save_message_to_log(log_f, user_header, final_log_message)
            if api_response_text:
                utils.save_message_to_log(log_f, f"## {current_character_name}:", api_response_text)

            try:
                if api_key and final_log_message.strip() and api_response_text and not api_response_text.startswith("[エラー"):
                    mem0_instance = mem0_manager.get_mem0_instance(current_character_name, api_key)
                    clean_api_response = re.sub(r"【Thoughts】.*?【/Thoughts】", "", api_response_text, flags=re.DOTALL).strip()
                    clean_api_response = re.sub(r"\*\[システムログ:.*?\]\*", "", clean_api_response, flags=re.DOTALL).strip()
                    conversation_to_add = [
                        {"role": "user", "content": final_log_message.strip()},
                        {"role": "assistant", "content": clean_api_response}
                    ]
                    mem0_instance.add(messages=conversation_to_add, user_id=current_character_name)
                    print(f"--- Mem0に会話を記憶しました (Character: {current_character_name}) ---")
            except Exception as mem0_e:
                print(f"Mem0への記憶中にエラーが発生しました: {mem0_e}")
                traceback.print_exc()

    except Exception as e:
        traceback.print_exc()
        gr.Error(f"メッセージ処理中に予期せぬエラーが発生しました: {e}")
        api_response_text = f"[予期せぬエラー: {e}]"

    if log_f and os.path.exists(log_f):
        new_log = load_chat_log(log_f, current_character_name)
        display_turns = _get_display_history_count(api_history_limit_state)
        new_hist = format_history_for_gradio(new_log[-(display_turns * 2):])
    else:
        new_hist = chatbot_history

    # トークン数表示を更新
    # notepad_editor の現在の内容を取得するロジックが必要だが、引数にないため空文字で代用
    final_token_str = update_token_count(None, None, current_character_name, current_model_name, current_api_key_name_state, api_history_limit_state, send_notepad_state, "", use_common_prompt_state)

    return new_hist, gr.update(value=""), gr.update(value=None), final_token_str

# ui_handlers.py に追記する handle_add_new_character 関数

def handle_add_new_character(character_name: str):
    """
    新しいキャラクター名を受け取り、ファイルを作成し、UIのドロップダウンを更新する。
    """
    if not character_name or not character_name.strip():
        gr.Warning("キャラクター名が入力されていません。")
        char_list = character_manager.get_character_list()
        # 4つのアウトプット全てにgr.update()を返す
        return gr.update(choices=char_list), gr.update(choices=char_list), gr.update(choices=char_list), gr.update(value="")

    # ファイル名として不適切な文字を削除
    safe_name = re.sub(r'[\\/*?:"<>|]', "", character_name).strip()
    if not safe_name:
        gr.Warning("無効なキャラクター名です。")
        char_list = character_manager.get_character_list()
        return gr.update(choices=char_list), gr.update(choices=char_list), gr.update(choices=char_list), gr.update(value="")

    if character_manager.ensure_character_files(safe_name):
        gr.Info(f"新しいキャラクター「{safe_name}」さんを迎えました！")
        new_char_list = character_manager.get_character_list()
        # 新しいリストで全てのドロップダウンを更新し、テキストボックスをクリア
        return (
            gr.update(choices=new_char_list, value=safe_name),
            gr.update(choices=new_char_list, value=safe_name),
            gr.update(choices=new_char_list, value=safe_name),
            gr.update(value="")
        )
    else:
        gr.Error(f"キャラクター「{safe_name}」の準備に失敗しました。")
        char_list = character_manager.get_character_list()
        # エラー時は元のテキストを維持
        return (
            gr.update(choices=char_list),
            gr.update(choices=char_list),
            gr.update(choices=char_list),
            gr.update(value=character_name)
        )
