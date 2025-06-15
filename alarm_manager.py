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
    if not os.path.exists(config_manager.ALARMS_FILE):
        alarms_data_global = []
        save_alarms()
        return alarms_data_global
    try:
        with open(config_manager.ALARMS_FILE, "r", encoding="utf-8") as f:
            loaded_data = json.load(f)
            if not isinstance(loaded_data, list):
                print(f"警告: {config_manager.ALARMS_FILE} の形式が不正です.空のリストで初期化します.")
                alarms_data_global = []
                return alarms_data_global
            valid_alarms = []
            default_days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
            for alarm in loaded_data:
                if isinstance(alarm, dict) and \
                   all(k in alarm for k in ["id", "time", "character", "theme", "enabled"]) and \
                   re.match(r"^\d{2}:\d{2}$", alarm.get("time", "")):
                    # 曜日(days)キーが存在しない場合にデフォルト値を追加
                    if "days" not in alarm:
                        alarm["days"] = default_days
                    valid_alarms.append(alarm)
                else:
                    print(f"警告: 不正な形式のアラームデータをスキップしました: {alarm}")
            alarms_data_global = sorted(valid_alarms, key=lambda x: x.get("time", ""))
            return alarms_data_global
    except json.JSONDecodeError as e:
        print(f"アラームファイル ({config_manager.ALARMS_FILE}) のJSONデコードエラー: {e}")
        alarms_data_global = []
        return alarms_data_global
    except Exception as e:
        print(f"アラーム読込中に予期せぬエラーが発生しました: {e}"); traceback.print_exc()
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

DAY_MAP_JA_TO_EN = {
    "月": "mon", "火": "tue", "水": "wed", "木": "thu",
    "金": "fri", "土": "sat", "日": "sun"
}

def add_alarm(hour: str, minute: str, character: str, theme: str, flash_prompt: str, days_ja: list):
    global alarms_data_global
    if not character:
        print("エラー: アラーム追加にはキャラクターの選択が必要です.")
        return False # UIコンポーネントではなく、失敗を示すbool値を返す

    theme_stripped = theme.strip() if theme else "時間になりました"
    prompt_stripped = flash_prompt.strip() if flash_prompt else None

    if not theme_stripped and not prompt_stripped:
        print("エラー: 「テーマ」または「カスタムプロンプト」のいずれかを入力してください.")
        return False # UIコンポーネントではなく、失敗を示すbool値を返す

    time_str = f"{hour}:{minute}"
    days_en = [DAY_MAP_JA_TO_EN.get(day_ja, "") for day_ja in days_ja if DAY_MAP_JA_TO_EN.get(day_ja)]
    if not days_en:
        # 曜日が一つも選択されなかった場合、全曜日を選択したものとして扱う
        days_en = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        print("警告: 曜日設定が無効だったため、全て選択(デフォルト)として登録します.")

    new_alarm = {
        "id": str(uuid.uuid4()), "time": time_str, "character": character,
        "theme": theme_stripped, "enabled": True, "days": days_en,
        "flash_prompt_template": prompt_stripped if prompt_stripped else None
    }
    alarms_data_global.append(new_alarm)
    save_alarms()
    print(f"アラーム追加 (有効): {new_alarm['id']} ({time_str}, {character}, Theme: '{theme_stripped}', Days: {days_en}, CustomPrompt: {'あり' if prompt_stripped else 'なし'})")
    return True # 成功を示すbool値を返す

def toggle_alarm_enabled(alarm_id: str):
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
        print(f"アラーム状態変更: ID {alarm_id} を{status}にしました.")
        return True
    else:
        print(f"警告: アラームID {alarm_id} が見つかりませんでした (トグル操作不可).")
        return False

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

def get_all_alarms():
    """現在のすべてのアラームのリストを返します."""
    load_alarms() # 常に最新の情報を読み込む
    return alarms_data_global

def get_alarm_by_id(alarm_id: str):
    """IDによって単一のアラームを取得します."""
    load_alarms()
    for alarm in alarms_data_global:
        if alarm.get("id") == alarm_id:
            return alarm
    return None

