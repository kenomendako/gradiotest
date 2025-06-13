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
    """「状態」チェックボックスの変更を検知して処理する。"""
    # df_after_change is the display DataFrame (ID-less) from the UI component.
    # df_original_with_id is the ID-ful DataFrame from the state (alarm_dataframe_original_data).
    if df_after_change is None or df_original_with_id is None:
        return df_original_with_id # Should not happen if states are managed

    try:
        # Iterate through the rows of the original ID-ful DataFrame (which preserves original order and IDs)
        # Compare its '状態' with the corresponding row in the display DataFrame (df_after_change)
        # This assumes that df_after_change (from UI) has the same row order as df_original_with_id was when displayed.
        for index, original_row in df_original_with_id.iterrows():
            if index < len(df_after_change):
                ui_row = df_after_change.iloc[index] # Get corresponding row from display DF
                # We need to ensure we are comparing the correct rows if sorting/filtering can happen in UI.
                # Kiseki's Ver.5 code: if original_row['状態'] != ui_row['状態']:
                # This assumes row-by-row correspondence based on index.

                # Let's try to match based on content if possible, for robustness,
                # but fall back to index if keys are insufficient or complex.
                # The simplest from Kiseki's Ver.5 is direct index comparison for '状態'.
                if original_row['状態'] != ui_row['状態']:
                    alarm_id = original_row['ID']
                    alarm_manager.toggle_alarm_enabled(alarm_id)
                    gr.Info(f"アラーム「{original_row['テーマ']}」の状態を更新しました。 (ID: {alarm_id})")
                    # 상태가 업데이트되었으므로 DB에서 최신 정보를 다시 가져와 반환합니다.
                    # (Korean comment in original Japanese code snippet from Kiseki)
                    # English: Since the state has been updated, retrieve the latest information from the DB and return it.
                    return render_alarms_as_dataframe() # Return fresh ID-ful data

    except Exception as e:
        print(f"Dataframe変更処理中にエラー: {e}\n{traceback.format_exc()}")
        gr.Error("アラーム状態の更新中にエラーが発生しました。")

    # If no state change was detected and handled by returning early
    return df_original_with_id


def handle_alarm_selection(evt: gr.SelectData, df_with_id: pd.DataFrame):
    """Dataframeの行選択を処理し、選択されたIDのリストを返す。"""
    # df_with_id is alarm_dataframe_original_data (ID-ful)
    if evt.indices is None or df_with_id is None or df_with_id.empty: return []
    selected_ids = []
    selected_row_indices = sorted(list(set([index[0] for index in evt.indices])))
    for row_index in selected_row_indices:
        if 0 <= row_index < len(df_with_id):
            selected_ids.append(str(df_with_id.iloc[row_index]['ID']))
    return selected_ids

def handle_delete_selected_alarms(selected_ids: list):
    """「削除」ボタンが押されたときの処理。"""
    if not selected_ids:
        gr.Warning("削除するアラームが選択されていません。")
    else:
        deleted_count = 0
        for alarm_id_str in selected_ids:
            if alarm_manager.delete_alarm(str(alarm_id_str)):
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
        else: # Should not happen
            gr.Error("不明なタイマータイプです。"); return "設定エラー"

        unified_timer = UnifiedTimer(timer_type, float(duration or 0), float(work_duration or 0), float(break_duration or 0), int(cycles or 0), character_name, work_theme, break_theme, api_key_name, webhook_url, normal_timer_theme)
        unified_timer.start()
        gr.Info(f"{timer_type}を開始しました。"); return status_message
    except ValueError as ve:
        error_msg = f"タイマー設定値エラー: {ve}"; gr.Error(error_msg); traceback.print_exc(); return error_msg
    except Exception as e:
        error_msg = f"タイマー開始エラー: {e}"; gr.Error(error_msg); traceback.print_exc(); return error_msg

# --- UI状態更新ハンドラ (完全版, Kiseki Ver.5) ---
def update_ui_on_character_change(character_name: Optional[str]):
    # This function signature and its outputs need to match log2gemini.py's demo.load and character_dropdown.change
    # Kiseki's Ver.5 log2gemini demo.load outputs:
    # [alarm_dataframe, alarm_dataframe_original_data, chatbot, log_editor, memory_json_editor, profile_image_display, alarm_char_dropdown, timer_char_dropdown]
    # Kiseki's Ver.5 ui_handlers update_ui_on_character_change returns 7 items.
    # This implies the initial_load in log2gemini.py will prepare the alarm DFs separately.
    # Let's adjust this handler to return 7 items as per Kiseki's ui_handlers.py Ver.5 spec.
    if not character_name:
        # For 7 outputs: current_character_name, chat_history, "", profile_image, memory_str, character_name (for alarm_dd), log_content
        return None, [], "", None, "{}", None, "キャラ未選択"

    config_manager.save_config("last_character", character_name)

    log_f, _, img_p, mem_p = get_character_files_paths(character_name)

    history_limit_val = getattr(config_manager, 'HISTORY_LIMIT', "100")
    try: history_limit = int(history_limit_val)
    except ValueError: history_limit = 100

    chat_history = format_history_for_gradio(load_chat_log(log_f, character_name)[-history_limit * 2:]) if log_f and os.path.exists(log_f) else []

    log_content = ""
    if log_f and os.path.exists(log_f):
        try:
            with open(log_f, "r", encoding="utf-8") as f: log_content = f.read()
        except Exception as e_log: log_content = f"ログファイル読込エラー: {e_log}"

    memory_str = json.dumps(load_memory_data_safe(mem_p), indent=2, ensure_ascii=False)
    profile_image = img_p if img_p and os.path.exists(img_p) else None

    # Kiseki's ui_handlers.py Ver.5 specific return (7 items)
    return character_name, chat_history, "", profile_image, memory_str, character_name, log_content


def update_model_state(model):
    config_manager.save_config("last_model", model)
    return model

def update_api_key_state(api_key_name):
    # Ensure configure_google_api is available or handle its absence
    if hasattr(gemini_api, 'configure_google_api'):
        ok, msg = gemini_api.configure_google_api(api_key_name)
    else: # Fallback if gemini_api.configure_google_api is not found (should not happen if imports are correct)
        ok, msg = False, "gemini_api.configure_google_api not found"
        print("CRITICAL ERROR: gemini_api.configure_google_api is not available.")


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
                                  {"none": "履歴なし", "all": "全履歴"})
    key = next((k for k, v in api_history_options.items() if v == limit_ui_val), "all")
    config_manager.save_config("last_api_history_limit_option", key)
    return key

def reload_chat_log(character_name):
    if not character_name: return [], "キャラクター未選択"
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

# Kiseki Ver.5: handle_message_submission(*args): return "メッセージ処理は実装中です", "", None, ""
def handle_message_submission(*args):
    # This is the placeholder from Kiseki's Ver.5 ui_handlers.py
    # It expects 4 return values for: chatbot_display, chat_input_textbox, file_upload_button, timer_status_display
    # The actual implementation would be more complex as seen in my previous attempts to fill it.
    # For strict adherence to Kiseki's Ver.5 ui_handlers.py:
    return "メッセージ処理は実装中です", "", None, ""
