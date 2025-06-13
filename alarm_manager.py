# -*- coding: utf-8 -*-
import os
import json
import re
import uuid
import threading
import schedule
import time
import datetime
import traceback
import requests
import gradio as gr # Gradio UI関連の応答を返すため
# config_manager モジュール全体をインポート
import config_manager
from character_manager import get_character_files_paths
# gemini_api モジュール全体をインポート
import gemini_api
from utils import save_message_to_log

# --- アラーム関連グローバル変数 ---
alarms_data_global = []
alarm_thread_stop_event = threading.Event()

# --- アラームデータ管理関数 ---
def load_alarms():
    global alarms_data_global
    if not os.path.exists(config_manager.ALARMS_FILE): # config_manager経由で定数を参照
        alarms_data_global = []
        save_alarms()
        return alarms_data_global
    try:
        with open(config_manager.ALARMS_FILE, "r", encoding="utf-8") as f: # config_manager経由で定数を参照
            loaded_data = json.load(f)
            if not isinstance(loaded_data, list):
                print(f"警告: {config_manager.ALARMS_FILE} の形式が不正です。空のリストで初期化します。")
                alarms_data_global = []; return alarms_data_global
            valid_alarms = []
            default_days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
            for alarm in loaded_data:
                if isinstance(alarm, dict) and \
                   all(k in alarm for k in ["id", "time", "character", "theme", "enabled"]) and \
                   re.match(r"^\d{2}:\d{2}$", alarm.get("time", "")):
                    if "days" not in alarm:
                        alarm["days"] = default_days
                    valid_alarms.append(alarm)
                else: print(f"警告: 不正な形式のアラームデータをスキップしました: {alarm}")
            alarms_data_global = sorted(valid_alarms, key=lambda x: x.get("time", ""))
            return alarms_data_global
    except json.JSONDecodeError as e:
        print(f"アラームファイル ({config_manager.ALARMS_FILE}) のJSONデコードエラー: {e}")
        alarms_data_global = []; return alarms_data_global
    except Exception as e:
        print(f"アラーム読込中に予期せぬエラーが発生しました: {e}"); traceback.print_exc()
        alarms_data_global = []; return alarms_data_global

def save_alarms():
    global alarms_data_global
    try:
        alarms_to_save = sorted(alarms_data_global, key=lambda x: x.get("time", ""))
        with open(config_manager.ALARMS_FILE, "w", encoding="utf-8") as f: # config_manager経由で定数を参照
            json.dump(alarms_to_save, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"アラーム保存エラー: {e}"); traceback.print_exc()

# Day mapping from Japanese to English short names
DAY_MAP_JA_TO_EN = {
    "月": "mon", "火": "tue", "水": "wed", "木": "thu",
    "金": "fri", "土": "sat", "日": "sun"
}

def add_alarm(hour, minute, character, theme, flash_prompt, days_ja): # Added days_ja
    global alarms_data_global
    if not character:
        gr.Error("キャラクターを選択してください。")
        return render_alarm_list_for_checkboxgroup()
    # デフォルトテーマを設定
    theme_stripped = theme.strip() if theme else "時間になりました"
    prompt_stripped = flash_prompt.strip() if flash_prompt else None
    if not theme_stripped and not prompt_stripped:
        gr.Error("「テーマ」または「カスタムプロンプト」のいずれかを入力してください。")
        return render_alarm_list_for_checkboxgroup()
    time_str = f"{hour}:{minute}"
    # Convert Japanese day names to English short names
    days_en = [DAY_MAP_JA_TO_EN.get(day_ja, "") for day_ja in days_ja if DAY_MAP_JA_TO_EN.get(day_ja)]
    if not days_en: # Fallback if conversion results in empty or invalid days
        days_en = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        gr.Warning("曜日設定が無効だったため、全て選択(デフォルト)として登録します。")


    new_alarm = {
        "id": str(uuid.uuid4()), "time": time_str, "character": character,
        "theme": theme_stripped, "enabled": True, "days": days_en, # Added days
        "flash_prompt_template": prompt_stripped if prompt_stripped else None
    }
    alarms_data_global.append(new_alarm)
    save_alarms()
    print(f"アラーム追加 (有効): {new_alarm['id']} ({time_str}, {character}, Theme: '{theme_stripped}', Days: {days_en}, CustomPrompt: {'あり' if prompt_stripped else 'なし'})")
    gr.Info("アラームを追加しました。")
    # The return value of add_alarm will be handled in log2gemini.py to trigger a refresh
    # of the interactive_alarm_list_area, likely by returning None or specific UI updates.
    # For now, let's make it return None as render_alarm_list_for_checkboxgroup is being removed.
    return None

