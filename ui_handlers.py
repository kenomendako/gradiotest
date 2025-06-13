# -*- coding: utf-8 -*-
import pandas as pd
from typing import List, Optional, Dict, Any, Tuple, Union
import gradio as gr
import datetime
import utils
import json
import traceback
import os
import shutil
import re
# --- モジュールインポート ---
import config_manager
import alarm_manager
from timers import UnifiedTimer
from character_manager import get_character_files_paths
from gemini_api import configure_google_api, send_to_gemini, generate_image_with_gemini
from memory_manager import load_memory_data_safe, save_memory_data
from utils import load_chat_log, format_history_for_gradio, save_message_to_log, _get_user_header_from_log, save_log_file

# --- Dataframe表示用データ整形関数 ---
DAY_MAP_EN_TO_JA = {"mon": "月", "tue": "火", "wed": "水", "thu": "木", "fri": "金", "sat": "土", "sun": "日"}

def render_alarms_as_dataframe():
    """アラームデータを取得し、GradioのDataframe表示用にID列も含むpandas.DataFrameを生成して返す。"""
    alarms = alarm_manager.get_all_alarms()
    display_data = []
    for alarm in sorted(alarms, key=lambda x: x.get("time", "")):
        days_ja = [DAY_MAP_EN_TO_JA.get(d, d.upper()) for d in alarm.get('days', [])]
        display_data.append({
            "ID": alarm.get("id"),
            "状態": alarm.get("enabled", False),
            "時刻": alarm.get("time"),
            "曜日": ",".join(days_ja),
            "キャラ": alarm.get("character"),
            "テーマ": alarm.get("theme")
        })
    return pd.DataFrame(display_data, columns=["ID", "状態", "時刻", "曜日", "キャラ", "テーマ"])

def get_display_df(df_with_id: pd.DataFrame):
    """ID列を非表示にした表示用のDataFrameを返す"""
    if df_with_id is None or df_with_id.empty or 'ID' not in df_with_id.columns:
        return pd.DataFrame(columns=["状態", "時刻", "曜日", "キャラ", "テーマ"])
    return df_with_id.drop(columns=['ID'])

# --- アラームDataframeイベントハンドラ ---
def handle_alarm_dataframe_change(df_after_change: pd.DataFrame, df_original_with_id: pd.DataFrame):
    # df_after_change is the display DataFrame (ID-less) from the UI component.
    # df_original_with_id is the ID-ful DataFrame from the state (alarm_dataframe_original_data).
    if df_after_change is None or df_original_with_id is None:
        return df_original_with_id # Should not happen if states are managed

    try:
        # To find changes, we compare the display data (df_after_change) with a display version of original_with_id.
        # Then, if a change in '状態' is detected for a row, we use other columns to find that row
        # in df_original_with_id to get its 'ID'.

        # Create comparable keys for rows if they don't have unique IDs in display
        # For example, combining time, days, character, theme
        key_cols = ["時刻", "曜日", "キャラ", "テーマ"] # Columns used to identify a row uniquely (excluding '状態')

        # Ensure df_after_change has all key_cols
        if not all(col in df_after_change.columns for col in key_cols):
            gr.Error("UIデータに比較用のキー列がありません。")
            return df_original_with_id # Return original ID-ful state

        # Iterate through the rows of the new display DataFrame
        for index_ui, row_ui in df_after_change.iterrows():
            # Find matching row(s) in the original ID-ful DataFrame based on key_cols
            condition = True
            for key_col in key_cols:
                condition &= (df_original_with_id[key_col] == row_ui[key_col])

            matched_original_rows = df_original_with_id[condition]

            if not matched_original_rows.empty:
                original_row_data = matched_original_rows.iloc[0] # Assume first match is the one
                alarm_id = original_row_data['ID']
                original_state = original_row_data['状態']
                new_state_ui = row_ui['状態']

                if new_state_ui != original_state:
                    alarm_manager.toggle_alarm_enabled(alarm_id)
                    gr.Info(f"アラーム「{row_ui['テーマ']}」の状態を更新しました。 (ID: {alarm_id})")
            else:
                # This might happen if a row was added/deleted and UI is not perfectly in sync,
                # or if key_cols are not sufficient for unique match.
                # For a 'change' event focused on toggling '状態', this might indicate an issue.
                print(f"Warning: No matching original alarm found for UI row: {row_ui.to_dict()}")


    except Exception as e:
        print(f"Dataframe変更処理中にエラー: {e}\n{traceback.format_exc()}")
        gr.Error("アラーム状態の更新中にエラーが発生しました。")

    return render_alarms_as_dataframe() # Return fresh ID-ful DataFrame for the state

