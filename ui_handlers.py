# ui_handlers.py ファイル全体を、この内容で置き換えてください

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
import mimetypes

# --- モジュールインポート ---
import config_manager
import alarm_manager
from timers import UnifiedTimer
from character_manager import get_character_files_paths
from gemini_api import configure_google_api, send_to_gemini
from memory_manager import load_memory_data_safe, save_memory_data
from utils import load_chat_log, format_history_for_gradio, save_message_to_log, _get_user_header_from_log, save_log_file, format_response_for_display

# --- プライベートヘルパー関数 (リファクタリングで作成) ---

def _validate_inputs(character_name: Optional[str], model_name: Optional[str], api_key_name: Optional[str]) -> Optional[str]:
    """入力のバリデーションを行い、問題があればエラーメッセージを返す。"""
    if not all([character_name, model_name, api_key_name]):
        return "キャラクター、モデル、APIキーをすべて選択してください。"
    return None

def _prepare_user_turn(
    log_file_path: str,
    character_name: str,
    user_prompt: str,
    add_timestamp: bool,
    file_input_list: Optional[List[str]]
) -> Tuple[str, List[Dict[str, str]]]:
    """ユーザーのターンを準備し、ログに記録し、API用の添付ファイルリストを返す。"""
    # ユーザーヘッダーを取得し、メッセージをログに記録
    user_header = _get_user_header_from_log(log_file_path, character_name)
    timestamp = f"
{datetime.datetime.now().strftime('%Y-%m-%d (%a) %H:%M:%S')}" if add_timestamp else ""
    save_message_to_log(log_file_path, user_header, user_prompt + timestamp)

    # 添付ファイルをAPIが期待する形式に変換
    formatted_files_for_api = []
    if file_input_list:
        for file_path in file_input_list:
            mime_type, _ = mimetypes.guess_type(file_path)
            if mime_type is None:
                mime_type = "application/octet-stream"
            formatted_files_for_api.append({"path": file_path, "mime_type": mime_type})
            print(f"情報: ファイル '{os.path.basename(file_path)}' (MIME: {mime_type}) をAPI送信用に準備しました。")

    return user_prompt, formatted_files_for_api

def _call_gemini_and_handle_response(
    system_prompt_path: str,
    log_file_path: str,
    user_prompt: str,
    model_name: str,
    character_name: str,
    send_thoughts_state: bool,
    api_history_limit_state: str,
    formatted_files: List[Dict[str, str]],
    memory_json_path: str
) -> None:
    """Gemini APIを呼び出し、応答をログに記録する。"""
    api_response_text, generated_image_path = send_to_gemini(
        system_prompt_path, log_file_path, user_prompt, model_name, character_name,
        send_thoughts_state, api_history_limit_state, formatted_files, memory_json_path
    )
    if api_response_text or generated_image_path:
        response_to_log = ""
        if generated_image_path:
            response_to_log += f"[Generated Image: {generated_image_path}]

"
        if api_response_text:
            response_to_log += api_response_text
        save_message_to_log(log_file_path, f"## {character_name}:", response_to_log)
    else:
        print("警告: APIから有効な応答がありませんでした。")

# --- メインのメッセージ処理関数 (リファクタリング後) ---

