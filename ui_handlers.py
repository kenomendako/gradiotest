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
from memory_manager import load_memory_data_safe
from utils import load_chat_log, format_history_for_gradio, save_message_to_log, _get_user_header_from_log, save_log_file

# --- Dataframe表示用データ整形関数 ---
DAY_MAP_EN_TO_JA = {"mon": "月", "tue": "火", "wed": "水", "thu": "木", "fri": "金", "sat": "土", "sun": "日"}

def render_alarms_as_dataframe():
    """アラームデータを取得し、GradioのDataframe表示用にpandas.DataFrameを生成して返す。"""
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
    df = pd.DataFrame(display_data, columns=["ID", "状態", "時刻", "曜日", "キャラ", "テーマ"])
    return df

def get_display_df(df_with_id: pd.DataFrame):
    """ID列を非表示にした表示用のDataFrameを返す"""
    if df_with_id is None or df_with_id.empty:
        return pd.DataFrame(columns=["状態", "時刻", "曜日", "キャラ", "テーマ"])
    # ID列が存在するか確認してからドロップ
    if 'ID' in df_with_id.columns:
        return df_with_id.drop(columns=['ID'])
    return df_with_id # IDがなければそのまま返す

# --- アラームDataframeイベントハンドラ ---
def handle_alarm_dataframe_change(df_after_change: pd.DataFrame, df_original: pd.DataFrame):
    # This function receives DataFrames that include the 'ID' column
    # as per log2gemini.py which passes alarm_dataframe_original_data for both inputs
    # when a change is detected.
    if df_after_change is None or df_original is None or df_after_change.equals(df_original):
        return df_original # Return the ID-ful original if no change
    try:
        # IDをキーにして変更を比較
        merged = pd.merge(df_after_change, df_original, on="ID", how="outer", indicator=True, suffixes=('_new', '_old'))
        changes = merged[merged['_merge'] != 'both']

        for _, row in changes.iterrows():
            # Check if '状態_new' and '状態_old' exist and are different
            if pd.notna(row.get('状態_new')) and pd.notna(row.get('状態_old')):
                 if row['状態_new'] != row['状態_old']:
                    alarm_id = row['ID']
                    alarm_manager.toggle_alarm_enabled(alarm_id)
                    theme_to_display = row.get('テーマ_new', row.get('テーマ_old', '')) # Get theme for message
                    gr.Info(f"アラーム「{theme_to_display}」の状態を更新しました。")
            elif pd.notna(row.get('ID')) and (pd.isna(row.get('状態_old')) or pd.isna(row.get('状態_new'))):
                # This case could be a new row added or a row deleted if not handled elsewhere.
                # For this specific handler, primary focus is on '状態' toggle.
                # Additions/deletions are typically handled by different UI flows.
                print(f"Debug: Row ID {row['ID']} found in changes but not a simple state toggle.")


    except Exception as e:
        print(f"Dataframe変更処理中にエラー: {e}\n{traceback.format_exc()}")
        gr.Error("アラーム状態の更新中にエラーが発生しました。")
    # Returns the new state of all alarms (ID-ful)
    return render_alarms_as_dataframe()

def handle_alarm_selection(evt: gr.SelectData, df_with_id: pd.DataFrame):
    # df_with_id is the DataFrame that includes the 'ID' column (from alarm_dataframe_original_data state)
    if evt.indices is None or df_with_id is None or df_with_id.empty:
        return []
    selected_ids = []
    selected_row_indices = sorted(list(set([index[0] for index in evt.indices])))
    for row_index in selected_row_indices:
        if 0 <= row_index < len(df_with_id): # Check bounds
            alarm_id = df_with_id.iloc[row_index]['ID']
            selected_ids.append(str(alarm_id))
    return selected_ids

def handle_delete_selected_alarms(selected_ids: list):
    if not selected_ids:
        gr.Warning("削除するアラームが選択されていません。")
    else:
        deleted_count = 0
        for alarm_id_str in selected_ids: # Iterate over the provided list of IDs
            if alarm_manager.delete_alarm(str(alarm_id_str)):
                deleted_count += 1

        if deleted_count > 0:
            gr.Info(f"{deleted_count}件のアラームを削除しました。")
        else:
            gr.Warning("選択されたアラームを削除できませんでした。")
    # Returns the new state of all alarms (ID-ful), which will then be processed by log2gemini
    return render_alarms_as_dataframe()

