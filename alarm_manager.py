# alarm_manager.py (構文エラー修正版)
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

# --- アラーム関連グローバル変数 ---
alarms_data_global = []
alarm_thread_stop_event = threading.Event()
_alarm_lock = threading.Lock()

# --- アラームデータ管理関数 ---
def load_alarms():
    global alarms_data_global
    if not os.path.exists(config_manager.ALARMS_FILE):
        alarms_data_global = []
        save_alarms()
        return
    try:
        with _alarm_lock:
            with open(config_manager.ALARMS_FILE, "r", encoding="utf-8") as f:
                loaded_data = json.load(f)
            if not isinstance(loaded_data, list):
                print(f"警告: {config_manager.ALARMS_FILE} の形式が不正です。空のリストで初期化します。")
                alarms_data_global = []
                return

            valid_alarms = []
            default_days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
            for alarm in loaded_data:
                if isinstance(alarm, dict) and all(k in alarm for k in ["id", "time", "character", "theme", "enabled"]):
                    if "days" not in alarm:
                        alarm["days"] = default_days
                    valid_alarms.append(alarm)
                else:
                    print(f"警告: 不正な形式のアラームデータをスキップしました: {alarm}")
            alarms_data_global = sorted(valid_alarms, key=lambda x: x.get("time", ""))
    except (json.JSONDecodeError, FileNotFoundError):
        alarms_data_global = []
    except Exception as e:
        print(f"アラーム読込中に予期せぬエラーが発生しました: {e}"); traceback.print_exc()
        alarms_data_global = []

def save_alarms():
    global alarms_data_global
    try:
        with _alarm_lock:
            alarms_to_save = sorted(alarms_data_global, key=lambda x: x.get("time", ""))
            with open(config_manager.ALARMS_FILE, "w", encoding="utf-8") as f:
                json.dump(alarms_to_save, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"アラーム保存エラー: {e}"); traceback.print_exc()

DAY_MAP_JA_TO_EN = {"月": "mon", "火": "tue", "水": "wed", "木": "thu", "金": "fri", "土": "sat", "日": "sun"}

def add_alarm(hour: str, minute: str, character: str, theme: str, flash_prompt: str, days_ja: list):
    global alarms_data_global
    time_str = f"{hour}:{minute}"
    days_en = [DAY_MAP_JA_TO_EN.get(day_ja) for day_ja in days_ja if DAY_MAP_JA_TO_EN.get(day_ja)]
    if not days_en:
        days_en = list(DAY_MAP_JA_TO_EN.values())

    new_alarm = {
        "id": str(uuid.uuid4()),
        "time": time_str,
        "character": character,
        "theme": theme.strip(),
        "enabled": True,
        "days": days_en,
        "flash_prompt_template": flash_prompt.strip() if flash_prompt else None,
    }
    with _alarm_lock:
        alarms_data_global.append(new_alarm)
    save_alarms()
    print(f"アラーム追加: {new_alarm['id']}")
    return True

def update_alarm(alarm_id: str, update_data: dict):
    global alarms_data_global
    with _alarm_lock:
        for alarm in alarms_data_global:
            if alarm.get("id") == alarm_id:
                alarm.update(update_data)
                save_alarms()
                print(f"アラーム更新: {alarm_id} with {update_data}")
                return True
    return False

def delete_alarm(alarm_id: str):
    global alarms_data_global
    with _alarm_lock:
        original_len = len(alarms_data_global)
        alarms_data_global = [a for a in alarms_data_global if a.get("id") != alarm_id]
        if len(alarms_data_global) < original_len:
            save_alarms()
            print(f"アラーム削除: {alarm_id}")
            return True
    return False

def get_all_alarms() -> list:
    load_alarms()
    return alarms_data_global

def get_alarm_by_id(alarm_id: str):
    global alarms_data_global
    load_alarms() # 念のため最新の状態を読み込む
    for alarm in alarms_data_global:
        if alarm.get("id") == alarm_id:
            return alarm
    return None

def send_webhook_notification(webhook_url, message_text):
    if not webhook_url or not message_text: return False
    headers = {'Content-Type': 'application/json'}
    payload = json.dumps({'content': message_text})
    try:
        response = requests.post(webhook_url, headers=headers, data=payload, timeout=10)
        response.raise_for_status()
        print(f"Webhook通知送信成功")
        return True
    except requests.exceptions.RequestException as e:
        print(f"Webhook通知送信エラー: {e}")
        return False
    return False

