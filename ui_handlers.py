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
    alarms = alarm_manager.get_all_alarms()
    display_data = []
    for alarm in sorted(alarms, key=lambda x: x.get("time", "")): # Sort for consistent display
        days_ja = [DAY_MAP_EN_TO_JA.get(d, d.upper()) for d in alarm.get('days', [])]
        display_data.append({
            "ID": alarm.get("id"), # Keep ID for internal use if needed, but won't be returned for display
            "状態": alarm.get("enabled", False),
            "時刻": alarm.get("time"),
            "曜日": ",".join(days_ja),
            "キャラ": alarm.get("character"),
            "テーマ": alarm.get("theme")
        })
    df = pd.DataFrame(display_data, columns=["ID", "状態", "時刻", "曜日", "キャラ", "テーマ"])
    return df[["状態", "時刻", "曜日", "キャラ", "テーマ"]]

def get_alarms_as_dataframe_with_id():
    """内部処理用にIDを含んだDataFrameを返すヘルパー"""
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

# --- アラームDataframeイベントハンドラ ---
def handle_alarm_dataframe_change(df_after_change: pd.DataFrame, df_original_display: pd.DataFrame):
    if df_after_change is None or df_original_display is None:
        return render_alarms_as_dataframe()

    df_with_ids_current_db_state = get_alarms_as_dataframe_with_id()
    if df_with_ids_current_db_state.empty:
        return render_alarms_as_dataframe()

    df_after_change['temp_key'] = df_after_change.apply(lambda row: f"{row['時刻']}_{'_'.join(sorted(row['曜日'].split(',')))}_{row['キャラ']}_{row['テーマ']}", axis=1)
    df_with_ids_current_db_state['temp_key'] = df_with_ids_current_db_state.apply(lambda row: f"{row['時刻']}_{'_'.join(sorted(row['曜日'].split(',')))}_{row['キャラ']}_{row['テーマ']}", axis=1)

    changed_ids_count = 0
    for index, row_ui in df_after_change.iterrows():
        db_row_match = df_with_ids_current_db_state[df_with_ids_current_db_state['temp_key'] == row_ui['temp_key']]
        if not db_row_match.empty:
            db_alarm = db_row_match.iloc[0]
            ui_state = row_ui['状態']
            db_state = db_alarm['状態']
            alarm_id = db_alarm['ID']
            theme = db_alarm['テーマ']
            if ui_state != db_state:
                try:
                    alarm_manager.toggle_alarm_enabled(alarm_id)
                    gr.Info(f"アラーム「{theme}」の状態を更新しました。ID: {alarm_id}")
                    changed_ids_count += 1
                except Exception as e_toggle:
                    print(f"Error toggling alarm ID {alarm_id}: {e_toggle}\n{traceback.format_exc()}")
                    gr.Error(f"アラーム「{theme}」の状態更新に失敗。")
        else:
            print(f"Warning: Row in UI not found in DB state for change detection: {row_ui}")

    df_after_change.drop(columns=['temp_key'], inplace=True)

    if changed_ids_count > 0:
        print(f"Processed {changed_ids_count} alarm state changes.")

    return render_alarms_as_dataframe()

def handle_alarm_selection(df_display: pd.DataFrame, evt: gr.SelectData) -> list:
    if evt.indices is None or df_display is None or df_display.empty:
        return []

    selected_row_indices = sorted(list(set([index[0] for index in evt.indices])))
    if not selected_row_indices:
        return []

    df_with_ids = get_alarms_as_dataframe_with_id()
    if df_with_ids.empty:
        return []

    selected_ids = []
    for row_idx in selected_row_indices:
        if 0 <= row_idx < len(df_display):
            ui_row_data = df_display.iloc[row_idx]
            match_conditions = (
                (df_with_ids["時刻"] == ui_row_data["時刻"]) &
                (df_with_ids["キャラ"] == ui_row_data["キャラ"]) &
                (df_with_ids["テーマ"] == ui_row_data["テーマ"]) &
                (df_with_ids["曜日"] == ui_row_data["曜日"]) &
                (df_with_ids["状態"] == ui_row_data["状態"])
            )
            matched_alarms_in_db = df_with_ids[match_conditions]
            if not matched_alarms_in_db.empty:
                for an_id in matched_alarms_in_db["ID"].tolist():
                    selected_ids.append(str(an_id))
            else:
                print(f"Warning: Could not find ID for selected UI row (idx {row_idx}): {ui_row_data}")

    return list(set(selected_ids))

