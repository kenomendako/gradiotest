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
import config_manager
from character_manager import get_character_files_paths
import gemini_api  # generate_alarm_message を使わなくなるが、他の箇所で必要になる可能性を考慮し残す
import utils

# --- アラーム関連グローバル変数 ---
alarms_data_global = []
alarm_thread_stop_event = threading.Event()

# --- アラームデータ管理関数 ---
def load_alarms():
    global alarms_data_global
    if not os.path.exists(config_manager.ALARMS_FILE):
        alarms_data_global = []
        save_alarms()
        return alarms_data_global
    try:
        with open(config_manager.ALARMS_FILE, "r", encoding="utf-8") as f:
            loaded_data = json.load(f)
            if not isinstance(loaded_data, list):
                alarms_data_global = []
                return alarms_data_global
            # 必須キーのチェックを緩和し、多様なアラーム形式に対応
            valid_alarms = [a for a in loaded_data if isinstance(a, dict) and "id" in a and "time" in a]
            alarms_data_global = sorted(valid_alarms, key=lambda x: x.get("time", ""))
            return alarms_data_global
    except Exception as e:
        print(f"アラーム読込エラー: {e}"); traceback.print_exc()
        alarms_data_global = []
        return alarms_data_global

def save_alarms():
    global alarms_data_global
    try:
        alarms_to_save = sorted(alarms_data_global, key=lambda x: x.get("time", ""))
        with open(config_manager.ALARMS_FILE, "w", encoding="utf-8") as f:
            json.dump(alarms_to_save, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"アラーム保存エラー: {e}"); traceback.print_exc()

def add_alarm_entry(alarm_data: dict):
    """新しいアラームデータをリストに追加して保存する中央関数。"""
    global alarms_data_global
    if not isinstance(alarm_data, dict) or "id" not in alarm_data:
        print(f"エラー: 無効なアラームデータです: {alarm_data}")
        return False
    alarms_data_global.append(alarm_data)
    save_alarms()
    return True

def delete_alarm(alarm_id: str):
    global alarms_data_global
    original_len = len(alarms_data_global)
    alarms_data_global = [alarm for alarm in alarms_data_global if alarm.get("id") != alarm_id]
    if len(alarms_data_global) < original_len:
        save_alarms()
        print(f"アラーム削除: ID {alarm_id}")
        return True
    else:
        print(f"警告: アラームID {alarm_id} が見つかりませんでした (削除不可).")
        return False

# ... (get_all_alarms, get_alarm_by_id, send_webhook_notification は変更不要) ...
def get_all_alarms():
    load_alarms()
    return alarms_data_global
def get_alarm_by_id(alarm_id: str):
    load_alarms()
    return next((alarm for alarm in alarms_data_global if alarm.get("id") == alarm_id), None)
def send_webhook_notification(webhook_url, message_text):
    if not webhook_url or not message_text: return False
    headers = {'Content-Type': 'application/json'}
    payload = json.dumps({'content': message_text})
    try:
        response = requests.post(webhook_url, headers=headers, data=payload, timeout=10)
        response.raise_for_status()
        print(f"Webhook通知送信成功 (URL: {webhook_url[:30]}...)")
        return True
    except requests.exceptions.RequestException as e:
        print(f"Webhook通知送信エラー: {e}")
        return False

# ★★★ ここからが修正の核心 ★★★
def trigger_alarm(alarm_config, current_api_key_name, webhook_url):
    char_name = alarm_config.get("character")
    alarm_id = alarm_config.get("id")

    # 1. 保存されたメッセージを直接取得
    response_text = alarm_config.get("alarm_message")

    # 2. メッセージがない場合、古い形式や手動設定へのフォールバック
    if not response_text:
        response_text = alarm_config.get("theme", "時間になりました")

    print(f"⏰ アラーム発火. ID: {alarm_id}, キャラクター: {char_name}, メッセージ: '{response_text}'")

    log_f, _, _, _, _ = get_character_files_paths(char_name)
    if not log_f:
        print(f"エラー: アラーム'{alarm_id}'のキャラクター'{char_name}'のログファイルが見つかりません。")
        return

    # 3. API呼び出しは行わず、ログ記録と通知を直接実行
    if response_text:
        dummy_user_message = f"（システムアラーム：{alarm_config.get('time')}）"
        system_header = "## システム(アラーム):"
        utils.save_message_to_log(log_f, system_header, dummy_user_message)
        utils.save_message_to_log(log_f, f"## {char_name}:", response_text)
        print(f"アラームログ記録完了 (ID:{alarm_id})")

        if webhook_url:
            notification_message = f"⏰  {char_name}\n\n{response_text}\n"
            send_webhook_notification(webhook_url, notification_message)
    else:
        print(f"警告: アラームメッセージが空のため、処理をスキップします (ID:{alarm_id}).")

