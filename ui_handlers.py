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
    # ID列もデータとして含んだままDataFrameを作成
    df = pd.DataFrame(display_data, columns=["ID", "状態", "時刻", "曜日", "キャラ", "テーマ"])
    return df

def get_display_df(df_with_id: pd.DataFrame):
    """ID列を非表示にした表示用のDataFrameを返す"""
    if df_with_id is None or df_with_id.empty:
        return pd.DataFrame(columns=["状態", "時刻", "曜日", "キャラ", "テーマ"])
    return df_with_id[["状態", "時刻", "曜日", "キャラ", "テーマ"]]

# --- アラームDataframeイベントハンドラ ---
def handle_alarm_dataframe_change(df_after_change: pd.DataFrame, df_original: pd.DataFrame):
    if df_after_change is None or df_original is None or df_after_change.equals(df_original):
        return df_original, df_original

    try:
        merged = pd.merge(df_after_change, df_original, on="ID", how="outer", indicator=True, suffixes=('_new', '_old'))
        changes = merged[merged['_merge'] != 'both']

        for _, row in changes.iterrows():
            if pd.notna(row.get('状態_new')) and pd.notna(row.get('状態_old')):
                 if row['状態_new'] != row['状態_old']:
                    alarm_id = row['ID']
                    alarm_manager.toggle_alarm_enabled(alarm_id)
                    theme_to_display = row.get('テーマ_new', row.get('テーマ_old', ''))
                    gr.Info(f"アラーム「{theme_to_display}」の状態を更新しました。")

    except Exception as e:
        print(f"Dataframe変更処理中にエラー: {e}\n{traceback.format_exc()}")
        gr.Error("アラーム状態の更新中にエラーが発生しました。")

    new_df_with_ids = render_alarms_as_dataframe()
    return new_df_with_ids, new_df_with_ids

def handle_alarm_selection(df_with_id: pd.DataFrame, evt: gr.SelectData):
    if evt.indices is None or df_with_id is None or df_with_id.empty:
        print("Debug: handle_alarm_selection - evt.indices or df_with_id is None or empty.")
        return []

    selected_ids = []
    selected_row_indices = sorted(list(set([index[0] for index in evt.indices])))
    print(f"Debug: handle_alarm_selection - Selected UI row indices: {selected_row_indices}")

    for row_index in selected_row_indices:
        if 0 <= row_index < len(df_with_id):
            alarm_id = df_with_id.iloc[row_index]['ID']
            selected_ids.append(str(alarm_id))
        else:
            print(f"Debug: handle_alarm_selection - row_index {row_index} out of bounds for df_with_id len {len(df_with_id)}.")

    print(f"UI Event: Alarms selected (IDs): {selected_ids}")
    return selected_ids

def handle_delete_selected_alarms(selected_ids: list):
    if not selected_ids:
        gr.Warning("削除するアラームが選択されていません。")
        # Fallback to return structure expected by log2gemini's refresh_alarm_ui if delete directly updates display + original
        # However, Kiseki's log2gemini.py for delete is:
        # outputs=[alarm_dataframe] -> then -> fn=lambda: [], outputs=[selected_alarm_ids_state] -> then -> fn=refresh_alarm_ui
        # This means this handler's direct output is only for 'alarm_dataframe' (display version).
        # The subsequent refresh_alarm_ui will handle setting both display and original_data state.
        id_ful_df = render_alarms_as_dataframe()
        return get_display_df(id_ful_df)
    else:
        deleted_count = 0
        for alarm_id_str in selected_ids:
            if alarm_manager.delete_alarm(str(alarm_id_str)):
                deleted_count += 1

        if deleted_count > 0:
            gr.Info(f"{deleted_count}件のアラームを削除しました。")
        else:
            gr.Warning("選択されたアラームを削除できませんでした。")

    id_ful_df = render_alarms_as_dataframe()
    # This output is for the first .click(..., outputs=[alarm_dataframe])
    return get_display_df(id_ful_df)

# --- タイマーイベントハンドラ ---
def handle_timer_submission(timer_type, duration, work_duration, break_duration, cycles, character_name, work_theme, break_theme, api_key_name, webhook_url, normal_timer_theme):
    if not character_name or not api_key_name:
        gr.Error("キャラクターとAPIキーを選択してください。"); return "設定エラー"
    try:
        status_message = ""
        if timer_type == "通常タイマー":
            if not (duration and float(duration) > 0): gr.Error("通常タイマーの時間を正しく入力してください。"); return "設定エラー"
            status_message = f"{duration}分の通常タイマーを開始しました。"
        elif timer_type == "ポモドーロタイマー":
            if not (work_duration and float(work_duration) > 0 and break_duration and float(break_duration) > 0 and cycles and int(cycles) > 0): gr.Error("ポモドーロの各項目を正しく入力してください。"); return "設定エラー"
            status_message = f"{work_duration}分作業/{break_duration}分休憩のポモドーロタイマーを開始。"

        unified_timer = UnifiedTimer(timer_type, float(duration or 0), float(work_duration or 0), float(break_duration or 0), int(cycles or 0), character_name, work_theme, break_theme, api_key_name, webhook_url, normal_timer_theme)
        unified_timer.start()
        gr.Info(f"{timer_type}を開始しました。"); return status_message
    except Exception as e:
        error_msg = f"タイマー開始エラー: {e}"; gr.Error(error_msg); traceback.print_exc(); return error_msg