def handle_alarm_selection(evt: gr.SelectData, df_with_id: pd.DataFrame):
    # df_with_id is alarm_dataframe_original_data (ID-ful)
    if evt.indices is None or df_with_id is None or df_with_id.empty: return []
    selected_ids = []
    # evt.indices is a list of tuples (row_index, col_index) for each selected cell.
    # We need unique row indices relative to df_with_id (which should match the display order at selection time)
    selected_row_indices = sorted(list(set([index[0] for index in evt.indices])))
    for row_index in selected_row_indices:
        if 0 <= row_index < len(df_with_id): # Check bounds against the ID-ful dataframe
            selected_ids.append(str(df_with_id.iloc[row_index]['ID']))
    return selected_ids

def handle_delete_selected_alarms(selected_ids: list):
    if not selected_ids:
        gr.Warning("削除するアラームが選択されていません。")
    else:
        deleted_count = 0
        for alarm_id_str in selected_ids:
            if alarm_manager.delete_alarm(str(alarm_id_str)): # Ensure ID is string
                deleted_count +=1
        if deleted_count > 0: gr.Info(f"{deleted_count}件のアラームを削除しました。")
        else: gr.Warning("選択されたアラームを削除できませんでした。")
    return render_alarms_as_dataframe() # Return fresh ID-ful DataFrame

# --- タイマーイベントハンドラ ---
def handle_timer_submission(timer_type, duration, work_duration, break_duration, cycles, character_name, work_theme, break_theme, api_key_name, webhook_url, normal_timer_theme):
    if not character_name or not api_key_name:
        gr.Error("キャラクターとAPIキーを選択してください。"); return "設定エラー"
    try:
        status_message = ""
        if timer_type == "通常タイマー":
            if not (duration and float(duration) > 0):
                gr.Error("通常タイマーの時間を正しく入力してください。"); return "設定エラー"
            status_message = f"{duration}分の通常タイマーを開始しました。"
        elif timer_type == "ポモドーロタイマー":
            if not (work_duration and float(work_duration) > 0 and
                    break_duration and float(break_duration) > 0 and
                    cycles and int(cycles) > 0):
                gr.Error("ポモドーロの各項目を正しく入力してください。"); return "設定エラー"
            status_message = f"{work_duration}分作業/{break_duration}分休憩のポモドーロタイマーを開始。"
        else:
            gr.Error("不明なタイマータイプです。"); return "設定エラー" # Should not happen

        unified_timer = UnifiedTimer(timer_type, float(duration or 0), float(work_duration or 0), float(break_duration or 0), int(cycles or 0), character_name, work_theme, break_theme, api_key_name, webhook_url, normal_timer_theme)
        unified_timer.start()
        gr.Info(f"{timer_type}を開始しました。"); return status_message
    except ValueError as ve:
        error_msg = f"タイマー設定値エラー: {ve}"; gr.Error(error_msg); traceback.print_exc(); return error_msg
    except Exception as e:
        error_msg = f"タイマー開始エラー: {e}"; gr.Error(error_msg); traceback.print_exc(); return error_msg