# --- Webhook通知関数 ---
def send_webhook_notification(webhook_url, message_text):
    if not webhook_url or not message_text:
        return False
    headers = {'Content-Type': 'application/json'}
    payload = json.dumps({'content': message_text})
    try:
        response = requests.post(webhook_url, headers=headers, data=payload, timeout=10)
        response.raise_for_status()
        print(f"Webhook通知送信成功 (URL: {webhook_url[:30]}...)")
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
    c = alarm_config.get("character")
    t = alarm_config.get("theme")
    tm = alarm_config.get("time")
    fp = alarm_config.get("flash_prompt_template")
    id = alarm_config.get("id")
    print(f"⏰ アラーム発火. ID: {id}, 時刻: {tm}, キャラクター: {c}, テーマ: '{t}' (カスタムP: {'あり' if fp else 'なし'})")

    log_f, _, _, _ = get_character_files_paths(c)
    if not log_f:
        print(f"エラー: アラーム'{id}'のキャラクター'{c}'のログファイルが見つかりません.処理をスキップします.")
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

    if not alarm_config.get("theme"):
        if alarm_config.get("id") == "通常タイマー": alarm_config["theme"] = "時間になりました"
        elif alarm_config.get("id") == "作業タイマー": alarm_config["theme"] = "作業終了アラーム"
        elif alarm_config.get("id") == "休憩タイマー": alarm_config["theme"] = "休憩終了アラーム"

    theme = alarm_config.get("theme") # Re-fetch after potential modification
    flash_prompt = alarm_config.get("flash_prompt_template")

    response_text = gemini_api.send_alarm_to_gemini(c, theme, flash_prompt, a_mod, current_api_key_name, log_f, a_hist)

    if response_text and isinstance(response_text, str) and not response_text.startswith("【アラームエラー】"):
        save_message_to_log(log_f, system_header, dummy_user_message)
        save_message_to_log(log_f, f"## {c}:", response_text)
        print(f"アラームログ記録完了 (ID:{id})")

        if webhook_url:
            notification_message = f"⏰  {c}\n\n{response_text}\n"
            send_webhook_notification(webhook_url, notification_message)
        else:
            print("情報: Webhook URLが設定されていないため、外部通知はスキップします.")
    else:
        print(f"警告: アラーム応答の生成に失敗したか、エラーが返されたため、ログ記録と通知をスキップします (ID:{id}).応答: {response_text}")

def check_alarms():
    now_dt = datetime.datetime.now()
    now_t = now_dt.strftime("%H:%M")
    current_day_short = now_dt.strftime('%a').lower()

    current_api_key = config_manager.initial_api_key_name_global
    webhook_url_to_use = config_manager.initial_notification_webhook_url_global

    # 毎回アラームリストを再読み込み
    current_alarms = load_alarms()

    if not current_api_key:
        return

    for a in current_alarms:
        alarm_time = a.get("time")
        is_enabled = a.get("enabled")
        alarm_id_for_log = a.get('id', 'N/A')
        alarm_days = a.get("days", [])

        if alarm_days is None: alarm_days = [] # 念のためのNoneチェック
        if not alarm_days: continue # 日付リストが空ならスキップ

        if is_enabled and alarm_time == now_t and current_day_short in alarm_days:
            try:
                trigger_alarm(a, current_api_key, webhook_url_to_use)
            except Exception as e:
                print(f"アラーム処理中に予期せぬエラー (ID:{alarm_id_for_log})")
                traceback.print_exc()

def schedule_thread_function():
    global alarm_thread_stop_event
    print("アラームスケジューラスレッドを開始します.")
    try:
        check_alarms() # 初回実行
    except Exception as e:
        print(f"初回アラームチェック中にエラー: {e}")
        traceback.print_exc()

    schedule.every().minute.at(":00").do(check_alarms)

    while not alarm_thread_stop_event.is_set():
        try:
            schedule.run_pending()
        except Exception as e:
            print(f"スケジュール実行中にエラー: {e}")
            traceback.print_exc()
        time.sleep(1)

    print("アラームスケジューラスレッドが停止しました.")

def start_alarm_scheduler_thread():
    global alarm_thread_stop_event
    alarm_thread_stop_event.clear()
    config_manager.load_config()

    if not hasattr(start_alarm_scheduler_thread, "scheduler_thread") or \
       not start_alarm_scheduler_thread.scheduler_thread.is_alive():
        start_alarm_scheduler_thread.scheduler_thread = threading.Thread(target=schedule_thread_function, daemon=True)
        start_alarm_scheduler_thread.scheduler_thread.start()
        print("アラームスケジューラスレッドを起動しました.")
    else:
        print("アラームスケジューラスレッドは既に実行中です.")


def stop_alarm_scheduler_thread():
    global alarm_thread_stop_event
    if hasattr(start_alarm_scheduler_thread, "scheduler_thread") and \
       start_alarm_scheduler_thread.scheduler_thread.is_alive():
        print("アラームスケジューラスレッドに停止信号を送信します...")
        alarm_thread_stop_event.set()
        start_alarm_scheduler_thread.scheduler_thread.join(timeout=5)
        if start_alarm_scheduler_thread.scheduler_thread.is_alive():
            print("警告: アラームスケジューラスレッドが時間内に停止しませんでした.")
        else:
            print("アラームスケジューラスレッドが正常に停止しました.")
    else:
        print("アラームスケジューラスレッドは実行されていません.")