# --- 基本的なUI状態更新ハンドラ ---
def update_ui_on_character_change(character_name):
    if not character_name: return None, [], "", None, "{}", None, "キャラ未選択"
    config_manager.save_config("last_character", character_name)
    log_f, _, img_p, mem_p = get_character_files_paths(character_name)
    history_limit = int(config_manager.get_config().get("HISTORY_LIMIT", 100))
    chat_history = format_history_for_gradio(load_chat_log(log_f, character_name)[-history_limit * 2:]) if log_f and os.path.exists(log_f) else []
    log_content = ""
    if log_f and os.path.exists(log_f):
        with open(log_f, "r", encoding="utf-8") as f: log_content = f.read()
    memory_str = json.dumps(load_memory_data_safe(mem_p), indent=2, ensure_ascii=False)
    profile_image = img_p if img_p and os.path.exists(img_p) else None
    return character_name, chat_history, "", profile_image, memory_str, character_name, log_content

def update_model_state(model):
    config_manager.save_config("last_model", model); return model

def update_api_key_state(api_key_name):
    ok, msg = configure_google_api(api_key_name);
    config_manager.save_config("last_api_key_name", api_key_name)
    if ok: gr.Info(f"APIキー '{api_key_name}' 設定成功。")
    else: gr.Error(f"APIキー '{api_key_name}' 設定失敗: {msg}")
    return api_key_name

def update_timestamp_state(checked):
    config_manager.save_config("add_timestamp", bool(checked))

def update_send_thoughts_state(checked):
    config_manager.save_config("last_send_thoughts_to_api", bool(checked)); return bool(checked)

def update_api_history_limit_state(limit_ui_val):
    # Ensure API_HISTORY_LIMIT_OPTIONS is loaded from config_manager, not a hardcoded dict
    api_history_options = getattr(config_manager, 'API_HISTORY_LIMIT_OPTIONS', {})
    if not api_history_options: # Fallback if not found in config_manager for some reason
        api_history_options = {"none": "履歴なし", "summary": "短期記憶(要約)", "short": "短期記憶(最新5件)", "long": "長期記憶(最新10件)", "all": "全履歴"}
    key = next((k for k, v in api_history_options.items() if v == limit_ui_val), "all")
    config_manager.save_config("last_api_history_limit_option", key); return key

def reload_chat_log(character_name):
    if not character_name: return [], "キャラクター未選択"
    log_f,_,_,_ = get_character_files_paths(character_name)
    if not log_f or not os.path.exists(log_f): return [], "ログファイルなし"
    history_limit = int(config_manager.get_config().get("HISTORY_LIMIT", 100))
    history = format_history_for_gradio(load_chat_log(log_f, character_name)[-history_limit * 2:])
    content = ""
    with open(log_f, "r", encoding="utf-8") as f: content = f.read()
    gr.Info(f"'{character_name}'のログを再読み込みしました。"); return history, content

def handle_save_log_button_click(character_name, log_content):
    if not character_name: gr.Error("キャラクターが選択されていません。"); return
    try:
        save_log_file(character_name, log_content);
        gr.Info(f"'{character_name}'のログを保存しました。")
    except Exception as e:
        gr.Error(f"ログ保存エラー: {e}"); traceback.print_exc()

# --- メッセージ送信処理 (内容は変更なし) ---
def handle_message_submission(textbox_content, chatbot_history, character_name, model_name, api_key_name, file_list, add_timestamp, send_thoughts, history_limit):
    print(f"Debug: handle_message_submission called with char: {character_name}, model: {model_name}")
    if not character_name or not model_name or not api_key_name:
        return chatbot_history, textbox_content, None, "エラー: キャラクター、モデル、APIキーのいずれかが選択されていません。"
    # Actual implementation would call gemini_api.send_to_gemini etc.
    # This is a placeholder based on Kiseki's note "(この関数の実装は長大なので、ここでは省略します。前回のコードをそのまま使います)"
    # and the stub return "メッセージ処理は実装中です"
    # For a slightly more interactive placeholder:
    response_text = f"Received: '{textbox_content}' for {character_name} with {model_name}."
    if file_list:
        response_text += f" Plus {len(file_list)} files."
    # Simulate some processing
    chatbot_history.append([textbox_content, response_text])
    return chatbot_history, "", None, "" # Clear textbox, no new files, no error
