# -*- coding: utf-8 -*-
import pandas as pd
from typing import List, Optional, Dict, Any, Tuple, Union
import gradio as gr
import datetime
import utils
import json
import traceback
import os
import uuid
import shutil
import re
# --- モジュールインポート ---
import config_manager
import alarm_manager
from timers import UnifiedTimer
from character_manager import get_character_files_paths
from gemini_api import configure_google_api, send_to_gemini
from memory_manager import load_memory_data_safe
from utils import load_chat_log, format_history_for_gradio, save_message_to_log, _get_user_header_from_log

# (handle_message_submission や update_..._state など、他の関数は変更なしのため省略)
# このファイルの末尾に、新しいアラームとタイマーのハンドラ関数を追加し、
# 既存のものを一部修正します。

# --- Dataframe表示用データ整形関数 ---
def render_alarms_as_dataframe():
    """
    アラームデータを取得し、GradioのDataframe表示用にpandas.DataFrameを生成して返す。
    """
    alarms = alarm_manager.get_all_alarms()

    # 表示用のデータを準備
    display_data = []
    DAY_MAP_EN_TO_JA = {"mon": "月", "tue": "火", "wed": "水", "thu": "木", "fri": "金", "sat": "土", "sun": "日"}

    for alarm in alarms:
        days_ja = [DAY_MAP_EN_TO_JA.get(d, d.upper()) for d in alarm.get('days', [])]
        display_data.append({
            "ID": alarm.get("id"),
            "状態": alarm.get("enabled", False),
            "時刻": alarm.get("time"),
            "曜日": ",".join(days_ja),
            "キャラ": alarm.get("character"),
            "テーマ": alarm.get("theme")
        })

    # pandas DataFrameを作成
    if not display_data:
        # データがない場合も、ヘッダーを持つ空のDataFrameを返す
        return pd.DataFrame(columns=["ID", "状態", "時刻", "曜日", "キャラ", "テーマ"])

    df = pd.DataFrame(display_data)
    # 表示順を定義
    df = df[["ID", "状態", "時刻", "曜日", "キャラ", "テーマ"]]
    return df

# --- アラームDataframeイベントハンドラ ---
def handle_alarm_dataframe_change(df: pd.DataFrame, original_df: pd.DataFrame):
    """
    Dataframeの内容が変更されたときに呼び出される。
    主に「状態」チェックボックスのON/OFFを検知する。
    """
    if df.equals(original_df):
        return # 変更がない場合は何もしない

    try:
        # DataFrameを比較して変更された行を見つける
        # 'ID' 列をインデックスとして使用して比較を試みる
        df_indexed = df.set_index("ID")
        original_df_indexed = original_df.set_index("ID")

        # 状態が変更された可能性のあるIDのリストを取得
        # まず、両方のDataFrameに存在するIDの共通部分を取得
        common_ids = df_indexed.index.intersection(original_df_indexed.index)

        for alarm_id in common_ids:
            new_status = df_indexed.loc[alarm_id, '状態']
            old_status = original_df_indexed.loc[alarm_id, '状態']
            
            if new_status != old_status:
                print(f"UI Event: Alarm '{alarm_id}' status changed from {old_status} to {new_status}.")
                alarm_manager.toggle_alarm_enabled(alarm_id)
                # DataFrameからテーマを取得
                theme = df_indexed.loc[alarm_id, 'テーマ']
                gr.Info(f"アラーム「{theme}」の状態を更新しました。")

    except Exception as e:
        print(f"Dataframe変更処理中にエラー: {e}")
        traceback.print_exc()
        gr.Error("アラームの状態更新中にエラーが発生しました。")

    # 変更を反映した最新のDataFrameを返す
    return render_alarms_as_dataframe()

def handle_alarm_selection(df: pd.DataFrame, evt: gr.SelectData):
    """
    Dataframeの行が選択されたときに呼び出される。選択された行のIDを返す。
    GradioのSelectData.indicesは [(row_index, col_index), ...] の形式
    """
    if evt.indices is None: # evt.indicesが正しい属性名か確認
        return []
    
    selected_ids = []
    # evt.indices は選択されたセルの (row_index, col_index) のタプルのリスト
    # 重複する行インデックスを排除するためにsetを使用
    selected_row_indices = sorted(list(set([index_pair[0] for index_pair in evt.indices])))

    for row_index in selected_row_indices:
        if row_index < len(df): # DataFrameの範囲内か確認
            alarm_id = df.iloc[row_index]['ID']
            selected_ids.append(str(alarm_id)) # IDを文字列として追加

    print(f"UI Event: Alarms selected: {selected_ids}")
    return selected_ids


def handle_delete_selected_alarms(selected_ids: list):
    """
    「削除」ボタンが押されたときに呼び出される。
    """
    if not selected_ids:
        gr.Warning("削除するアラームが選択されていません。")
        return render_alarms_as_dataframe() # 何もせず現在のリストを返す

    deleted_count = 0
    for alarm_id in selected_ids:
        if alarm_manager.delete_alarm(alarm_id): # delete_alarmは成功時Trueを返すと仮定
            deleted_count += 1
            print(f"Attempted to delete alarm {alarm_id}, result: successful")
        else:
            print(f"Attempted to delete alarm {alarm_id}, result: failed or not found")


    if deleted_count > 0:
        gr.Info(f"{deleted_count}件のアラームを削除しました。")
    else:
        # 選択されたIDがあったが、何も削除されなかった場合
        # (例: IDがバックエンドに存在しなかった、またはdelete_alarmがFalseを返した)
        gr.Warning("選択されたアラームを削除できませんでした。リストを再確認してください。")


    # 最新のリストを返す
    return render_alarms_as_dataframe()