def handle_message_submission(*args):
    """
    ユーザーからのメッセージ送信を処理するメインハンドラ（監督役）。
    """
    (textbox_content, chatbot_history, current_character_name, current_model_name,
     current_api_key_name_state, file_input_list, add_timestamp_checkbox,
     send_thoughts_state, api_history_limit_state) = args

    print(f"
--- メッセージ送信処理開始 --- {datetime.datetime.now()} ---")

    try:
        # 1. バリデーション
        error_msg = _validate_inputs(current_character_name, current_model_name, current_api_key_name_state)
        if error_msg:
            return chatbot_history, gr.update(), gr.update(value=None), error_msg

        log_f, sys_p, _, mem_p = get_character_files_paths(current_character_name)
        if not all([log_f, sys_p, mem_p]):
            return chatbot_history, gr.update(), gr.update(value=None), f"キャラクター '{current_character_name}' の必須ファイルパス取得に失敗。"

        user_prompt_str = textbox_content.strip() if textbox_content else ""
        if not user_prompt_str and not file_input_list:
            return chatbot_history, gr.update(), gr.update(value=None), "メッセージまたはファイルを送信してください。"

        # 2. ユーザーのターンを準備・記録
        user_prompt, formatted_files = _prepare_user_turn(
            log_f, current_character_name, user_prompt_str, add_timestamp_checkbox, file_input_list
        )

        # 3. API呼び出しと応答処理
        _call_gemini_and_handle_response(
            sys_p, log_f, user_prompt, current_model_name, current_character_name,
            send_thoughts_state, api_history_limit_state, formatted_files, mem_p
        )

    except Exception as e:
        traceback.print_exc()
        # UIにエラーメッセージを返す
        new_hist = format_history_for_gradio(load_chat_log(log_f, current_character_name)[-(config_manager.HISTORY_LIMIT * 2):])
        return new_hist, gr.update(value=""), gr.update(value=None), f"メッセージ処理中に予期せぬエラーが発生しました: {e}"

    # 4. UI更新
    new_log = load_chat_log(log_f, current_character_name)
    new_hist = format_history_for_gradio(new_log[-(config_manager.HISTORY_LIMIT * 2):])
    return new_hist, gr.update(value=""), gr.update(value=None), ""


# --- (以降の関数は、あなたのファイルにあるものと同じですが、念のため全て含めます) ---

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
    return df_with_id[["状態", "時刻", "曜日", "キャラ", "テーマ"]]

# --- アラームDataframeイベントハンドラ ---
def handle_alarm_selection(evt: gr.SelectData, df_with_id: pd.DataFrame):
    if evt.index is None or df_with_id is None or df_with_id.empty: return []
    selected_row_indices = []
    if isinstance(evt.index, list):
        selected_row_indices = sorted(list(set(evt.index)))
    elif isinstance(evt.index, int):
        selected_row_indices = [evt.index]
    selected_ids = []
    for row_index in selected_row_indices:
        if 0 <= row_index < len(df_with_id):
            selected_ids.append(str(df_with_id.iloc[row_index]['ID']))
    return selected_ids

def toggle_selected_alarms_status(selected_ids: list, target_status: bool):
    if not selected_ids:
        gr.Warning("状態を変更するアラームが選択されていません。")
        return render_alarms_as_dataframe()
    changed_count = 0
    status_text = "有効" if target_status else "無効"
    for alarm_id in selected_ids:
        alarm = alarm_manager.get_alarm_by_id(alarm_id)
        if alarm and alarm.get("enabled") != target_status:
            if alarm_manager.toggle_alarm_enabled(alarm_id):
                changed_count += 1
    if changed_count > 0:
        gr.Info(f"{changed_count}件のアラームを「{status_text}」に変更しました。")
    else:
        gr.Info("状態の変更はありませんでした。")
    return render_alarms_as_dataframe()

def handle_delete_selected_alarms(selected_ids: list):
    if not selected_ids:
        gr.Warning("削除するアラームが選択されていません。")
    else:
        deleted_count = 0
        for alarm_id_str in selected_ids:
            if alarm_manager.delete_alarm(str(alarm_id_str)):
                deleted_count +=1
        if deleted_count > 0:
            gr.Info(f"{deleted_count}件のアラームを削除しました。")
        else:
            gr.Warning("選択されたアラームを削除できませんでした。")
    return render_alarms_as_dataframe()

# --- タイマーイベントハンドラ ---
def handle_timer_submission(timer_type, duration, work_duration, break_duration, cycles, character_name, work_theme, break_theme, api_key_name, webhook_url, normal_timer_theme):
    if not character_name or not api_key_name:
        return "エラー：キャラクターとAPIキーを選択してください。"
    try:
        status_message = ""
        if timer_type == "通常タイマー":
            if not (duration and float(duration) > 0):
                return "エラー：通常タイマーの時間を正しく入力してください。"
            status_message = f"{duration}分の通常タイマーを開始しました。"
        elif timer_type == "ポモドーロタイマー":
            if not (work_duration and float(work_duration) > 0 and
                    break_duration and float(break_duration) > 0 and
                    cycles and int(cycles) > 0):
                return "エラー：ポモドーロの各項目を正しく入力してください。"
            status_message = f"{work_duration}分作業/{break_duration}分休憩のポモドーロタイマーを開始。"
        else:
            return "エラー：不明なタイマータイプです。"
        unified_timer = UnifiedTimer(timer_type, float(duration or 0), float(work_duration or 0), float(break_duration or 0), int(cycles or 0), character_name, work_theme, break_theme, api_key_name, webhook_url, normal_timer_theme)
        unified_timer.start()
        gr.Info(f"{timer_type}を開始しました。")
        return status_message
    except ValueError as ve:
        error_msg = f"タイマー設定値エラー: {ve}"
        traceback.print_exc()
        return error_msg
    except Exception as e:
        error_msg = f"タイマー開始エラー: {e}"
        traceback.print_exc()
        return error_msg

# --- UI状態更新ハンドラ ---
def update_ui_on_character_change(character_name: Optional[str]):
    if not character_name:
        return None, [], "", None, "{}", None, "キャラ未選択"
    config_manager.save_config("last_character", character_name)
    log_f, _, img_p, mem_p = get_character_files_paths(character_name)
    chat_history = format_history_for_gradio(load_chat_log(log_f, character_name)[-(config_manager.HISTORY_LIMIT * 2):]) if log_f and os.path.exists(log_f) else []
    log_content = ""
    if log_f and os.path.exists(log_f):
        try:
            with open(log_f, "r", encoding="utf-8") as f: log_content = f.read()
        except Exception as e_log: log_content = f"ログファイル読込エラー: {e_log}"
    memory_str = json.dumps(load_memory_data_safe(mem_p), indent=2, ensure_ascii=False)
    profile_image = img_p if img_p and os.path.exists(img_p) else None
    return character_name, chat_history, "", profile_image, memory_str, character_name, log_content

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
    key = next((k for k, v in config_manager.API_HISTORY_LIMIT_OPTIONS.items() if v == limit_ui_val), "all")
    config_manager.save_config("last_api_history_limit_option", key)
    return key

def reload_chat_log(character_name):
    if not character_name: return [], "キャラクター未選択"
    log_f,_,_,_ = get_character_files_paths(character_name)
    if not log_f or not os.path.exists(log_f): return [], "ログファイルなし"
    history = format_history_for_gradio(load_chat_log(log_f, character_name)[-(config_manager.HISTORY_LIMIT * 2):])
    content = ""
    try:
        with open(log_f, "r", encoding="utf-8") as f: content = f.read()
    except Exception as e: content = f"ログファイル読込エラー: {e}"
    gr.Info(f"'{character_name}'のログを再読み込みしました。")
    return history, content

def handle_save_log_button_click(character_name, log_content):
    if not character_name:
        gr.Error("キャラクターが選択されていません。")
        return
    try:
        save_log_file(character_name, log_content)
        gr.Info(f"'{character_name}'のログを保存しました。")
    except Exception as e:
        gr.Error(f"ログ保存エラー: {e}")
        traceback.print_exc()

def load_alarm_to_form(selected_ids: list):
    if not selected_ids or len(selected_ids) != 1:
        return "アラーム追加", "", "", "", [], "08", "00", None
    alarm_id = selected_ids[0]
    alarm = alarm_manager.get_alarm_by_id(alarm_id)
    if not alarm:
        return "アラーム追加", "", "", "", [], "08", "00", None
    hour, minute = alarm.get("time", "08:00").split(":")
    theme = alarm.get("theme", "")
    prompt = alarm.get("flash_prompt_template", "")
    character = alarm.get("character", "")
    days_en = alarm.get("days", [])
    days_ja = [DAY_MAP_EN_TO_JA.get(d) for d in days_en if DAY_MAP_EN_TO_JA.get(d)]
    return f"アラーム更新 (ID: {alarm_id[:8]})", theme, prompt, character, days_ja, hour, minute, alarm_id

def handle_add_or_update_alarm(editing_alarm_id, hour, minute, char, theme, prompt, days):
    if editing_alarm_id:
        try:
            if alarm_manager.add_alarm(hour, minute, char, theme, prompt, days):
                alarm_manager.delete_alarm(editing_alarm_id)
                gr.Info(f"アラーム(ID: {editing_alarm_id[:8]})を更新しました。")
            else:
                gr.Warning("アラームの更新に失敗しました（データ検証エラー）。")
        except Exception as e:
            gr.Error(f"アラーム更新処理中にエラー: {e}")
    else:
        if alarm_manager.add_alarm(hour, minute, char, theme, prompt, days):
            gr.Info("アラームを追加しました。")
        else:
            gr.Warning("アラームの追加に失敗しました。")
    new_df_with_ids = render_alarms_as_dataframe()
    new_display_df = get_display_df(new_df_with_ids)
    return new_display_df, new_df_with_ids, "アラーム追加", "", "", char, ["月","火","水","木","金","土","日"], "08", "00", None
