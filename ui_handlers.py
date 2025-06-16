# ui_handlers.py の【完全修正版】

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
import character_manager
from timers import UnifiedTimer
from character_manager import get_character_files_paths
from gemini_api import configure_google_api, send_to_gemini
from memory_manager import load_memory_data_safe, save_memory_data
from utils import load_chat_log, format_history_for_gradio, save_message_to_log, _get_user_header_from_log, save_log_file

# --- キャラクター管理ハンドラ ---
def handle_add_new_character(character_name: str):
    """gr.promptから受け取った名前で新しいキャラクターを作成する。"""
    if not character_name or not character_name.strip():
        gr.Warning("キャラクター名が入力されていません。")
        char_list = character_manager.get_character_list()
        return gr.update(choices=char_list), gr.update(choices=char_list), gr.update(choices=char_list)

    safe_name = re.sub(r'[\/*?:"<>|]', "", character_name).strip()
    if not safe_name:
        gr.Warning("無効なキャラクター名です。")
        char_list = character_manager.get_character_list()
        return gr.update(choices=char_list), gr.update(choices=char_list), gr.update(choices=char_list)

    if character_manager.ensure_character_files(safe_name):
        gr.Info(f"新しいキャラクター「{safe_name}」さんを迎えました！")
        new_char_list = character_manager.get_character_list()
        # 新しいキャラクターを選択状態にする
        return gr.update(choices=new_char_list, value=safe_name), gr.update(choices=new_char_list), gr.update(choices=new_char_list)
    else:
        gr.Error(f"キャラクター「{safe_name}」の準備に失敗しました。")
        char_list = character_manager.get_character_list()
        return gr.update(choices=char_list), gr.update(choices=char_list), gr.update(choices=char_list)

# --- UI状態更新ハンドラ ---
def update_ui_on_character_change(character_name: Optional[str]):
    """キャラクター変更時にUI全体を更新する。戻り値の数を8個に統一。"""
    if not character_name:
        # キャラクターがいないという異常事態は考えにくいが、安全のためのフォールバック
        return "Default", [], "", None, "{}", "Default", "ログなし", "Default"

    config_manager.save_config("last_character", character_name)
    log_f, _, img_p, mem_p = get_character_files_paths(character_name)

    chat_history = format_history_for_gradio(load_chat_log(log_f, character_name)[-(config_manager.HISTORY_LIMIT * 2):]) if log_f and os.path.exists(log_f) else []

    log_content = ""
    if log_f and os.path.exists(log_f):
        try:
            with open(log_f, "r", encoding="utf-8") as f: log_content = f.read()
        except Exception as e: log_content = f"ログ読込エラー: {e}"

    memory_str = json.dumps(load_memory_data_safe(mem_p), indent=2, ensure_ascii=False)
    profile_image = img_p if img_p and os.path.exists(img_p) else None

    # ★★★ 修正点: 戻り値を8個に固定 ★★★
    return character_name, chat_history, "", profile_image, memory_str, character_name, log_content, character_name

# (以降、元のファイルの関数群は変更なし)
# --- メッセージ処理, アラーム, タイマーなどのハンドラ ---

