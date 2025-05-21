# -*- coding: utf-8 -*-
import gradio as gr
import datetime
import json
import os
# 分割したモジュールから必要な関数や変数をインポート
import config_manager
from timers import Timer, PomodoroTimer, UnifiedTimer  # Use absolute import if 'my_timer_module.py' is in the same directory
from alarm_manager import start_alarm_timer  # Assuming it is defined in alarm_manager
from character_manager import get_character_files_paths
from gemini_api import configure_google_api, send_to_gemini
from memory_manager import save_memory_data, load_memory_data_safe
from utils import load_chat_log, format_history_for_gradio, save_message_to_log, _get_user_header_from_log

# --- Gradio UI イベントハンドラ ---
def handle_message_submission(textbox, chatbot, current_character_name, current_model_name, current_api_key_name_state, file_input, add_timestamp_checkbox, send_thoughts_state, api_history_limit_state):
    print(f"\n--- メッセージ送信処理開始 --- {datetime.datetime.now()} ---")
    error_message = ""
    if not all([current_character_name, current_model_name, current_api_key_name_state]):
        error_message = "キャラクター、AIモデル、APIキーが選択されていません。設定を確認してください。"
        return chatbot, textbox.update(value=""), None, error_message

    # APIキー設定エラー処理
    ok, msg = configure_google_api(current_api_key_name_state)
    if not ok:
        error_message = f"APIキー設定エラー: {msg}"
        return chatbot, textbox or "", None, error_message

    log_f, sys_p, _, mem_p = get_character_files_paths(current_character_name)
    if not all([log_f, sys_p, mem_p]):
        error_message = f"キャラクター '{current_character_name}' のファイル（ログ、プロンプト、記憶）が見つかりません。"
        return chatbot, textbox.update(value=""), None, error_message

    msg_send = textbox.strip() if textbox else ""
    ts = ""
    if (add_timestamp_checkbox and (msg_send or file_input)):
        now = datetime.datetime.now()
        ts = f"\n{now.strftime('%Y-%m-%d (%a) %H:%M:%S')}"
        if msg_send: msg_send += ts

    if not msg_send and not file_input:
        error_message = "送信するメッセージまたは画像がありません。"
        return chatbot, "", None, error_message

    try:
        # --- Gemini 2.5 Pro/Flashモデル時は検索ツール自動利用（toolsパラメータ有効化）でAPI呼び出し（send_to_gemini側で自動判定） ---
        if file_input:
            if file_input.endswith(('.png', '.jpg', '.jpeg')):
                resp, _ = send_to_gemini(sys_p, log_f, msg_send, current_model_name, current_character_name, send_thoughts_state, api_history_limit_state, file_input, mem_p)
                file_input = None
            elif file_input.endswith(('.txt', '.json')):
                try:
                    with open(file_input, 'r', encoding='utf-8') as file:
                        file_content = file.read()
                    resp, _ = send_to_gemini(sys_p, log_f, msg_send + "\n" + file_content, current_model_name, current_character_name, send_thoughts_state, api_history_limit_state, None, mem_p)
                except Exception as e:
                    error_message = f"ファイルの読み込み中にエラーが発生しました: {e}"
                    return chatbot, textbox or "", None, error_message
                file_input = None
            else:
                error_message = "サポートされていないファイル形式です。画像、テキスト、またはJSONファイルをアップロードしてください。"
                return chatbot, textbox or "", None, error_message

            if not msg_send.strip():
                error_message = f"送信したファイル名: {os.path.basename(file_input)}"
                return chatbot, textbox or "", None, error_message

            textbox = ""
        else:
            resp, _ = send_to_gemini(sys_p, log_f, msg_send, current_model_name, current_character_name, send_thoughts_state, api_history_limit_state, None, mem_p)

        # --- エラー応答の場合はログに書き込まずUIのみ更新 ---
        if resp and (resp.strip().startswith("エラー:") or resp.strip().startswith("API通信エラー:") or resp.strip().startswith("応答取得エラー") or resp.strip().startswith("応答生成失敗")):
            error_message = f"Gemini APIエラー: {resp}"
            return chatbot, textbox or "", None, error_message

        if msg_send.strip():
            save_message_to_log(log_f, _get_user_header_from_log(log_f, current_character_name), msg_send)
        if resp and resp.strip():
            save_message_to_log(log_f, f"## {current_character_name}:", resp)

    except Exception as e:
        error_message = f"API送信中にエラーが発生しました: {e}"
        return chatbot, textbox or "", None, error_message

    new_log = load_chat_log(log_f, current_character_name)
    new_hist = format_history_for_gradio(new_log[-(config_manager.HISTORY_LIMIT * 2):])
    return new_hist, "", None, ""