# --- UI状態更新ハンドラ (完全版, Kiseki Ver.3/4) ---
def update_ui_on_character_change(character_name: Optional[str]):
    # Based on Kiseki Ver.3 log2gemini.py outputs for character_dropdown.change:
    # [current_character_name, chatbot, log_editor, memory_json_editor, profile_image_display, alarm_char_dropdown, timer_char_dropdown]
    # My ui_handlers.py (Ver.3 based) returned 8 items, Kiseki's log2gemini.py Ver.3 initial_load expects 8.
    # Kiseki's ui_handlers.py Ver.3 update_ui_on_character_change returns 7 items.
    # The log2gemini.py Ver.3 character_dropdown.change has 8 outputs.
    # Let's ensure this function returns 8 values as expected by log2gemini.py initial_load and character_dropdown.change.
    # The expected outputs (from log2gemini initial_load) are:
    # display_alarms_df, id_ful_alarms_df, current_chat_hist, current_log_content, current_mem_str, current_profile_img, alarm_dd_char, timer_dd_char

    if not character_name:
        # This handler is for character_dropdown.change, its outputs are defined in log2gemini.py as:
        # [current_character_name(state), chatbot_display, chat_input_textbox, profile_image_display,
        #  memory_json_editor, alarm_char_dropdown, timer_char_dropdown, log_editor]
        return None, [], "", None, "{}", None, None, "キャラ未選択"

    config_manager.save_config("last_character", character_name)

    log_f, _, img_p, mem_p = get_character_files_paths(character_name)

    # Use HISTORY_LIMIT from config_manager global, ensure it's an int
    history_limit_val = getattr(config_manager, 'HISTORY_LIMIT', "100") # Default to "100" string
    try:
        history_limit = int(history_limit_val)
    except ValueError:
        history_limit = 100 # Fallback if conversion fails

    chat_history = format_history_for_gradio(load_chat_log(log_f, character_name)[-history_limit * 2:]) if log_f and os.path.exists(log_f) else []

    log_content = ""
    if log_f and os.path.exists(log_f):
        try:
            with open(log_f, "r", encoding="utf-8") as f: log_content = f.read()
        except Exception as e_log:
            log_content = f"ログファイル読込エラー: {e_log}"

    memory_str = json.dumps(load_memory_data_safe(mem_p), indent=2, ensure_ascii=False)
    profile_image = img_p if img_p and os.path.exists(img_p) else None

    # Outputs for character_dropdown.change in log2gemini.py (Ver.4 implies these are the correct ones)
    # current_character_name, chatbot_display, chat_input_textbox, profile_image_display,
    # memory_json_editor, alarm_char_dropdown, timer_char_dropdown, log_editor
    return character_name, chat_history, "", profile_image, memory_str, character_name, character_name, log_content


def update_model_state(model):
    config_manager.save_config("last_model", model)
    return model

def update_api_key_state(api_key_name):
    ok, msg = configure_google_api(api_key_name)
    config_manager.save_config("last_api_key_name", api_key_name)
    if ok: gr.Info(f"APIキー '{api_key_name}' 設定成功。")
    else: gr.Error(f"APIキー '{api_key_name}' 設定失敗: {msg}")
    return api_key_name

def update_timestamp_state(checked):
    config_manager.save_config("add_timestamp", bool(checked))

def update_send_thoughts_state(checked):
    config_manager.save_config("last_send_thoughts_to_api", bool(checked))
    return bool(checked)

def update_api_history_limit_state(limit_ui_val):
    api_history_options = getattr(config_manager, 'API_HISTORY_LIMIT_OPTIONS',
                                  {"none": "履歴なし", "all": "全履歴"}) # Simplified fallback
    key = next((k for k, v in api_history_options.items() if v == limit_ui_val), "all")
    config_manager.save_config("last_api_history_limit_option", key)
    return key

def reload_chat_log(character_name):
    if not character_name: return [], "キャラクター未選択" # chatbot, log_editor
    log_f,_,_,_ = get_character_files_paths(character_name)
    if not log_f or not os.path.exists(log_f): return [], "ログファイルなし"
    history_limit_val = getattr(config_manager, 'HISTORY_LIMIT', "100")
    try: history_limit = int(history_limit_val)
    except ValueError: history_limit = 100

    history = format_history_for_gradio(load_chat_log(log_f, character_name)[-history_limit * 2:])
    content = ""
    try:
        with open(log_f, "r", encoding="utf-8") as f: content = f.read()
    except Exception as e: content = f"ログファイル読込エラー: {e}"
    gr.Info(f"'{character_name}'のログを再読み込みしました。"); return history, content

