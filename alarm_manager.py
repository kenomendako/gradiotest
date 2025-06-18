# alarm_manager.py (Restored version with deferred imports)
import os
import json
import re # Keep re for potential future use, though not explicitly used in this version
import uuid
import threading
import schedule
import time
import datetime # Keep for now, might be used by other functions if added
import traceback
import requests
from typing import Optional, List # Added import

# Project-specific imports (ensure these are correct and available)
import config_manager
from character_manager import get_character_files_paths
# import gemini_api # Removed from top - will be imported deferred in trigger_alarm
# from utils import save_message_to_log # Removed from top - will be imported deferred in trigger_alarm

# --- アラーム関連グローバル変数 ---
alarms_data_global = []
alarm_thread_stop_event = threading.Event()
_alarm_lock = threading.Lock()


# --- アラームデータ管理関数 ---
def load_alarms():
    global alarms_data_global
    if not os.path.exists(config_manager.ALARMS_FILE):
        alarms_data_global = []
        save_alarms() # Create an empty alarms file if it doesn't exist
        return

    try:
        with _alarm_lock:
            with open(config_manager.ALARMS_FILE, "r", encoding="utf-8") as f:
                loaded_data = json.load(f)

            if not isinstance(loaded_data, list): # Basic validation
                print(f"警告: {config_manager.ALARMS_FILE} の形式が不正です。空のリストで初期化します。")
                alarms_data_global = []
                save_alarms() # Attempt to save a correct empty list
                return

            valid_alarms = []
            default_days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] # Default all days
            for alarm_item in loaded_data: # Use different var name
                if isinstance(alarm_item, dict) and all(k in alarm_item for k in ["id", "time", "character", "theme", "enabled"]):
                    if "days" not in alarm_item or not alarm_item["days"]: # Ensure days is present and not empty
                        alarm_item["days"] = default_days
                    valid_alarms.append(alarm_item)
                else:
                    print(f"警告: 不正な形式のアラームデータをスキップしました: {alarm_item}")

            # Sort by time for consistent order if not already sorted by save_alarms
            alarms_data_global = sorted(valid_alarms, key=lambda x: (x.get("time", ""), x.get("id", "")))

    except json.JSONDecodeError:
        print(f"警告: {config_manager.ALARMS_FILE} のJSONデコードに失敗しました。空のリストで初期化します。")
        alarms_data_global = []
        save_alarms() # Attempt to save a correct empty list
    except FileNotFoundError: # Should be caught by the os.path.exists check, but good practice
        print(f"情報: アラームファイル '{config_manager.ALARMS_FILE}' が見つかりません。新規作成します。")
        alarms_data_global = []
        save_alarms()
    except Exception as e:
        print(f"アラーム読込中に予期せぬエラーが発生しました: {e}"); traceback.print_exc()
        alarms_data_global = [] # Default to empty on other errors


def save_alarms():
    global alarms_data_global
    try:
        with _alarm_lock:
            # Sort by time then ID for stable saving order
            alarms_to_save = sorted(alarms_data_global, key=lambda x: (x.get("time", ""), x.get("id", "")))
            with open(config_manager.ALARMS_FILE, "w", encoding="utf-8") as f:
                json.dump(alarms_to_save, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"アラーム保存エラー: {e}"); traceback.print_exc()

# Day mapping for UI, ensure consistent with ui_handlers.py if defined there too
DAY_MAP_JA_TO_EN = {"月": "mon", "火": "tue", "水": "wed", "木": "thu", "金": "fri", "土": "sat", "日": "sun"}
DAY_MAP_EN_TO_JA = {v: k for k, v in DAY_MAP_JA_TO_EN.items()}


