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
            for alarm in loaded_data:
                if isinstance(alarm, dict) and \
                   all(k in alarm for k in ["id", "time", "character", "theme", "enabled"]) and \
                   re.match(r"^\d{2}:\d{2}$", alarm.get("time", "")):
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

def add_alarm(hour, minute, character, theme, flash_prompt):
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
    new_alarm = {
        "id": str(uuid.uuid4()), "time": time_str, "character": character,
        "theme": theme_stripped, "enabled": True,
        "flash_prompt_template": prompt_stripped if prompt_stripped else None
    }
    alarms_data_global.append(new_alarm)
    save_alarms()
    print(f"アラーム追加 (有効): {new_alarm['id']} ({time_str}, {character}, Theme: '{theme_stripped}', CustomPrompt: {'あり' if prompt_stripped else 'なし'})")
    gr.Info("アラームを追加しました。")
    return render_alarm_list_for_checkboxgroup()

def delete_selected_alarms(selected_alarm_ids):
    global alarms_data_global
    if not selected_alarm_ids: gr.Warning("削除対象のアラームが選択されていません。"); return render_alarm_list_for_checkboxgroup()
    original_len = len(alarms_data_global); ids_to_del = set(selected_alarm_ids)
    alarms_data_global = [a for a in alarms_data_global if a.get("id") not in ids_to_del]
    deleted_count = original_len - len(alarms_data_global)
    if deleted_count > 0:
        save_alarms(); print(f"アラーム削除(選択): {deleted_count}件")
        gr.Info(f"{deleted_count}件のアラームを削除しました。")
    else: gr.Warning("選択されたIDに一致するアラームが見つかりませんでした。")
    return render_alarm_list_for_checkboxgroup()

def render_alarm_list_for_checkboxgroup():
    alarms = load_alarms()
    if not alarms:
        return gr.update(choices=[], value=[], label="設定済みアラーム (なし)", interactive=False)
    choices = []
    for alarm in alarms:
        status = "✅" if alarm.get("enabled") else "❌"
        theme_display = alarm.get('theme', '')[:20]
        if len(alarm.get('theme', '')) > 20:
            theme_display += '...'
        # カスタムプロンプトの内容のみを表示
        prompt_display = f" {alarm.get('flash_prompt_template')}" if alarm.get("flash_prompt_template") else ""
        label = f"{status} {alarm.get('time')} - {alarm.get('character')} - \"{theme_display}\"{prompt_display}"
        choices.append((label, alarm.get("id")))
    return gr.update(choices=choices, value=[], label="設定済みアラーム (削除したい項目を選択)", interactive=True)


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

        if is_enabled and alarm_time == now_t:
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