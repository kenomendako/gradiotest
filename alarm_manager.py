# alarm_manager.py の内容を、以下のコードで完全に置き換えてください

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
import gemini_api
import utils

try:
    from plyer import notification
    PLYER_AVAILABLE = True
except ImportError:
    print("情報: 'plyer'ライブラリが見つかりません。PCデスクトップ通知機能は無効になります。")
    print(" -> pip install plyer でインストールできます。")
    PLYER_AVAILABLE = False

# --- アラーム関連グローバル変数 ---
alarms_data_global = []
alarm_thread_stop_event = threading.Event()

# --- アラームデータ管理関数 ---
def load_alarms():
    global alarms_data_global
    if not os.path.exists(config_manager.ALARMS_FILE):
        alarms_data_global = []
        return alarms_data_global
    try:
        with open(config_manager.ALARMS_FILE, "r", encoding="utf-8") as f:
            loaded_data = json.load(f)
            alarms_data_global = sorted(loaded_data, key=lambda x: x.get("time", ""))
            return alarms_data_global
    except Exception as e:
        print(f"アラーム読込エラー: {e}")
        alarms_data_global = []
        return alarms_data_global

def save_alarms():
    try:
        with open(config_manager.ALARMS_FILE, "w", encoding="utf-8") as f:
            json.dump(alarms_data_global, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"アラーム保存エラー: {e}")

def add_alarm_entry(alarm_data: dict):
    global alarms_data_global
    alarms_data_global.append(alarm_data)
    save_alarms()
    return True

def delete_alarm(alarm_id: str):
    global alarms_data_global
    original_len = len(alarms_data_global)
    alarms_data_global = [a for a in alarms_data_global if a.get("id") != alarm_id]
    if len(alarms_data_global) < original_len:
        save_alarms()
        print(f"アラーム削除: ID {alarm_id}")
        return True
    return False

# ★★★ ここからが通知機能の改修箇所 ★★★

def _send_discord_notification(webhook_url, message_text):
    if not webhook_url: return
    headers = {'Content-Type': 'application/json'}
    payload = json.dumps({'content': message_text})
    try:
        response = requests.post(webhook_url, headers=headers, data=payload, timeout=10)
        response.raise_for_status()
        print("Discord/Slack形式のWebhook通知を送信しました。")
    except Exception as e:
        print(f"Discord/Slack形式のWebhook通知送信エラー: {e}")

def _send_pushover_notification(app_token, user_key, message_text, char_name):
    if not app_token or not user_key: return
    payload = {
        "token": app_token,
        "user": user_key,
        "title": f"{char_name} ⏰",
        "message": message_text
    }
    try:
        response = requests.post("https://api.pushover.net/1/messages.json", data=payload, timeout=10)
        response.raise_for_status()
        print("Pushover通知を送信しました。")
    except Exception as e:
        print(f"Pushover通知送信エラー: {e}")

def send_notification(char_name, message_text):
    """設定に応じて適切な通知サービスを呼び出す司令塔"""
    service = config_manager.NOTIFICATION_SERVICE_GLOBAL

    if service == "pushover":
        _send_pushover_notification(
            config_manager.PUSHOVER_APP_TOKEN_GLOBAL,
            config_manager.PUSHOVER_USER_KEY_GLOBAL,
            message_text,
            char_name
        )
    else: # デフォルトはdiscord/slack形式
        notification_message = f"⏰  {char_name}\n\n{message_text}\n"
        _send_discord_notification(
            config_manager.NOTIFICATION_WEBHOOK_URL_GLOBAL,
            notification_message
        )

# ★★★ 通知機能の改修ここまで ★★★