# --- New Interactive Alarm List Handlers & Renderer ---

# These handler functions will be called by Gradio events.
# They perform the backend action and then return the updated UI components.

def handle_toggle_alarm(alarm_id: str):
    """Calls toggle_alarm_enabled and returns the updated alarm list UI."""
    print(f"UI Event: Toggling alarm {alarm_id}") # For easier debugging
    toggle_alarm_enabled(alarm_id)
    return render_interactive_alarm_list()

def handle_delete_alarm(alarm_id: str):
    """Calls delete_alarm_interactive and returns the updated alarm list UI."""
    print(f"UI Event: Deleting alarm {alarm_id}") # For easier debugging
    delete_alarm_interactive(alarm_id)
    return render_interactive_alarm_list()

# Original backend logic functions (no longer directly called from Gradio UI in this new model)
def toggle_alarm_enabled(alarm_id: str):
    """Toggles the enabled status of an alarm."""
    global alarms_data_global
    found_alarm = None
    for alarm in alarms_data_global:
        if alarm.get("id") == alarm_id:
            alarm["enabled"] = not alarm.get("enabled", False)
            found_alarm = alarm
            break
    if found_alarm:
        save_alarms()
        status = "有効" if found_alarm["enabled"] else "無効"
        print(f"アラーム状態変更: ID {alarm_id} を{status}にしました。")
    else:
        print(f"警告: アラームID {alarm_id} が見つかりませんでした (トグル操作不可)。")
    # This function itself does not return UI components.
    # This function is now primarily for backend logic.

def delete_alarm_interactive(alarm_id: str):
    """Deletes an alarm interactively (backend logic)."""
    global alarms_data_global
    original_len = len(alarms_data_global)
    alarms_data_global = [alarm for alarm in alarms_data_global if alarm.get("id") != alarm_id]
    if len(alarms_data_global) < original_len:
        save_alarms()
        print(f"アラーム削除(対話的): ID {alarm_id}")
    else:
        print(f"警告: アラームID {alarm_id} が見つかりませんでした (対話的削除不可)。")
    # This function is now primarily for backend logic.


def render_interactive_alarm_list(interactive_alarm_list_area_component=None):
    """Renders the list of alarms with interactive components and wires their events."""
    # interactive_alarm_list_area_component is the gr.Column in log2gemini.py that will be updated.

    _ = load_alarms() # Ensure alarms_data_global is fresh.

    # Sort alarms by time for consistent display
    # Make sure to use alarms_data_global after load_alarms() call
    sorted_alarms = sorted(alarms_data_global, key=lambda x: x.get("time", ""))

    if not sorted_alarms:
        return [gr.Markdown("設定済みのアラームはありません。")]

    alarm_rows = []
    for alarm_data in sorted_alarms: # Iterate over the sorted list
        alarm_id_str = alarm_data.get("id") # Ensure it's a string for lambda capture

        with gr.Row(elem_id=f"alarm_row_{alarm_id_str}") as row:
            switch = gr.Switch(value=alarm_data.get("enabled", False), label="有効", scale=1, elem_id=f"enable_switch_{alarm_id_str}")

            days_str = ", ".join(alarm_data.get("days", []))
            theme_str = alarm_data.get("theme", "")
            theme_display = theme_str[:30] + '...' if len(theme_str) > 30 else theme_str
            details_md_val = f"{alarm_data.get('time')} [{days_str}] {alarm_data.get('character')} - \"{theme_display}\""
            gr.Markdown(value=details_md_val, scale=3, elem_id=f"alarm_details_{alarm_id_str}")

            delete_button = gr.Button("削除", variant="stop", scale=1, elem_id=f"delete_button_{alarm_id_str}")

            # Event wiring:
            # The .then(None, js=...) is a way to trigger updates on other components without a direct Python output from the handler to those specific components.
            # The actual update mechanism involves these handlers returning the new list,
            # and log2gemini.py directing that output to the interactive_alarm_list_area.
            if interactive_alarm_list_area_component: # Check if the target component is provided
                switch.change(
                    fn=lambda current_alarm_id=alarm_id_str: handle_toggle_alarm(current_alarm_id),
                    inputs=[], # No direct inputs from the switch to the handler beyond what lambda captures
                    outputs=[interactive_alarm_list_area_component] # Target the column for update
                )
                delete_button.click(
                    fn=lambda current_alarm_id=alarm_id_str: handle_delete_alarm(current_alarm_id),
                    inputs=[], # No direct inputs from the button to the handler
                    outputs=[interactive_alarm_list_area_component] # Target the column for update
                )
            else: # Fallback or initial rendering without direct output wiring here
                  # This path might be taken if render_interactive_alarm_list is called directly
                  # without being the result of an event that has interactive_alarm_list_area_component as an output.
                switch.change(
                    fn=lambda current_alarm_id=alarm_id_str: handle_toggle_alarm(current_alarm_id),
                    inputs=[]
                    # Outputs will be handled by log2gemini.py's demo.load or similar
                )
                delete_button.click(
                    fn=lambda current_alarm_id=alarm_id_str: handle_delete_alarm(current_alarm_id),
                    inputs=[]
                    # Outputs will be handled by log2gemini.py
                )


        alarm_rows.append(row)

    return alarm_rows if alarm_rows else [gr.Markdown("設定済みのアラームはありません。")]

