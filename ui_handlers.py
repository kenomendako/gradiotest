# ui_handlers.py の完全修正版

import pandas as pd
from typing import List, Optional, Dict, Any, Tuple, Union
import gradio as gr
import datetime
import json
import traceback
import os
import shutil
import re
from PIL import Image
import base64
from langchain_core.messages import AIMessage, SystemMessage
import threading

# --- Nexus Ark モジュールのインポート ---
import gemini_api
import mem0_manager
import rag_manager
import config_manager
import alarm_manager
import character_manager
import utils # ★★★ utilsを直接インポート ★★★
from tools import memory_tools
from timers import UnifiedTimer
from character_manager import get_character_files_paths
from memory_manager import load_memory_data_safe, save_memory_data

# ★★★ utilsからの個別インポートは不要になるか、あるいは以下のように明示的に行う ★★★
# from utils import (
#     load_chat_log,
#     format_history_for_gradio,
#     save_message_to_log,
#     _get_user_header_from_log,
#     save_log_file
# )

def handle_message_submission(*args: Any):
    (textbox_content, chatbot_history, current_character_name, current_model_name,
     current_api_key_name_state, file_input_list, add_timestamp_checkbox,
     send_thoughts_state, api_history_limit_state,
     send_notepad_state, use_common_prompt_state) = args

    user_prompt_from_textbox = textbox_content.strip() if textbox_content else ""

    if not user_prompt_from_textbox and not file_input_list:
        token_count = update_token_count(None, None, current_character_name, current_model_name, current_api_key_name_state, api_history_limit_state, send_notepad_state, "", use_common_prompt_state)
        yield chatbot_history, gr.update(), gr.update(), token_count
        return

    timestamp = f"\n\n{datetime.datetime.now().strftime('%Y-%m-%d (%a) %H:%M:%S')}" if add_timestamp_checkbox else ""

    log_message_parts = []

    if user_prompt_from_textbox:
        processed_text = user_prompt_from_textbox + timestamp
        log_message_parts.append(processed_text)
        chatbot_history.append({"role": "user", "content": user_prompt_from_textbox})

    if file_input_list:
        for file_obj in file_input_list:
            filepath = file_obj.name
            filename = os.path.basename(filepath)
            log_message_parts.append(f"[ファイル添付: {filepath}]")
            chatbot_history.append({"role": "user", "content": (filepath, filename)})

    final_log_message = "\n\n".join(log_message_parts).strip()

    chatbot_history.append({"role": "assistant", "content": "思考中... ▌"})

    token_count = update_token_count(None, None, current_character_name, current_model_name, current_api_key_name_state, api_history_limit_state, send_notepad_state, "", use_common_prompt_state)
    yield chatbot_history, gr.update(value=""), gr.update(value=None), token_count

    final_response_text = ""
    try:
        args_list = list(args)
        final_response_text = gemini_api.invoke_nexus_agent(*args_list)
    except Exception as e:
        traceback.print_exc()
        final_response_text = f"[UIハンドラエラー: {e}]"

    log_f, _, _, _, _ = get_character_files_paths(current_character_name)
    if final_log_message:
        user_header = utils._get_user_header_from_log(log_f, current_character_name) # ★★★ utils. を追記 ★★★
        utils.save_message_to_log(log_f, user_header, final_log_message) # ★★★ utils. を追記 ★★★
        if final_response_text:
            utils.save_message_to_log(log_f, f"## {current_character_name}:", final_response_text) # ★★★ utils. を追記 ★★★

    chatbot_history.pop()

    image_tag_pattern = re.compile(r"\[Generated Image: (.*?)\]")
    image_match = image_tag_pattern.search(final_response_text)
    if image_match:
        text_before_image = final_response_text[:image_match.start()].strip()
        image_path = image_match.group(1).strip()
        text_after_image = final_response_text[image_match.end():].strip()
        if text_before_image:
            chatbot_history.append({"role": "assistant", "content": utils.format_response_for_display(text_before_image)})
        absolute_image_path = os.path.abspath(image_path)
        if os.path.exists(absolute_image_path):
            chatbot_history.append({"role": "assistant", "content": (absolute_image_path, os.path.basename(image_path))})
        else:
            chatbot_history.append({"role": "assistant", "content": f"*[表示エラー: 画像 '{os.path.basename(image_path)}' が見つかりません]*"})
        if text_after_image:
            chatbot_history.append({"role": "assistant", "content": utils.format_response_for_display(text_after_image)})
    else:
        chatbot_history.append({"role": "assistant", "content": utils.format_response_for_display(final_response_text)})

    token_count = update_token_count(None, None, current_character_name, current_model_name, current_api_key_name_state, api_history_limit_state, send_notepad_state, "", use_common_prompt_state)
    yield chatbot_history, gr.update(), gr.update(value=None), token_count