def handle_message_submission(*args: Any) -> Tuple[List[Dict[str, Any]], gr.update, gr.update, str]:
    (textbox_content, chatbot_history, current_character_name, current_model_name,
     current_api_key_name_state, file_input_list, add_timestamp_checkbox,
     send_thoughts_state, api_history_limit_state) = args
    print(f"\n--- メッセージ送信処理開始 --- {datetime.datetime.now()} ---")
    log_f, sys_p, _, mem_p = None, None, None, None
    error_message = ""
    try:
        if not all([current_character_name, current_model_name, current_api_key_name_state]):
            return chatbot_history, gr.update(), gr.update(value=None), "キャラクター、モデル、APIキーをすべて選択してください。"
        log_f, sys_p, _, mem_p = get_character_files_paths(current_character_name)
        if not all([log_f, sys_p, mem_p]):
            return chatbot_history, gr.update(), gr.update(value=None), f"キャラクター '{current_character_name}' の必須ファイルパス取得に失敗。"
        user_prompt = textbox_content.strip() if textbox_content else ""
        if not user_prompt and not file_input_list:
            return chatbot_history, gr.update(), gr.update(value=None), "メッセージまたはファイルを送信してください。"
        log_message_content = user_prompt
        if file_input_list:
            for file_path in file_input_list:
                log_message_content += f"\n[ファイル添付: {file_path}]"
        user_header = _get_user_header_from_log(log_f, current_character_name)
        timestamp = f"\n{datetime.datetime.now().strftime('%Y-%m-%d (%a) %H:%M:%S')}" if add_timestamp_checkbox else ""
        save_message_to_log(log_f, user_header, log_message_content.strip() + timestamp)
        formatted_files_for_api = []
        if file_input_list:
            for file_path in file_input_list:
                mime_type, _ = mimetypes.guess_type(file_path)
                if mime_type is None: mime_type = "application/octet-stream"
                formatted_files_for_api.append({"path": file_path, "mime_type": mime_type})
        api_response_text, generated_image_path = send_to_gemini(sys_p, log_f, user_prompt, current_model_name, current_character_name, send_thoughts_state, api_history_limit_state, formatted_files_for_api, mem_p)
        if api_response_text or generated_image_path:
            response_to_log = ""
            if generated_image_path:
                response_to_log += f"[Generated Image: {generated_image_path}]\n\n"
            if api_response_text:
                response_to_log += api_response_text
            save_message_to_log(log_f, f"## {current_character_name}:", response_to_log)
    except Exception as e:
        traceback.print_exc()
        error_message = f"メッセージ処理中に予期せぬエラーが発生しました: {e}"
    if log_f and os.path.exists(log_f):
        new_log = load_chat_log(log_f, current_character_name)
        new_hist = format_history_for_gradio(new_log[-(config_manager.HISTORY_LIMIT * 2):])
    else:
        new_hist = chatbot_history
    return new_hist, gr.update(value=""), gr.update(value=None), error_message

DAY_MAP_EN_TO_JA = {"mon": "月", "tue": "火", "wed": "水", "thu": "木", "fri": "金", "sat": "土", "sun": "日"}

def render_alarms_as_dataframe():
    alarms = alarm_manager.get_all_alarms()
    display_data = []
    for alarm in sorted(alarms, key=lambda x: x.get("time", "")):
        days_ja = [DAY_MAP_EN_TO_JA.get(d, d.upper()) for d in alarm.get('days', [])]
        display_data.append({"ID": alarm.get("id"), "状態": alarm.get("enabled", False), "時刻": alarm.get("time"), "曜日": ",".join(days_ja), "キャラ": alarm.get("character"), "テーマ": alarm.get("theme")})
    return pd.DataFrame(display_data, columns=["ID", "状態", "時刻", "曜日", "キャラ", "テーマ"])

def get_display_df(df_with_id: pd.DataFrame):
    if df_with_id is None or df_with_id.empty or 'ID' not in df_with_id.columns:
        return pd.DataFrame(columns=["状態", "時刻", "曜日", "キャラ", "テーマ"])
    return df_with_id[["状態", "時刻", "曜日", "キャラ", "テーマ"]]

def handle_alarm_selection(evt: gr.SelectData, df_with_id: pd.DataFrame):
    if evt.index is None or df_with_id is None or df_with_id.empty: return []
    if isinstance(evt.index, list):
        selected_row_indices = sorted(list(set(evt.index)))
    elif isinstance(evt.index, int):
        selected_row_indices = [evt.index]
    else: selected_row_indices = []
    selected_ids = [str(df_with_id.iloc[i]['ID']) for i in selected_row_indices if 0 <= i < len(df_with_id)]
    return selected_ids