def add_alarm(hour: str, minute: str, character: str, theme: str, flash_prompt: Optional[str], days_ja: List[str]): # Type hints
    global alarms_data_global
    time_str = f"{hour}:{minute}"

    # Convert Japanese day names to English short names
    days_en = [DAY_MAP_JA_TO_EN.get(day_ja) for day_ja in days_ja if DAY_MAP_JA_TO_EN.get(day_ja)]
    if not days_en: # Default to all days if none are selected or valid
        days_en = list(DAY_MAP_JA_TO_EN.values()) # ["mon", "tue", ...]

    new_alarm = {
        "id": str(uuid.uuid4()),
        "time": time_str,
        "character": character,
        "theme": theme.strip(), # Ensure theme is stripped
        "enabled": True,
        "days": days_en, # Store English short names
        "flash_prompt_template": flash_prompt.strip() if flash_prompt else None, # Store stripped or None
    }
    with _alarm_lock:
        alarms_data_global.append(new_alarm)
    save_alarms()
    print(f"アラーム追加: {new_alarm['id']} - {new_alarm['time']} for {new_alarm['character']}")
    return True # Indicate success

def update_alarm(alarm_id: str, update_data: dict):
    global alarms_data_global
    with _alarm_lock:
        alarm_found = False
        for alarm_item in alarms_data_global: # Use different var name
            if alarm_item.get("id") == alarm_id:
                alarm_item.update(update_data)
                alarm_found = True
                break # Found and updated, no need to continue loop
        if alarm_found:
            save_alarms()
            print(f"アラーム更新: {alarm_id} with {update_data}")
            return True
    print(f"警告: 更新対象のアラームID '{alarm_id}' が見つかりません。")
    return False

def delete_alarm(alarm_id: str) -> bool: # Type hint
    global alarms_data_global
    with _alarm_lock:
        original_len = len(alarms_data_global)
        alarms_data_global = [a for a in alarms_data_global if a.get("id") != alarm_id]
        if len(alarms_data_global) < original_len:
            save_alarms()
            print(f"アラーム削除: {alarm_id}")
            return True
    print(f"警告: 削除対象のアラームID '{alarm_id}' が見つかりません。")
    return False

def get_all_alarms() -> List[dict]: # Type hint
    load_alarms() # Ensure latest alarms are loaded before returning
    # Return a copy to prevent external modification of the global list if needed,
    # but for now, direct return is fine as it's managed internally.
    return alarms_data_global

def get_alarm_by_id(alarm_id: str) -> Optional[dict]: # Type hint
    load_alarms() # Ensure latest alarms are loaded
    for alarm_item in alarms_data_global: # Use different var name
        if alarm_item.get("id") == alarm_id:
            return alarm_item
    return None


def send_webhook_notification(webhook_url: str, message_text: str) -> bool: # Type hints
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
    # Removed redundant return False

def trigger_alarm(alarm_config: dict, current_api_key_name: str, webhook_url: Optional[str]): # Type hints
    # Deferred imports
    import gemini_api
    from utils import save_message_to_log

    c = alarm_config.get("character")
    t = alarm_config.get("theme")
    tm = alarm_config.get("time")
    fp = alarm_config.get("flash_prompt_template")
    id_val = alarm_config.get("id") # Renamed from id
    print(f"⏰ アラーム発火. ID: {id_val}, 時刻: {tm}, キャラクター: {c}, テーマ: '{t}' (カスタムP: {'あり' if fp else 'なし'})")

    log_f, _, _, _ = get_character_files_paths(c) # from character_manager
    if not log_f:
        print(f"エラー: アラーム'{id_val}'のキャラクター'{c}'のログファイルが見つかりません.処理をスキップします.")
        return

    # Use global config values directly
    a_mod = config_manager.initial_alarm_model_global
    a_hist = config_manager.initial_alarm_api_history_turns_global

    if not a_mod: # Check if model is configured
        print(f"エラー: config.jsonでアラーム用モデル('alarm_model')が設定されていません.")
        return
    if not current_api_key_name: # Check if API key is available
        print(f"エラー: 有効なAPIキー名が設定されていません (アラーム用).")
        return

    # Construct dummy user message for log
    dummy_user_theme = t if t else (fp if fp else "(テーマ未設定)")
    dummy_user_message = f"（システムアラーム：{tm} {dummy_user_theme}）"
    system_header = "## システム(アラーム):"

    # Default theme logic from user's final version of this function
    active_theme = alarm_config.get("theme")
    active_flash_prompt = alarm_config.get("flash_prompt_template")

    if not active_theme: # Check original theme from config
        if id_val == "通常タイマー": active_theme = "時間になりました"
        elif id_val == "作業タイマー": active_theme = "作業終了アラーム"
        elif id_val == "休憩タイマー": active_theme = "休憩終了アラーム"
        # No else, if it's a custom alarm without a theme, it will use flash_prompt or "(テーマ未設定)"

    response_text = gemini_api.send_alarm_to_gemini(c, active_theme, active_flash_prompt, a_mod, current_api_key_name, log_f, a_hist)

    if response_text and isinstance(response_text, str) and not response_text.startswith("【アラームエラー】"):
        save_message_to_log(log_f, system_header, dummy_user_message) # from utils
        save_message_to_log(log_f, f"## {c}:", response_text) # from utils
        print(f"アラームログ記録完了 (ID:{id_val})")

        if webhook_url:
            notification_message = f"⏰  {c}\n\n{response_text}\n" # Corrected f-string from earlier fix
            send_webhook_notification(webhook_url, notification_message) # Local function
        else:
            print("情報: Webhook URLが設定されていないため、外部通知はスキップします.")
    else:
        print(f"警告: アラーム応答の生成に失敗したか、エラーが返されたため、ログ記録と通知をスキップします (ID:{id_val}).応答: {response_text}")