def handle_add_new_character(character_name: str):
    if not character_name or not character_name.strip():
        gr.Warning("キャラクター名が入力されていません。")
        char_list = character_manager.get_character_list()
        return gr.update(choices=char_list), gr.update(choices=char_list), gr.update(choices=char_list), gr.update(value="")
    safe_name = re.sub(r'[\\/*?:"<>|]', "", character_name).strip()
    if not safe_name:
        gr.Warning("無効なキャラクター名です。")
        char_list = character_manager.get_character_list()
        return gr.update(choices=char_list), gr.update(choices=char_list), gr.update(choices=char_list), gr.update(value="")
    if character_manager.ensure_character_files(safe_name):
        gr.Info(f"新しいキャラクター「{safe_name}」さんを迎えました！")
        new_char_list = character_manager.get_character_list()
        return gr.update(choices=new_char_list, value=safe_name), gr.update(choices=new_char_list, value=safe_name), gr.update(choices=new_char_list, value=safe_name), gr.update(value="")
    else:
        gr.Error(f"キャラクター「{safe_name}」の準備に失敗しました。")
        char_list = character_manager.get_character_list()
        return gr.update(choices=char_list), gr.update(choices=char_list), gr.update(choices=char_list), gr.update(value=character_name)

def _get_display_history_count(api_history_limit_value: str) -> int:
    return int(api_history_limit_value) if api_history_limit_value.isdigit() else config_manager.UI_HISTORY_MAX_LIMIT

def update_ui_on_character_change(character_name: Optional[str], api_history_limit_value: str):
    if not character_name:
        all_chars = character_manager.get_character_list()
        character_name = all_chars[0] if all_chars else "Default"
        if not os.path.exists(os.path.join(config_manager.CHARACTERS_DIR, character_name)): character_manager.ensure_character_files(character_name)
    config_manager.save_config("last_character", character_name)
    log_f, _, img_p, mem_p, notepad_p = get_character_files_paths(character_name)
    display_turns = _get_display_history_count(api_history_limit_value)
    chat_history = utils.format_history_for_gradio(utils.load_chat_log(log_f, character_name)[-(display_turns * 2):]) if log_f and os.path.exists(log_f) else [] # ★★★
    log_content = ""
    if log_f and os.path.exists(log_f):
        try:
            with open(log_f, "r", encoding="utf-8") as f: log_content = f.read()
        except Exception as e: log_content = f"ログ読込エラー: {e}"
    memory_str = json.dumps(load_memory_data_safe(mem_p), indent=2, ensure_ascii=False)
    profile_image = img_p if img_p and os.path.exists(img_p) else None
    notepad_content = load_notepad_content(character_name)
    return character_name, chat_history, "", profile_image, memory_str, character_name, log_content, character_name, notepad_content

def handle_save_memory_click(character_name, json_string_data):
    if not character_name: gr.Warning("キャラクターが選択されていません。"); return gr.update()
    try:
        update_action = save_memory_data(character_name, json_string_data)
        gr.Info("記憶を保存しました。")
        return update_action
    except json.JSONDecodeError: gr.Error("記憶データのJSON形式が正しくありません。"); return gr.update()
    except Exception as e: gr.Error(f"記憶の保存中にエラーが発生しました: {e}"); return gr.update()

DAY_MAP_EN_TO_JA = {"mon": "月", "tue": "火", "wed": "水", "thu": "木", "fri": "金", "sat": "土", "sun": "日"}