# Remove old functions that are no longer needed with the new interactive list
# def delete_selected_alarms(selected_alarm_ids): ...
# def render_alarm_list_for_checkboxgroup(): ...


# --- Webhook通知関数 ---
def send_webhook_notification(webhook_url, message_text):
    """Webhook URLにシンプルなテキストメッセージをPOSTする関数"""
    if not webhook_url or not message_text:
        # デバッグ用print削除
        return False
    headers = {'Content-Type': 'application/json'}
    payload = json.dumps({'content': message_text})
    # デバッグ用print削除
    try:
        response = requests.post(webhook_url, headers=headers, data=payload, timeout=10)
        response.raise_for_status()
        print(f"Webhook通知送信成功 (URL: {webhook_url[:30]}...)") # 成功ログは残す
        return True
    except requests.exceptions.RequestException as e:
        print(f"Webhook通知送信エラー (URL: {webhook_url[:30]}...): {e}")
        return False
    except Exception as e:
        print(f"Webhook通知中に予期せぬエラー (URL: {webhook_url[:30]}...): {e}")
        traceback.print_exc()
        return False

# --- アラームトリガーとスケジューリング ---
def trigger_alarm(alarm_config, current_api_key_name, webhook_url):
    # デバッグ用print削除
    c = alarm_config.get("character")
    t = alarm_config.get("theme")
    tm = alarm_config.get("time")
    fp = alarm_config.get("flash_prompt_template")
    id = alarm_config.get("id") # これは必ず存在するはず
    print(f"⏰ アラーム発火！ ID: {id}, 時刻: {tm}, キャラクター: {c}, テーマ: '{t}' (カスタムP: {'あり' if fp else 'なし'})") # 発火ログは残す

    log_f, _, _, _ = get_character_files_paths(c)
    if not log_f:
        # デバッグ用print削除
        print(f"エラー: アラーム'{id}'のキャラクター'{c}'のログファイルが見つかりません。処理をスキップします。") # エラーログは残す
        return

    a_mod = config_manager.initial_alarm_model_global
    a_hist = config_manager.initial_alarm_api_history_turns_global
    # デバッグ用print削除

    if not a_mod:
        # デバッグ用print削除
        print(f"エラー: config.jsonでアラーム用モデル('alarm_model')が設定されていません。") # エラーログは残す
        return
    if not current_api_key_name:
        # デバッグ用print削除
        print(f"エラー: 有効なAPIキー名が設定されていません。") # エラーログは残す
        return

    dummy_user_theme = t if t else (fp if fp else "(テーマ未設定)")
    dummy_user_message = f"（システムアラーム：{tm} {dummy_user_theme}）"
    system_header = "## システム(アラーム):"

    # アラームのテーマが未設定の場合にデフォルトテーマを適用
    if not alarm_config.get("theme"):
        if alarm_config.get("id") == "通常タイマー":
            alarm_config["theme"] = "時間になりました"
        elif alarm_config.get("id") == "作業タイマー":
            alarm_config["theme"] = "作業終了アラーム"
        elif alarm_config.get("id") == "休憩タイマー":
            alarm_config["theme"] = "休憩終了アラーム"

    theme = alarm_config.get("theme")
    flash_prompt = alarm_config.get("flash_prompt_template")
    # if not theme and not flash_prompt:
    #     print("エラー: アラームのテーマもカスタムプロンプトも設定されていません。応答生成をスキップします。")
    #     return

    # デバッグ用print削除
    response_text = gemini_api.send_alarm_to_gemini(c, t, fp, a_mod, current_api_key_name, log_f, a_hist)
    # デバッグ用print削除

    if response_text and isinstance(response_text, str) and not response_text.startswith("【アラームエラー】"):
        # デバッグ用print削除
        save_message_to_log(log_f, system_header, dummy_user_message)
        save_message_to_log(log_f, f"## {c}:", response_text)
        print(f"アラームログ記録完了 (ID:{id})") # ログ記録完了ログは残す

        if webhook_url:
            # デバッグ用print削除
            notification_message = f"⏰  {c}\n\n{response_text}\n"
            success = send_webhook_notification(webhook_url, notification_message)
            # デバッグ用print削除
        else:
            # デバッグ用print削除
            print("情報: Webhook URLが設定されていないため、外部通知はスキップします。") # スキップ情報は残す
    else:
        # デバッグ用print削除
        print(f"警告: アラーム応答の生成に失敗したか、エラーが返されたため、ログ記録と通知をスキップします (ID:{id})。応答: {response_text}") # 警告ログは残す