def check_alarms():
    now_dt = datetime.datetime.now()
    now_t, current_day_short = now_dt.strftime("%H:%M"), now_dt.strftime('%a').lower()

    # Get current API key and webhook URL from config_manager globals
    current_api_key = config_manager.initial_api_key_name_global
    webhook_url_val = config_manager.initial_notification_webhook_url_global

    if not current_api_key:
        print("警告: check_alarms - 有効なAPIキーが設定されていません。アラームチェックをスキップします。")
        return

    current_alarms = get_all_alarms() # Always get fresh list
    for alarm_item in current_alarms: # Use different var name
        if alarm_item.get("enabled") and alarm_item.get("time") == now_t and current_day_short in alarm_item.get("days", []):
            try:
                trigger_alarm(alarm_item, current_api_key, webhook_url_val)
            except Exception as e: # Catch errors during individual alarm trigger
                print(f"アラーム処理中にエラー (ID:{alarm_item.get('id')})"); traceback.print_exc()


def schedule_thread_function():
    global alarm_thread_stop_event # Use the global event
    print("アラームスケジューラスレッドを開始します。")
    try:
        check_alarms() # Initial check
    except Exception as e:
        print(f"初回アラームチェック中にエラー: {e}"); traceback.print_exc()

    # Schedule every minute, aligned to the start of the minute
    schedule.every().minute.at(":00").do(check_alarms)

    while not alarm_thread_stop_event.is_set():
        schedule.run_pending()
        time.sleep(1) # Check every second
    print("アラームスケジューラスレッドが停止しました。")

# Thread management variables should be module-level to be accessed by start/stop
_scheduler_thread = None

def start_alarm_scheduler_thread():
    global alarm_thread_stop_event, _scheduler_thread
    alarm_thread_stop_event.clear() # Clear stop event before starting

    # config_manager.load_config() # Config should be loaded at app startup, not here repeatedly.
                                # This was in an older version, but removed as it can cause issues if called late.

    if _scheduler_thread is None or not _scheduler_thread.is_alive():
        _scheduler_thread = threading.Thread(target=schedule_thread_function, daemon=True)
        _scheduler_thread.start()
        print("アラームスケジューラスレッドを起動しました。")
    else:
        print("アラームスケジューラスレッドは既に実行中です。")


def stop_alarm_scheduler_thread():
    global alarm_thread_stop_event, _scheduler_thread
    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        print("アラームスケジューラスレッドに停止信号を送信します...")
        alarm_thread_stop_event.set()
        _scheduler_thread.join(timeout=5) # Wait for thread to stop
        if _scheduler_thread.is_alive():
            print("警告: アラームスレッドがタイムアウト後も停止していません。")
        else:
            print("アラームスケジューラスレッドは正常に停止しました。")
        _scheduler_thread = None # Reset thread variable
    else:
        print("アラームスケジューラスレッドは実行されていません。")