def trigger_alarm(alarm_config, current_api_key_name):
        char_name = alarm_config.get("character")
        alarm_id = alarm_config.get("id")
        context_to_use = alarm_config.get("context_memo", "時間になりました")

        print(f"⏰ アラーム発火. ID: {alarm_id}, キャラクター: {char_name}, コンテキスト: '{context_to_use}'")

        log_f, _, _, _, _ = get_character_files_paths(char_name)
        if not log_f or not current_api_key_name:
            print(f"警告: アラーム (ID:{alarm_id}) のログファイルまたはAPIキーが見つからないため、処理をスキップします。")
            return

        # ★★★ ここからが最重要修正点 ★★★
        # 古い generate_alarm_message の呼び出しを削除し、
        # 最新のエージェント呼び出し関数 invoke_nexus_agent を使用する。

        # 1. エージェントに渡すための「擬似的なユーザー入力」を生成する
        synthesized_user_message = f"（システムアラーム：時間です。コンテキスト「{context_to_use}」について、何か伝えてください）"

        # 2. invoke_nexus_agent が要求する引数リストを組み立てる
        #    UIからの入力ではないため、ほとんどはデフォルト値やNoneで良い
        agent_args = [
            synthesized_user_message,                       # textbox_content
            [],                                             # chatbot_history (空で良い)
            char_name,                                      # current_character_name
            config_manager.initial_model_global,            # current_model_name
            current_api_key_name,                           # current_api_key_name_state
            None,                                           # file_input_list
            False,                                          # add_timestamp_checkbox
            config_manager.initial_send_thoughts_to_api_global, # send_thoughts_state
            config_manager.initial_api_history_limit_option_global, # api_history_limit_state
            True,                                           # send_notepad_state
            True,                                           # use_common_prompt_state
            True                                            # send_core_memory_state
        ]

        # 3. エージェントを呼び出して、応答を生成させる
        response_text = gemini_api.invoke_nexus_agent(*agent_args)
        # ★★★ 修正ここまで ★★★

        if response_text and not response_text.startswith("[エラー"):
            # アラーム専用のヘッダーではなく、システムからの入力としてログに残す
            utils.save_message_to_log(log_f, "## システム(アラーム):", synthesized_user_message)
            utils.save_message_to_log(log_f, f"## {char_name}:", response_text)
            print(f"アラームログ記録完了 (ID:{alarm_id})")

            # 司令塔関数を呼び出して通知を送信
            send_notification(char_name, response_text)

            if PLYER_AVAILABLE:
                try:
                    notification.notify(
                        title=f"{char_name} ⏰",
                        message=response_text,
                        app_name="Nexus Ark",
                        timeout=20
                    )
                    print("PCデスクトップ通知を送信しました。")
                except Exception as e:
                    print(f"PCデスクトップ通知の送信中にエラーが発生しました: {e}")
        else:
            print(f"警告: アラーム応答の生成に失敗 (ID:{alarm_id}). 応答: {response_text}")

def check_alarms():
    now_dt = datetime.datetime.now()
    now_t = now_dt.strftime("%H:%M")
    current_day_short = now_dt.strftime('%a').lower()
    current_api_key = config_manager.initial_api_key_name_global

    current_alarms = load_alarms()
    alarms_to_trigger = []
    remaining_alarms = list(current_alarms)

    for i in range(len(current_alarms) - 1, -1, -1):
        a = current_alarms[i]
        alarm_time = a.get("time")
        is_enabled = a.get("enabled", True)
        alarm_days = [d.lower() for d in a.get("days", [])]

        is_today = False
        alarm_date_str = a.get("date")
        if alarm_date_str:
            try:
                if datetime.datetime.strptime(alarm_date_str, "%Y-%m-%d").date() == now_dt.date():
                    is_today = True
            except (ValueError, TypeError):
                 is_today = not alarm_days or current_day_short in alarm_days
        else:
             is_today = not alarm_days or current_day_short in alarm_days

        if is_enabled and alarm_time == now_t and is_today:
            alarms_to_trigger.append(a)
            if not a.get("days"): # 繰り返しでない単発アラームなら削除
                print(f"  - 単発アラーム {a.get('id')} は実行後に削除されます。")
                remaining_alarms.pop(i)

    if len(current_alarms) != len(remaining_alarms):
        global alarms_data_global
        alarms_data_global = remaining_alarms
        save_alarms()

    if not current_api_key: return

    for alarm_to_run in alarms_to_trigger:
        trigger_alarm(alarm_to_run, current_api_key)

# (schedule_thread_function, start/stop_alarm_scheduler_thread は変更不要)
def schedule_thread_function():
    global alarm_thread_stop_event
    print("アラームスケジューラスレッドを開始します.")
    schedule.every().minute.at(":00").do(check_alarms)
    while not alarm_thread_stop_event.is_set():
        schedule.run_pending(); time.sleep(1)
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
    # (実装は省略)
    pass