# --- タイマーイベントハンドラ ---
def handle_timer_submission(timer_type, duration, work_duration, break_duration, cycles, character_name, work_theme, break_theme, api_key_name, webhook_url, normal_timer_theme):
    if not character_name or not api_key_name:
        gr.Error("キャラクターとAPIキーを選択してください。"); return "設定エラー" # Return a string for status display
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
            gr.Error("不明なタイマータイプです。"); return "設定エラー"


        unified_timer = UnifiedTimer(timer_type, float(duration or 0), float(work_duration or 0), float(break_duration or 0), int(cycles or 0), character_name, work_theme, break_theme, api_key_name, webhook_url, normal_timer_theme)
        unified_timer.start()
        gr.Info(f"{timer_type}を開始しました。"); return status_message
    except ValueError as ve: # Catch specific conversion errors
        error_msg = f"タイマー設定値エラー: {ve}"; gr.Error(error_msg); traceback.print_exc(); return error_msg
    except Exception as e:
        error_msg = f"タイマー開始エラー: {e}"; gr.Error(error_msg); traceback.print_exc(); return error_msg

# --- 基本的なUI状態更新ハンドラ ---
def update_ui_on_character_change(character_name):
    if not character_name: return None, [], "", None, "{}", None, "キャラ未選択" # Match tuple size for outputs
    config_manager.initial_character_global = character_name # Update global state directly if this is the pattern
    # Alternatively, save to config file: config_manager.save_config("last_character", character_name)

    log_f, _, img_p, mem_p = get_character_files_paths(character_name)

    history_limit = getattr(config_manager, 'HISTORY_LIMIT', 100) # Use global var
    chat_history = format_history_for_gradio(load_chat_log(log_f, character_name)[-history_limit * 2:]) if log_f and os.path.exists(log_f) else []

    log_content = ""
    if log_f and os.path.exists(log_f):
        try:
            with open(log_f, "r", encoding="utf-8") as f: log_content = f.read()
        except Exception as e:
            log_content = f"ログファイル読込エラー: {e}"

    memory_str = json.dumps(load_memory_data_safe(mem_p), indent=2, ensure_ascii=False)
    profile_image = img_p if img_p and os.path.exists(img_p) else None

    # Expected outputs: current_character_name, chatbot, chat_input_textbox, profile_image_display, memory_json_editor, alarm_char_dropdown, log_editor
    return character_name, chat_history, "", profile_image, memory_str, character_name, log_content

def update_model_state(model):
    config_manager.initial_model_global = model # Update global state
    # config_manager.save_config("last_model", model) # Or save to file
    return model

def update_api_key_state(api_key_name):
    ok, msg = configure_google_api(api_key_name)
    config_manager.initial_api_key_name_global = api_key_name # Update global state
    # config_manager.save_config("last_api_key_name", api_key_name) # Or save to file
    if ok: gr.Info(f"APIキー '{api_key_name}' 設定成功。")
    else: gr.Error(f"APIキー '{api_key_name}' 設定失敗: {msg}")
    return api_key_name

def update_timestamp_state(checked):
    # Assuming add_timestamp is a global var in config_manager or saved to config
    config_manager.add_timestamp_global = bool(checked) # Example if it's a global
    # config_manager.save_config("add_timestamp", bool(checked))

def update_send_thoughts_state(checked):
    config_manager.initial_send_thoughts_to_api_global = bool(checked) # Update global
    # config_manager.save_config("last_send_thoughts_to_api", bool(checked))
    return bool(checked) # Return the state for Gradio state variable

def update_api_history_limit_state(limit_ui_val):
    api_history_options = getattr(config_manager, 'API_HISTORY_LIMIT_OPTIONS', {})
    key = next((k for k, v in api_history_options.items() if v == limit_ui_val), "all")
    config_manager.initial_api_history_limit_option_global = key # Update global
    # config_manager.save_config("last_api_history_limit_option", key)
    return key # Return the key for Gradio state variable

