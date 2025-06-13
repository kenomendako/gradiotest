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
    """アラームデータを取得し、GradioのDataframe表示用にpandas.DataFrameを生成して返す"""
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

# --- アラームDataframeイベントハンドラ ---
def handle_alarm_dataframe_change(df_after_change: pd.DataFrame, df_original: pd.DataFrame):
    if df_after_change is None or df_original is None or df_after_change.equals(df_original):
        return df_original
    try:
        merged = pd.merge(df_after_change, df_original, on="ID", how="outer", indicator=True, suffixes=('_new', '_old'))
        changes = merged[merged['_merge'] != 'both']

        for _, row in changes.iterrows():
            if pd.notna(row.get('状態_new')) and pd.notna(row.get('状態_old')):
                 if row['状態_new'] != row['状態_old']:
                    alarm_manager.toggle_alarm_enabled(row['ID'])
                    gr.Info(f"アラーム「{row['テーマ_new']}」の状態を更新しました。")
    except Exception as e:
        print(f"Dataframe変更処理中にエラー: {e}\n{traceback.format_exc()}")
        gr.Error("アラーム状態の更新中にエラーが発生しました。")
    return render_alarms_as_dataframe()

def handle_alarm_selection(evt: gr.SelectData, df: pd.DataFrame):
    selected_ids = []
    if evt.selected:
        for row_index in evt.indices:
            alarm_id = df.iloc[row_index[0]]['ID']
            selected_ids.append(str(alarm_id))
    return selected_ids

def handle_delete_selected_alarms(selected_ids: list):
    if not selected_ids:
        gr.Warning("削除するアラームが選択されていません。")
        return render_alarms_as_dataframe()
    deleted_count = sum(1 for alarm_id in selected_ids if alarm_manager.delete_alarm(alarm_id))
    if deleted_count > 0: gr.Info(f"{deleted_count}件のアラームを削除しました。")
    else: gr.Warning("選択されたアラームを削除できませんでした。")
    return render_alarms_as_dataframe()

# --- タイマーイベントハンドラ ---
def handle_timer_submission(timer_type, duration, work_duration, break_duration, cycles, character_name, work_theme, break_theme, api_key_name, webhook_url, normal_timer_theme):
    if not character_name or not api_key_name:
        gr.Error("キャラクターとAPIキーを選択してください。"); return "設定エラー"
    try:
        if timer_type == "通常タイマー":
            if not (duration and float(duration) > 0): gr.Error("通常タイマーの時間を正しく入力してください。"); return "設定エラー"
            status_message = f"{duration}分の通常タイマーを開始しました。"
        else:
            if not (work_duration and float(work_duration) > 0 and break_duration and float(break_duration) > 0 and cycles and int(cycles) > 0): gr.Error("ポモドーロの各項目を正しく入力してください。"); return "設定エラー"
            status_message = f"{work_duration}分作業/{break_duration}分休憩のポモドーロタイマーを開始。"

        unified_timer = UnifiedTimer(timer_type, float(duration or 0), float(work_duration or 0), float(break_duration or 0), int(cycles or 0), character_name, work_theme, break_theme, api_key_name, webhook_url, normal_timer_theme)
        unified_timer.start()
        gr.Info(f"{timer_type}を開始しました。"); return status_message
    except Exception as e:
        error_msg = f"タイマー開始エラー: {e}"; gr.Error(error_msg); traceback.print_exc(); return error_msg

# --- UI状態更新ハンドラ (復活版) ---
def update_ui_on_character_change(character_name: Optional[str]):
    # ... (この関数の実装は省略)
    pass

def update_model_state(model: str):
    # ... (この関数の実装は省略)
    pass

# (他の基本的なハンドラも同様に省略)

# --- メッセージ送信処理 ---
def handle_message_submission(textbox_content, chatbot_history, character_name, model_name, api_key_name, file_list, add_timestamp, send_thoughts, history_limit):
    # (この関数の実装は省略)
    pass