def render_alarms_as_dataframe():
    alarms = sorted(alarm_manager.get_all_alarms(), key=lambda x: x.get("time", ""))
    display_data = [{"ID": a.get("id"), "状態": a.get("enabled", False), "時刻": a.get("time"), "曜日": ",".join([DAY_MAP_EN_TO_JA.get(d, d.upper()) for d in a.get('days', [])]), "キャラ": a.get("character"), "テーマ": a.get("theme")} for a in alarms]
    return pd.DataFrame(display_data, columns=["ID", "状態", "時刻", "曜日", "キャラ", "テーマ"])

def get_display_df(df_with_id: pd.DataFrame):
    if df_with_id is None or df_with_id.empty or 'ID' not in df_with_id.columns:
        return pd.DataFrame(columns=["状態", "時刻", "曜日", "キャラ", "テーマ"])
    return df_with_id[["状態", "時刻", "曜日", "キャラ", "テーマ"]]

def handle_alarm_selection(evt: gr.SelectData, df_with_id: pd.DataFrame) -> List[str]:
    if evt.index is None or df_with_id is None or df_with_id.empty: return []
    indices = [evt.index] if isinstance(evt.index, int) else evt.index if isinstance(evt.index, list) else []
    return [str(df_with_id.iloc[i]['ID']) for i in indices if 0 <= i < len(df_with_id)]

def handle_alarm_selection_and_feedback(evt: gr.SelectData, df_with_id: pd.DataFrame):
    selected_ids = handle_alarm_selection(evt, df_with_id)
    count = len(selected_ids)
    feedback_text = "アラームを選択してください" if count == 0 else f"{count} 件のアラームを選択中"
    return selected_ids, feedback_text

def toggle_selected_alarms_status(selected_ids: list, target_status: bool):
    if not selected_ids:
        gr.Warning("状態を変更するアラームが選択されていません。")
    else:
        changed_count = 0
        status_text = "有効" if target_status else "無効"
        for alarm_id in selected_ids:
            alarm = alarm_manager.get_alarm_by_id(alarm_id)
            if alarm and alarm.get("enabled") != target_status:
                if alarm_manager.toggle_alarm_enabled(alarm_id): changed_count += 1
        if changed_count > 0: gr.Info(f"{changed_count}件のアラームを「{status_text}」に変更しました。")
    return render_alarms_as_dataframe()

def handle_delete_selected_alarms(selected_ids: list):
    if not selected_ids:
        gr.Warning("削除するアラームが選択されていません。")
    else:
        deleted_count = sum(1 for sid in selected_ids if alarm_manager.delete_alarm(str(sid)))
        if deleted_count > 0: gr.Info(f"{deleted_count}件のアラームを削除しました。")
    return render_alarms_as_dataframe()

def handle_timer_submission(timer_type, duration, work, brk, cycles, char, work_theme, brk_theme, api_key, webhook, normal_theme):
    if not char or not api_key: return "エラー：キャラクターとAPIキーを選択してください。"
    try:
        timer = UnifiedTimer(timer_type, float(duration or 0), float(work or 0), float(brk or 0), int(cycles or 0), char, work_theme, brk_theme, api_key, webhook, normal_theme)
        timer.start()
        gr.Info(f"{timer_type}を開始しました。")
        return f"{timer_type}を開始しました。"
    except Exception as e: return f"タイマー開始エラー: {e}"

def update_model_state(model): config_manager.save_config("last_model", model); return model
def update_api_key_state(api_key_name): config_manager.save_config("last_api_key_name", api_key_name); gr.Info(f"APIキーを '{api_key_name}' に設定しました。"); return api_key_name
def update_timestamp_state(checked): config_manager.save_config("add_timestamp", bool(checked))
def update_send_thoughts_state(checked): config_manager.save_config("last_send_thoughts_to_api", bool(checked)); return bool(checked)

def update_api_history_limit_state_and_reload_chat(limit_ui_val: str, character_name: Optional[str]):
    key = next((k for k, v in config_manager.API_HISTORY_LIMIT_OPTIONS.items() if v == limit_ui_val), "all")
    config_manager.save_config("last_api_history_limit_option", key)
    chat_history, log_content = reload_chat_log(character_name, key)
    return key, chat_history, log_content