def reload_chat_log(character_name):
    if not character_name: return [], "キャラクター未選択"
    log_f,_,_,_ = get_character_files_paths(character_name)
    if not log_f or not os.path.exists(log_f): return [], "ログファイルなし"
    history_limit = getattr(config_manager, 'HISTORY_LIMIT', 100)
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

# --- メッセージ送信処理 ---
def handle_message_submission(textbox_content, chatbot_history, character_name, model_name, api_key_name, file_list, add_timestamp, send_thoughts, history_limit_key):
    # Using global vars from config_manager as per Kiseki's latest explanation
    if not character_name or not model_name or not api_key_name:
        gr.Error("キャラクター、モデル、またはAPIキーが選択されていません。")
        return chatbot_history, textbox_content, file_list, "設定エラー" # Keep inputs, show error

    # Ensure API is configured with the current key
    # This might be redundant if configure_google_api is called on key change, but good for safety
    api_ok, msg = configure_google_api(api_key_name)
    if not api_ok:
        gr.Error(f"APIキー設定エラー: {msg}")
        return chatbot_history, textbox_content, file_list, f"APIキーエラー: {msg}"

    log_f, sys_p, _, mem_p = get_character_files_paths(character_name)
    user_header = _get_user_header_from_log(log_f, character_name) # Get user header

    # Process text and files for API
    api_text_arg = textbox_content.strip() if textbox_content else ""
    files_for_gemini = [] # To be populated with {'path': ..., 'mime_type': ...}

    # Timestamp logic (simplified, assuming utils.py handles detailed formatting)
    timestamp_str = f" ({datetime.datetime.now().strftime('%H:%M:%S')})" if add_timestamp else ""

    # Log user message (text part)
    if api_text_arg:
        save_message_to_log(log_f, user_header, api_text_arg + timestamp_str)

    # TODO: File handling logic from previous versions needs to be integrated here
    # For now, just acknowledge files if present
    if file_list:
        api_text_arg += f"\n[添付ファイルが{len(file_list)}件あります]" # Placeholder for actual file processing
        # save_message_to_log for file attachments would go here

    if not api_text_arg and not files_for_gemini: # Check if there's anything to send
        gr.Warning("送信するテキストまたはファイルがありません。")
        return chatbot_history, textbox_content, file_list, "入力なし"

    try:
        # Send to Gemini API
        # Assuming send_to_gemini can handle history_limit_key, send_thoughts etc.
        # The placeholder from Kiseki was: return chatbot_history, "", None, "メッセージ処理は実装中です"
        # This suggests the full implementation is complex.
        # For now, a more dynamic placeholder:

        # This is where the actual call to gemini_api.send_to_gemini would be:
        # response_text, generated_image_path = gemini_api.send_to_gemini(
        # system_prompt_path=sys_p,
        # log_file_path=log_f, # for history
        # user_prompt=api_text_arg,
        # selected_model=model_name,
        # character_name=character_name,
        # send_thoughts_to_api=send_thoughts,
        # api_history_limit_option=history_limit_key,
        # uploaded_file_parts=files_for_gemini, # This needs to be prepared correctly
        # memory_json_path=mem_p
        # )

        # Placeholder response:
        response_text = f"AI ({character_name}): 「{api_text_arg}」について思考中... (API呼び出しは省略されました)"
        generated_image_path = None # Placeholder

        if response_text:
            save_message_to_log(log_f, f"## {character_name}:", response_text + timestamp_str)
        if generated_image_path: # If image generation was part of it
             save_message_to_log(log_f, f"## {character_name}:", f"[生成画像: {generated_image_path}]")


        # Update chat history for display
        # chatbot_history.append([textbox_content, response_text])
        # If image, chatbot_history.append([None, (generated_image_path,)])

        # Let's use the reload log pattern to get updated history
        current_chat_history, _ = reload_chat_log(character_name)

        return current_chat_history, "", None, "" # Clear input, clear files, no error message

    except Exception as e:
        print(f"メッセージ送信処理中にエラー: {e}\n{traceback.format_exc()}")
        gr.Error("メッセージ送信中にエラーが発生しました。")
        return chatbot_history, textbox_content, file_list, f"送信エラー: {e}"