def update_ui_on_character_change(character_name):
    if not character_name:
        # キャラクターが選択されていない場合（リストが空など）のフォールバック
        return gr.update(), gr.update(value=[]), gr.update(value=""), gr.update(value=None), gr.update(value="{}")
    print(f"キャラクター変更: '{character_name}'")
    config_manager.save_config("last_character", character_name)
    log_f, _, img_p, mem_p = get_character_files_paths(character_name)
    hist = []
    if log_f:
        hist = format_history_for_gradio(load_chat_log(log_f, character_name)[-(config_manager.HISTORY_LIMIT*2):])
    mem_data = load_memory_data_safe(mem_p)
    mem_s = json.dumps(mem_data, indent=2, ensure_ascii=False) if isinstance(mem_data, dict) else json.dumps({"error": "Failed to load memory"}, indent=2)

    # アラーム設定のキャラクタードロップダウンも更新
    return character_name, gr.update(value=hist), gr.update(value=""), gr.update(value=img_p), gr.update(value=mem_s), gr.update(value=character_name)

def update_model_state(selected_model):
    if selected_model is None: return gr.update() # 選択肢がない場合など
    print(f"モデル変更: '{selected_model}'")
    config_manager.save_config("last_model", selected_model)
    return selected_model # Stateを更新するために返す

def update_api_key_state(selected_api_key_name):
    # global initial_api_key_name_global # グローバル変数を更新するため -> config_manager 経由でアクセス
    if not selected_api_key_name: return gr.update()
    print(f"APIキー変更: '{selected_api_key_name}'")
    ok, msg = configure_google_api(selected_api_key_name)
    config_manager.save_config("last_api_key_name", selected_api_key_name)
    config_manager.initial_api_key_name_global = selected_api_key_name # アラームチェックで使うためグローバルも更新
    if ok:
        gr.Info(f"APIキー '{selected_api_key_name}' の設定に成功しました。")
    else:
        gr.Error(f"APIキー '{selected_api_key_name}' の設定に失敗しました: {msg}")
    return selected_api_key_name # Stateを更新するために返す

def update_timestamp_state(add_timestamp_checked):
    if isinstance(add_timestamp_checked, bool):
        config_manager.save_config("add_timestamp", add_timestamp_checked)
    # チェックボックスの状態はGradioが管理するので、明示的に返す必要はない
    # 返り値として add_timestamp_checked を返すことでStateを更新することも可能だが、
    # このチェックボックスは直接Stateにバインドされていないため、Noneを返すか、何も返さないのが適切
    return None


def update_send_thoughts_state(send_thoughts_checked):
    if not isinstance(send_thoughts_checked, bool): return gr.update()
    print(f"思考過程API送信設定変更: {send_thoughts_checked}")
    config_manager.save_config("last_send_thoughts_to_api", send_thoughts_checked)
    return send_thoughts_checked # Stateを更新するために返す

def update_api_history_limit_state(selected_limit_option_ui_value):
    # UI表示名から内部キー（"10", "all"など）を逆引き
    key = next((k for k, v in config_manager.API_HISTORY_LIMIT_OPTIONS.items() if v == selected_limit_option_ui_value), None)
    if key:
        print(f"API履歴制限設定変更: '{key}' ({selected_limit_option_ui_value})")
        config_manager.save_config("last_api_history_limit_option", key)
        return key # Stateを更新するために返す
    return gr.update() # 見つからなかった場合は更新しない

def reload_chat_log(character_name):
    if not character_name:
        return []
    log_file, _, _, _ = get_character_files_paths(character_name)
    if not log_file:
        return []
    return format_history_for_gradio(load_chat_log(log_file, character_name)[-(config_manager.HISTORY_LIMIT * 2):])

# handle_timer_submission 関数を UnifiedTimer を使用するように更新
def handle_timer_submission(timer_type, duration, work_duration, break_duration, cycles, current_character_name, work_theme, break_theme, api_key_name, webhook_url, normal_timer_theme):
    if not current_character_name:
        gr.Error("キャラクターが選択されていません。タイマーを設定するにはキャラクターを選択してください。")
        return

    if timer_type == "通常タイマー" and not duration:
        gr.Error("タイマーの時間を入力してください。")
        return

    if timer_type == "ポモドーロタイマー" and not (work_duration and break_duration and cycles):
        gr.Error("作業時間、休憩時間、サイクル数を入力してください。")
        return

    print(f"タイマー設定: タイプ={timer_type}, キャラクター={current_character_name}, 作業テーマ={work_theme}, 休憩テーマ={break_theme}, 通常タイマーのテーマ={normal_timer_theme}")

    unified_timer = UnifiedTimer(
        timer_type=timer_type,
        duration=duration,
        work_duration=work_duration,
        break_duration=break_duration,
        cycles=cycles,
        character_name=current_character_name,
        work_theme=work_theme,
        break_theme=break_theme,
        api_key_name=api_key_name,
        webhook_url=webhook_url,
        normal_timer_theme=normal_timer_theme
    )
    unified_timer.start()
    gr.Info(f"{timer_type} を開始しました。")