def reload_chat_log(character_name: Optional[str], api_history_limit_value: str):
    if not character_name: return [], "キャラクター未選択"
    log_f,_,_,_,_ = get_character_files_paths(character_name)
    if not log_f or not os.path.exists(log_f): return [], "ログファイルなし"
    display_turns = _get_display_history_count(api_history_limit_value)
    history = utils.format_history_for_gradio(utils.load_chat_log(log_f, character_name)[-(display_turns*2):]) # ★★★
    content = ""
    with open(log_f, "r", encoding="utf-8") as f: content = f.read()
    return history, content

def handle_save_log_button_click(character_name, log_content):
    if character_name:
        utils.save_log_file(character_name, log_content) # ★★★
        gr.Info(f"'{character_name}'のログを保存しました。")
    else: gr.Error("キャラクターが選択されていません。")

def load_alarm_to_form(selected_ids: list):
    default_char = character_manager.get_character_list()[0] if character_manager.get_character_list() else "Default"
    if not selected_ids or len(selected_ids) != 1: return "アラーム追加", "", "", default_char, list(DAY_MAP_EN_TO_JA.values()), "08", "00", None
    alarm = alarm_manager.get_alarm_by_id(selected_ids[0])
    if not alarm:
        gr.Warning(f"アラームID '{selected_ids[0]}' が見つかりません。")
        return "アラーム追加", "", "", default_char, list(DAY_MAP_EN_TO_JA.values()), "08", "00", None
    h, m = alarm.get("time", "08:00").split(":")
    days_ja = [DAY_MAP_EN_TO_JA.get(d.lower(), d.upper()) for d in alarm.get("days", [])]
    return f"アラーム更新", alarm.get("theme", ""), alarm.get("flash_prompt_template", ""), alarm.get("character", default_char), days_ja, h, m, selected_ids[0]

def handle_add_or_update_alarm(editing_id, h, m, char, theme, prompt, days):
    default_char = character_manager.get_character_list()[0] if character_manager.get_character_list() else "Default"
    if not char: gr.Warning("キャラクターが選択されていません。"); df = render_alarms_as_dataframe(); return df, df, "アラーム更新" if editing_id else "アラーム追加", theme, prompt, char, days, h, m, editing_id
    success = False
    if editing_id:
        pass
    else:
        if alarm_manager.add_alarm(h, m, char, theme, prompt, days): gr.Info("新しいアラームを追加しました。"); success = True
        else: gr.Warning("新しいアラームの追加に失敗しました。")
    if success:
        df = render_alarms_as_dataframe()
        return df, df, "アラーム追加", "", "", default_char, list(DAY_MAP_EN_TO_JA.values()), "08", "00", None
    df = render_alarms_as_dataframe()
    return df, df, "アラーム更新" if editing_id else "アラーム追加", theme, prompt, char, days, h, m, editing_id

def handle_rag_update_button_click(character_name: str, api_key_name: str):
    if not character_name or not api_key_name: gr.Warning("キャラクターとAPIキーを選択してください。"); return
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"): gr.Warning(f"APIキー '{api_key_name}' が有効ではありません。"); return
    gr.Info(f"「{character_name}」のRAG索引の更新を開始します...")
    threading.Thread(target=lambda: rag_manager.create_or_update_index(character_name, api_key)).start()

def update_send_notepad_state(checked: bool): return checked
def update_use_common_prompt_state(checked: bool): return checked

def load_notepad_content(character_name: str) -> str:
    if not character_name: return ""
    _, _, _, _, notepad_path = get_character_files_paths(character_name)
    if notepad_path and os.path.exists(notepad_path):
        with open(notepad_path, "r", encoding="utf-8") as f: return f.read()
    return ""

def handle_save_notepad_click(character_name: str, content: str) -> str:
    if not character_name: gr.Warning("キャラクターが選択されていません。"); return content
    _, _, _, _, notepad_path = character_manager.get_character_files_paths(character_name)
    if not notepad_path: gr.Error(f"「{character_name}」のメモ帳パス取得失敗。"); return content
    lines = [f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}] {line.strip()}" if not re.match(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\]", line.strip()) else line.strip() for line in content.strip().split('\n') if line.strip()]
    final_content = "\n".join(lines)
    try:
        with open(notepad_path, "w", encoding="utf-8") as f: f.write(final_content + ('\n' if final_content else ''))
        gr.Info(f"「{character_name}」のメモ帳を保存しました。")
        return final_content
    except Exception as e: gr.Error(f"メモ帳の保存エラー: {e}"); traceback.print_exc(); return content