# ★★★ 修正ここまで ★★★

def check_alarms():
    now_dt = datetime.datetime.now()
    now_t = now_dt.strftime("%H:%M")
    current_day_short = now_dt.strftime('%a').lower()

    current_api_key = config_manager.initial_api_key_name_global
    webhook_url_to_use = config_manager.initial_notification_webhook_url_global

    current_alarms = load_alarms()

    alarms_to_trigger = []
    remaining_alarms = []

    for a in current_alarms:
        alarm_time = a.get("time")
        is_enabled = a.get("enabled", True) # デフォルト有効
        alarm_days = a.get("days", [])

        # 日付チェックロジック
        is_today = False
        alarm_date_str = a.get("date")
        if alarm_date_str:
            try:
                alarm_date = datetime.datetime.strptime(alarm_date_str, "%Y-%m-%d").date()
                if alarm_date == now_dt.date():
                    is_today = True
            except (ValueError, TypeError):
                 # 日付形式が不正、または存在しない場合は曜日チェックにフォールバック
                 is_today = current_day_short in alarm_days
        else:
             # 日付指定がない場合は曜日で判断
             is_today = not alarm_days or current_day_short in alarm_days

        if is_enabled and alarm_time == now_t and is_today:
            alarms_to_trigger.append(a)
            # 繰り返しでないアラームは実行後にリストから削除する
            if not a.get("days"):
                print(f"  - 単発アラーム {a.get('id')} は実行後に削除されます。")
                continue # remaining_alarms には追加しない
        remaining_alarms.append(a)

    if len(current_alarms) != len(remaining_alarms):
        global alarms_data_global
        alarms_data_global = remaining_alarms
        save_alarms()

    if not current_api_key: return

    for alarm_to_run in alarms_to_trigger:
        try:
            trigger_alarm(alarm_to_run, current_api_key, webhook_url_to_use)
        except Exception as e:
            print(f"アラーム処理中に予期せぬエラー (ID:{alarm_to_run.get('id', 'N/A')})")
            traceback.print_exc()

# ... (schedule_thread_function, start/stop_alarm_scheduler_thread は変更不要) ...
def schedule_thread_function():
    global alarm_thread_stop_event
    print("アラームスケジューラスレッドを開始します.")
    schedule.every().minute.at(":00").do(check_alarms)
    while not alarm_thread_stop_event.is_set():
        schedule.run_pending()
        time.sleep(1)
    print("アラームスケジューラスレッドが停止しました.")
def start_alarm_scheduler_thread():
    global alarm_thread_stop_event
    alarm_thread_stop_event.clear()
    config_manager.load_config()
    if not hasattr(start_alarm_scheduler_thread, "scheduler_thread") or not start_alarm_scheduler_thread.scheduler_thread.is_alive():
        thread = threading.Thread(target=schedule_thread_function, daemon=True)
        thread.start()
        start_alarm_scheduler_thread.scheduler_thread = thread
        print("アラームスケジューラスレッドを起動しました.")
def stop_alarm_scheduler_thread():
    global alarm_thread_stop_event
    if hasattr(start_alarm_scheduler_thread, "scheduler_thread") and start_alarm_scheduler_thread.scheduler_thread.is_alive():
        print("アラームスケジューラスレッドに停止信号を送信します...")
        alarm_thread_stop_event.set()
        start_alarm_scheduler_thread.scheduler_thread.join(timeout=5)