# --- タイマーイベントハンドラ ---
def handle_timer_submission(
    timer_type: str,
    duration: Optional[float],
    work_duration: Optional[float],
    break_duration: Optional[float],
    cycles: Optional[int],
    character_name: Optional[str],
    work_theme: Optional[str],
    break_theme: Optional[str],
    api_key_name: Optional[str],
    webhook_url: Optional[str],
    normal_timer_theme: Optional[str]
) -> str: # 戻り値を文字列に変更
    """
    タイマー設定フォームからの送信を処理し、適切なタイマーを開始し、ステータス文字列を返す。
    """
    if not character_name or not api_key_name:
        gr.Error("キャラクターとAPIキーを選択してください。")
        return "設定エラー: キャラクターとAPIキーを選択してください。" # 詳細なエラーメッセージ

    status_message = ""
    try:
        if timer_type == "通常タイマー":
            if not (duration and duration > 0):
                gr.Error("通常タイマーの時間を正しく入力してください。")
                return "設定エラー: 通常タイマーの時間を正しく入力してください。"
            actual_duration_minutes = float(duration)
            status_message = f"{actual_duration_minutes}分の通常タイマー（{normal_timer_theme if normal_timer_theme else '指定テーマなし'}）を開始しました。（キャラ: {character_name}）"
        elif timer_type == "ポモドーロタイマー":
            if not (work_duration and work_duration > 0 and break_duration and break_duration > 0 and cycles and cycles > 0):
                gr.Error("ポモドーロタイマーの各項目を正しく入力してください。")
                return "設定エラー: ポモドーロタイマーの各項目を正しく入力してください。"
            status_message = f"{float(work_duration)}分作業（{work_theme if work_theme else '作業'}）/{float(break_duration)}分休憩（{break_theme if break_theme else '休憩'}） のポモドーロタイマーを{int(cycles)}サイクルで開始しました。"
        else:
            gr.Error(f"不明なタイマータイプです: {timer_type}")
            return f"設定エラー: 不明なタイマータイプです: {timer_type}"

        # UnifiedTimerのインスタンス化と開始
        # 注意: UnifiedTimerのコンストラクタとstartメソッドがこの呼び出し方と一致しているか確認が必要
        unified_timer = UnifiedTimer(
            timer_type=timer_type,
            duration_minutes=float(duration) if duration else 0, # UnifiedTimerがduration_minutesを期待する場合
            work_minutes=float(work_duration) if work_duration else 0,
            break_minutes=float(break_duration) if break_duration else 0,
            cycles=int(cycles) if cycles else 0,
            character_name=character_name,
            work_theme=work_theme if work_theme else "作業の時間です！", # デフォルトテーマ
            break_theme=break_theme if break_theme else "休憩しましょう！", # デフォルトテーマ
            api_key_name=api_key_name,
            webhook_url=webhook_url, # UnifiedTimerがwebhook_urlを処理できるか確認
            normal_timer_theme=normal_timer_theme if normal_timer_theme else "時間です！" # デフォルトテーマ
        )
        unified_timer.start() # startメソッドが例外を投げる可能性も考慮
        gr.Info(f"{timer_type}を開始しました。")
        return status_message

    except ValueError as ve: # 数値変換エラーなど
        error_msg = f"タイマー設定値エラー: {str(ve)}"
        gr.Error(error_msg)
        traceback.print_exc()
        return error_msg
    except Exception as e: # その他の予期せぬエラー
        error_msg = f"タイマー開始時に予期せぬエラーが発生しました: {str(e)}"
        gr.Error(error_msg)
        traceback.print_exc()
        return error_msg

# placeholder for other functions that might be in the original ui_handlers.py
# def handle_message_submission(message_input_textbox, *args): pass
# def update_api_key_dropdown_state(*args): pass
# def update_model_dropdown_state(*args): pass
# def update_character_dropdown_state(*args): pass
# def update_temperature_slider_state(*args): pass
# def update_top_k_slider_state(*args): pass
# def update_top_p_slider_state(*args): pass
# def update_token_limit_slider_state(*args): pass
# def update_history_turns_slider_state(*args): pass
# def update_system_prompt_input_state(*args): pass
# def update_prefix_user_input_state(*args): pass
# def update_prefix_assistant_input_state(*args): pass
# def update_memory_display_state(*args): pass
# def update_log_display_state(*args): pass
# def update_timer_status_display_state(*args): pass
# def clear_chat_history_button_click(*args): pass
# def save_config_button_click(*args): pass
# def load_config_button_click(*args): pass
# def apply_settings_button_click(*args): pass
# def edit_system_prompt_button_click(*args): pass
# def save_system_prompt_button_click(*args): pass
# def create_new_character_button_click(*args): pass
# def delete_character_button_click(*args): pass