def trigger_alarm(alarm_config, current_api_key_name, webhook_url):
        # ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
        # ★★★ ここで gemini_api を「関数の中」でインポートすることで、起動時の問題を回避します ★★★
        # ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
        import gemini_api # Deferred import
        from utils import save_message_to_log # Deferred import

        # Ensure config_manager is accessible, typically imported at the top of the file
        # from character_manager import get_character_files_paths # Ensure this is imported (likely at top)
        # from .utils import save_message_to_log # Or however utils is structured
        # from . import config_manager # Or however config_manager is structured

        c = alarm_config.get("character")
        t = alarm_config.get("theme")
        tm = alarm_config.get("time")
        fp = alarm_config.get("flash_prompt_template")
        id_val = alarm_config.get("id") # Renamed from id to id_val to avoid shadowing built-in id
        print(f"⏰ アラーム発火. ID: {id_val}, 時刻: {tm}, キャラクター: {c}, テーマ: '{t}' (カスタムP: {'あり' if fp else 'なし'})")

        # This import should be at the top of the file
        # from character_manager import get_character_files_paths
        log_f, _, _, _ = get_character_files_paths(c) # Assuming get_character_files_paths is correctly imported
        if not log_f:
            print(f"エラー: アラーム'{id_val}'のキャラクター'{c}'のログファイルが見つかりません.処理をスキップします.")
            return

        a_mod = config_manager.initial_alarm_model_global
        a_hist = config_manager.initial_alarm_api_history_turns_global

        if not a_mod:
            print(f"エラー: config.jsonでアラーム用モデル('alarm_model')が設定されていません.")
            return
        if not current_api_key_name:
            print(f"エラー: 有効なAPIキー名が設定されていません.")
            return

        dummy_user_theme = t if t else (fp if fp else "(テーマ未設定)")
        dummy_user_message = f"（システムアラーム：{tm} {dummy_user_theme}）"
        system_header = "## システム(アラーム):"

        # Default theme logic from user
        if not alarm_config.get("theme"):
            if alarm_config.get("id") == "通常タイマー": alarm_config["theme"] = "時間になりました"
            elif alarm_config.get("id") == "作業タイマー": alarm_config["theme"] = "作業終了アラーム"
            elif alarm_config.get("id") == "休憩タイマー": alarm_config["theme"] = "休憩終了アラーム"

        theme = alarm_config.get("theme") # Re-get theme after potential modification
        flash_prompt = alarm_config.get("flash_prompt_template") # Re-get flash_prompt just in case

        response_text = gemini_api.send_alarm_to_gemini(c, theme, flash_prompt, a_mod, current_api_key_name, log_f, a_hist)

        if response_text and isinstance(response_text, str) and not response_text.startswith("【アラームエラー】"):
            save_message_to_log(log_f, system_header, dummy_user_message)
            save_message_to_log(log_f, f"## {c}:", response_text)
            print(f"アラームログ記録完了 (ID:{id_val})")

            if webhook_url:
                # Assuming send_webhook_notification is correctly imported (likely at top)
                notification_message = f"⏰  {c}\n\n{response_text}\n"
                send_webhook_notification(webhook_url, notification_message)
            else:
                print("情報: Webhook URLが設定されていないため、外部通知はスキップします.")
        else:
            print(f"警告: アラーム応答の生成に失敗したか、エラーが返されたため、ログ記録と通知をスキップします (ID:{id_val}).応答: {response_text}")

def check_alarms():
    now_dt = datetime.datetime.now()
    now_t, current_day_short = now_dt.strftime("%H:%M"), now_dt.strftime('%a').lower()
    current_api_key, webhook_url = config_manager.initial_api_key_name_global, config_manager.initial_notification_webhook_url_global
    if not current_api_key: return
    current_alarms = get_all_alarms()
    for a in current_alarms:
        if a.get("enabled") and a.get("time") == now_t and current_day_short in a.get("days", []):
            try:
                trigger_alarm(a, current_api_key, webhook_url)
            except Exception as e:
                print(f"アラーム処理中にエラー (ID:{a.get('id')})"); traceback.print_exc()

def schedule_thread_function():
    global alarm_thread_stop_event
    print("アラームスケジューラスレッドを開始します。")
    try: check_alarms()
    except Exception as e: print(f"初回アラームチェック中にエラー: {e}"); traceback.print_exc()
    schedule.every().minute.at(":00").do(check_alarms)
    while not alarm_thread_stop_event.is_set():
        schedule.run_pending()
        time.sleep(1)
    print("アラームスケジューラスレッドが停止しました。")

def start_alarm_scheduler_thread():
    global alarm_thread_stop_event
    alarm_thread_stop_event.clear()
    config_manager.load_config()
    if not hasattr(start_alarm_scheduler_thread, "scheduler_thread") or not start_alarm_scheduler_thread.scheduler_thread.is_alive():
        thread = threading.Thread(target=schedule_thread_function, daemon=True)
        thread.start()
        start_alarm_scheduler_thread.scheduler_thread = thread
        print("アラームスケジューラスレッドを起動しました。")
    else:
        print("アラームスケジューラスレッドは既に実行中です。")

def stop_alarm_scheduler_thread():
    global alarm_thread_stop_event
    if hasattr(start_alarm_scheduler_thread, "scheduler_thread") and start_alarm_scheduler_thread.scheduler_thread.is_alive():
        print("アラームスケジューラスレッドに停止信号を送信します...")
        alarm_thread_stop_event.set()
        start_alarm_scheduler_thread.scheduler_thread.join(timeout=5)