def handle_alarm_selection_and_feedback(evt: gr.SelectData, df_with_id: pd.DataFrame):
    selected_ids = handle_alarm_selection(evt, df_with_id)
    count = len(selected_ids)
    feedback_text = "アラームを選択してください"
    if count == 1:
        feedback_text = f"1 件のアラームを選択中"
    elif count > 1:
        feedback_text = f"{count} 件のアラームを選択中"
    return selected_ids, feedback_text

def toggle_selected_alarms_status(selected_ids: list, target_status: bool):
    if not selected_ids:
        gr.Warning("状態を変更するアラームが選択されていません。")
        return render_alarms_as_dataframe()
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

def update_model_state(model):
    config_manager.save_config("last_model", model)
    return model

def update_api_key_state(api_key_name):
    ok, msg = configure_google_api(api_key_name)
    config_manager.save_config("last_api_key_name", api_key_name)
    if ok: gr.Info(f"APIキー '{api_key_name}' 設定成功。")
    else: gr.Error(f"APIキー '{api_key_name}' 設定失敗: {msg}")
    return api_key_name

def update_timestamp_state(checked): config_manager.save_config("add_timestamp", bool(checked))
def update_send_thoughts_state(checked):
    config_manager.save_config("last_send_thoughts_to_api", bool(checked))
    return bool(checked)
def update_api_history_limit_state(limit_ui_val):
    key = next((k for k,v in config_manager.API_HISTORY_LIMIT_OPTIONS.items() if v==limit_ui_val), "all")
    config_manager.save_config("last_api_history_limit_option", key)
    return key

def reload_chat_log(character_name):
    if not character_name: return [], "キャラクター未選択"
    log_f,_,_,_ = get_character_files_paths(character_name)
    if not log_f or not os.path.exists(log_f): return [], "ログファイルなし"
    history = format_history_for_gradio(load_chat_log(log_f, character_name)[-(config_manager.HISTORY_LIMIT*2):])
    content = ""
    if log_f and os.path.exists(log_f):
        with open(log_f, "r", encoding="utf-8") as f: content = f.read()
    return history, content

def handle_save_log_button_click(character_name, log_content):
    if not character_name: gr.Error("キャラクターが選択されていません。")
    else:
        save_log_file(character_name, log_content)
        gr.Info(f"'{character_name}'のログを保存しました。")

def load_alarm_to_form(selected_ids: list):
    if not selected_ids or len(selected_ids) != 1: return "アラーム追加", "", "", "", [], "08", "00", None
    alarm = alarm_manager.get_alarm_by_id(selected_ids[0])
    if not alarm: return "アラーム追加", "", "", "", [], "08", "00", None
    h, m = alarm.get("time", "08:00").split(":")
    days_ja = [DAY_MAP_EN_TO_JA.get(d) for d in alarm.get("days", []) if DAY_MAP_EN_TO_JA.get(d)]
    return f"アラーム更新", alarm.get("theme", ""), alarm.get("flash_prompt_template", ""), alarm.get("character", ""), days_ja, h, m, selected_ids[0]

def handle_add_or_update_alarm(editing_id, h, m, char, theme, prompt, days):
    if editing_id:
        # これは更新処理
        # 古いアラームを削除し、新しい情報でアラームを追加する
        alarm_manager.delete_alarm(editing_id)
        if alarm_manager.add_alarm(h, m, char, theme, prompt, days):
             gr.Info(f"アラームを更新しました。")
        else:
             gr.Warning("アラームの更新に失敗しました。")
    else:
        # これは新規追加処理
        if alarm_manager.add_alarm(h, m, char, theme, prompt, days):
            gr.Info("アラームを追加しました。")
        else:
            gr.Warning("アラームの追加に失敗しました。")

    df_with_ids = render_alarms_as_dataframe()
    display_df = get_display_df(df_with_ids)
    return display_df, df_with_ids, "アラーム追加", "", "", char, ["月","火","水","木","金","土","日"], "08", "00", None