def handle_clear_notepad_click(character_name: str) -> str:
    if not character_name: gr.Warning("キャラクターが選択されていません。"); return ""
    _, _, _, _, notepad_path = character_manager.get_character_files_paths(character_name)
    if not notepad_path: gr.Error(f"「{character_name}」のメモ帳パス取得失敗。"); return ""
    try:
        with open(notepad_path, "w", encoding="utf-8") as f: f.write("")
        gr.Info(f"「{character_name}」のメモ帳を空にしました。")
        return ""
    except Exception as e: gr.Error(f"メモ帳クリアエラー: {e}"); traceback.print_exc(); return f"エラー: {e}"

def handle_reload_notepad(character_name: str) -> str:
    if not character_name: gr.Warning("キャラクターが選択されていません。"); return ""
    content = load_notepad_content(character_name)
    gr.Info(f"「{character_name}」のメモ帳を再読み込みしました。")
    return content

def _run_core_memory_update(character_name: str, api_key: str):
    print(f"--- [スレッド開始] コアメモリ更新処理を開始します (Character: {character_name}) ---")
    try:
        result = memory_tools.summarize_and_save_core_memory.func(character_name=character_name, api_key=api_key)
        print(f"--- [スレッド終了] コアメモリ更新処理完了 --- 結果: {result}")
    except Exception as e: print(f"--- [スレッドエラー] コアメモリ更新中に予期せぬエラー ---"); traceback.print_exc()

def handle_core_memory_update_click(character_name: str, api_key_name: str):
    if not character_name or not api_key_name: gr.Warning("キャラクターとAPIキーを選択してください。"); return
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"): gr.Warning(f"APIキー '{api_key_name}' が有効ではありません。"); return
    gr.Info(f"「{character_name}」のコアメモリ更新をバックグラウンドで開始しました。")
    threading.Thread(target=_run_core_memory_update, args=(character_name, api_key)).start()

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
    if not all([current_character_name, current_model_name, current_api_key_name_state]):
        return "入力トークン数 (設定不足)"
    parts_for_api = []
    if textbox_content: parts_for_api.append(textbox_content)
    if file_input_list:
        for file_wrapper in file_input_list:
            if not file_wrapper: continue
            try: parts_for_api.append(Image.open(file_wrapper.name))
            except Exception:
                try:
                    with open(file_wrapper.name, 'r', encoding='utf-8') as f: parts_for_api.append(f.read())
                except Exception as text_e: print(f"トークン計算ファイル読込エラー: {text_e}")
    api_key = config_manager.API_KEYS.get(current_api_key_name_state)
    limits = gemini_api.get_model_token_limits(current_model_name, api_key)
    limit_str = f" / {limits['input']:,}" if limits and 'input' in limits else ""
    basic_tokens = gemini_api.count_input_tokens(character_name=current_character_name, model_name=current_model_name, parts=parts_for_api, api_history_limit_option=api_history_limit_state, api_key_name=current_api_key_name_state, send_notepad_to_api=False, use_common_prompt=use_common_prompt_state)
    if send_notepad_state and notepad_editor_content and notepad_editor_content.strip() and basic_tokens >= 0:
        try:
            if api_key and not api_key.startswith("YOUR_API_KEY"):
                temp_messages = [SystemMessage(content=f"\n\n---\n【現在のメモ帳の内容】\n{notepad_editor_content.strip()}\n---")]
                notepad_tokens = gemini_api.count_tokens_from_lc_messages(temp_messages, current_model_name, api_key)
                if notepad_tokens >= 0: basic_tokens += notepad_tokens
        except Exception as e: print(f"メモ帳トークン計算エラー: {e}")
    if basic_tokens >= 0: return f"**基本入力:** {basic_tokens:,}{limit_str} トークン"
    return "基本入力: (APIキー無効)" if basic_tokens == -1 else "基本入力: (計算エラー)"