def handle_delete_selected_alarms(selected_ids: list):
    if not selected_ids:
        gr.Warning("削除するアラームが選択されていません。")
        return render_alarms_as_dataframe()

    deleted_count = 0
    for alarm_id_str in selected_ids:
        try:
            if alarm_manager.delete_alarm(str(alarm_id_str)):
                deleted_count += 1
        except Exception as e_del:
            print(f"Error deleting alarm ID {alarm_id_str}: {e_del}")
            gr.Error(f"アラーム ID {alarm_id_str} の削除中にエラー。")

    if deleted_count > 0:
        gr.Info(f"{deleted_count}件のアラームを削除しました。")
    elif not selected_ids:
        gr.Warning("削除するアラームが選択されていません。")
    else:
        gr.Warning("選択されたアラームを削除できませんでした。ログを確認してください。")

    return render_alarms_as_dataframe()

# --- タイマーイベントハンドラ ---
def handle_timer_submission(timer_type, duration, work_duration, break_duration, cycles, character_name, work_theme, break_theme, api_key_name, webhook_url, normal_timer_theme):
    if not character_name or not api_key_name:
        gr.Error("キャラクターとAPIキーを選択してください。"); return "設定エラー"
    try:
        if timer_type == "通常タイマー":
            if not (duration and float(duration) > 0):
                gr.Error("通常タイマーの時間を正しく入力してください。"); return "設定エラー"
            status_message = f"{duration}分の通常タイマーを開始しました。"
        else: # ポモドーロタイマー
            if not (work_duration and float(work_duration) > 0 and \
                    break_duration and float(break_duration) > 0 and \
                    cycles and int(cycles) > 0):
                gr.Error("ポモドーロの各項目を正しく入力してください。"); return "設定エラー"
            status_message = f"{work_duration}分作業/{break_duration}分休憩のポモドーロタイマー ({cycles}サイクル) を開始。"

        unified_timer = UnifiedTimer(
            timer_type=timer_type,
            duration_minutes=float(duration) if duration else 0,
            work_minutes=float(work_duration) if work_duration else 0,
            break_minutes=float(break_duration) if break_duration else 0,
            cycles=int(cycles) if cycles else 0,
            character_name=character_name,
            work_theme=work_theme,
            break_theme=break_theme,
            api_key_name=api_key_name,
            webhook_url=webhook_url,
            normal_timer_theme=normal_timer_theme
        )
        unified_timer.start()
        gr.Info(f"{timer_type}を開始しました。"); return status_message
    except ValueError as ve:
        error_msg = f"タイマー設定値エラー: {ve}"; gr.Error(error_msg); traceback.print_exc(); return error_msg
    except Exception as e:
        error_msg = f"タイマー開始エラー: {e}"; gr.Error(error_msg); traceback.print_exc(); return error_msg

# --- UI状態更新ハンドラ (復活版) ---
def update_ui_on_character_change(character_name: Optional[str]):
    if not character_name:
        return gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update()
    return gr.update(value=character_name), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(value=character_name), gr.update()

def update_model_state(model: str):
    return gr.update(value=model)

# --- メッセージ送信処理 ---
def handle_message_submission(textbox_content, chatbot_history, character_name, model_name, api_key_name, file_list, add_timestamp, send_thoughts, history_limit):
    return chatbot_history, gr.update(value=""), gr.update(value=None), "メッセージ処理は省略されました。"