def check_alarms():
    now_dt = datetime.datetime.now()
    now_t = now_dt.strftime("%H:%M")
    current_day_short = now_dt.strftime('%a').lower() # Example: "mon", "tue"
    # デバッグ用print削除 (毎分出力されるため)

    current_api_key = config_manager.initial_api_key_name_global
    webhook_url_to_use = config_manager.initial_notification_webhook_url_global
    alarms = load_alarms() # アラームリストを毎回再読み込み
    # デバッグ用print削除

    if not current_api_key:
        # デバッグ用print削除
        return # APIキーがなければこの回のチェックはスキップ

    triggered_count = 0
    for a in alarms:
        alarm_time = a.get("time")
        is_enabled = a.get("enabled")
        alarm_id_for_log = a.get('id', 'N/A')
        alarm_days = a.get("days", []) # Get the list of days, default to empty list if missing

        # Gracefully handle if alarm_days is None (though load_alarms should prevent this)
        if alarm_days is None:
            alarm_days = []

        if not alarm_days:
            # print(f"情報: アラーム (ID:{alarm_id_for_log}) に曜日設定がないためスキップします。") # Optionally log this
            continue # Skip if no days are set for the alarm

        if is_enabled and alarm_time == now_t and current_day_short in alarm_days:
            # デバッグ用print削除
            triggered_count += 1
            try:
                # 必要な情報を渡してトリガー
                trigger_alarm(a, current_api_key, webhook_url_to_use)
            except Exception as e:
                print(f"アラーム処理中に予期せぬエラー (ID:{alarm_id_for_log})") # 簡略化されたエラーログを残す
                traceback.print_exc() # スタックトレースは残す

    # デバッグ用print削除


def schedule_thread_function():
    global alarm_thread_stop_event
    print("アラームスケジューラスレッドを開始します。") # スレッド開始ログは残す
    try:
        # デバッグ用print削除
        check_alarms() # 初回実行
        # デバッグ用print削除
    except Exception as e:
        print(f"初回アラームチェック中にエラー: {e}") # エラーログは残す
        traceback.print_exc()

    # デバッグ用print削除
    schedule.every().minute.at(":00").do(check_alarms)

    while not alarm_thread_stop_event.is_set():
        try:
            schedule.run_pending()
        except Exception as e:
            print(f"スケジュール実行中にエラー: {e}") # エラーログは残す
            traceback.print_exc()
        time.sleep(1) # CPU負荷軽減

    print("アラームスケジューラスレッドが停止しました。") # スレッド停止ログは残す