def handle_save_log_button_click(character_name, log_content):
    if not character_name: gr.Error("キャラクターが選択されていません。"); return
    try:
        save_log_file(character_name, log_content);
        gr.Info(f"'{character_name}'のログを保存しました。")
    except Exception as e:
        gr.Error(f"ログ保存エラー: {e}"); traceback.print_exc()

# Kiseki Ver.4: handle_message_submission(*args): return "メッセージ処理は実装中です", "", None, ""
# This means it expects 4 return values.
# The log2gemini.py (Ver.3/4) hookup is:
# outputs=[chatbot_display, chat_input_textbox, file_upload_button, timer_status_display]
def handle_message_submission(*args):
    # Unpack args based on inputs in log2gemini.py:
    # chat_input_textbox, chatbot_display, current_character_name, current_model_name,
    # current_api_key_name_state, file_upload_button, add_timestamp_checkbox,
    # send_thoughts_state, api_history_limit_state
    if len(args) < 9:
        return [], "", None, "引数エラー" # Placeholder for chatbot, input_text, files, status

    textbox_content, chatbot_history, character_name, model_name,     api_key_name, file_list, add_timestamp, send_thoughts, history_limit_key = args[:9]

    # Actual implementation from ui_handlers.py (Ver.3) which was more complete than just a stub:
    if not character_name or not model_name or not api_key_name:
        gr.Error("キャラクター、モデル、またはAPIキーが選択されていません。")
        return chatbot_history, textbox_content or "", file_list, "設定エラー"

    api_ok, msg = configure_google_api(api_key_name)
    if not api_ok:
        gr.Error(f"APIキー設定エラー: {msg}")
        return chatbot_history, textbox_content or "", file_list, f"APIキーエラー: {msg}"

    log_f, sys_p, _, mem_p = get_character_files_paths(character_name)
    if not all([log_f, sys_p, mem_p]):
         gr.Error(f"キャラ '{character_name}' の必須ファイルパス取得失敗。")
         return chatbot_history, textbox_content or "", file_list, "ファイルパスエラー"

    user_header = _get_user_header_from_log(log_f, character_name)
    current_text_input = textbox_content.strip() if textbox_content else ""
    api_text_for_gemini = current_text_input
    processed_file_parts_for_api = [] # Placeholder for actual file processing
    file_log_entries = []

    if file_list: # file_list is List[tempfile._TemporaryFileWrapper objects] or List[str] paths
        for file_obj_or_path in file_list:
            try:
                file_path = file_obj_or_path if isinstance(file_obj_or_path, str) else file_obj_or_path.name
                original_filename = os.path.basename(file_path)
                file_log_entries.append(f"[添付ファイル: {original_filename}]")
                # Actual file processing to create `processed_file_parts_for_api` would go here
            except Exception as e_file:
                gr.Warning(f"ファイル処理エラー: {e_file}")
        if file_log_entries:
             api_text_for_gemini += "\n" + "\n".join(file_log_entries)

    timestamp_log_entry = datetime.datetime.now().strftime(" (%Y-%m-%d %H:%M:%S)") if add_timestamp else ""

    if current_text_input or file_log_entries:
        log_entry_for_user = current_text_input
        if file_log_entries:
            log_entry_for_user += ("\n" if current_text_input else "") + "\n".join(file_log_entries)
        save_message_to_log(log_f, user_header, log_entry_for_user + timestamp_log_entry)

    if not api_text_for_gemini.strip():
        gr.Warning("送信する有効なコンテンツがありません。")
        return chatbot_history, "", None, "入力なし"

    try:
        # response_text, generated_image_path = gemini_api.send_to_gemini(...) # Actual call
        response_text = f"AI ({character_name}): 「{current_text_input}」の処理(省略)"
        if response_text:
            save_message_to_log(log_f, f"## {character_name}:", response_text + timestamp_log_entry)

        new_history_entry = [current_text_input if current_text_input else None, response_text]
        updated_chatbot_history = chatbot_history + [new_history_entry]
        return updated_chatbot_history, "", None, "メッセージ送信成功（仮）"
    except Exception as e_send:
        error_detail = f"送信エラー: {e_send}"
        gr.Error(error_detail)
        return chatbot_history, current_text_input, file_list, error_detail
