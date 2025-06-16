# ui_handlers.py の【最終確定版】

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
from memory_manager import load_memory_data_safe, save_memory_data # save_memory_data を直接使う場合
from utils import load_chat_log, format_history_for_gradio, save_message_to_log, _get_user_header_from_log, save_log_file

# ★★★ ui_handlers.py の修正点: 新しいキャラクター追加のハンドラをシンプルに ★★★
def handle_add_new_character(character_name: str):
    """テキストボックスから受け取った名前で新しいキャラクターを作成する。"""
    if not character_name or not character_name.strip():
        gr.Warning("キャラクター名が入力されていません。")
        char_list = character_manager.get_character_list()
        # ドロップダウンの選択は変更せず、テキストボックスもそのまま
        return gr.update(choices=char_list), gr.update(choices=char_list), gr.update(choices=char_list), gr.update(value=character_name)


    safe_name = re.sub(r'[\/*?:"<>|]', "", character_name).strip()
    if not safe_name:
        gr.Warning("無効なキャラクター名です。")
        char_list = character_manager.get_character_list()
        return gr.update(choices=char_list), gr.update(choices=char_list), gr.update(choices=char_list), gr.update(value=character_name) # 無効な名前は残す

    if character_manager.ensure_character_files(safe_name):
        gr.Info(f"新しいキャラクター「{safe_name}」さんを迎えました！")
        new_char_list = character_manager.get_character_list()
        # 新しいキャラクターを選択状態にし、入力欄をクリアする
        # ★★★ ui_handlers.py の修正点: 3つのドロップダウンすべてで新しいキャラクターを選択 ★★★
        return gr.update(choices=new_char_list, value=safe_name), gr.update(choices=new_char_list, value=safe_name), gr.update(choices=new_char_list, value=safe_name), gr.update(value="")
    else:
        gr.Error(f"キャラクター「{safe_name}」の準備に失敗しました。")
        char_list = character_manager.get_character_list()
        return gr.update(choices=char_list), gr.update(choices=char_list), gr.update(choices=char_list), gr.update(value=character_name) # 失敗時も入力は残す

# ★★★ ui_handlers.py の修正点: character_nameがNoneの場合のフォールバックを強化 ★★★
def update_ui_on_character_change(character_name: Optional[str]):
    """キャラクター変更時にUI全体を更新する。戻り値の数を8個に統一。"""
    if not character_name:
        all_chars = character_manager.get_character_list()
        if all_chars: # 利用可能なキャラクターが一人でもいれば
            character_name = all_chars[0]
            gr.Warning("キャラクターが選択されていませんでした。リストの最初のキャラクターを選択します。")
        else: # 本当に一人もいない場合 (通常ありえないが念のため)
            gr.Info("キャラクターが存在しません。'Default'キャラクターを作成します。")
            character_manager.ensure_character_files("Default") # Defaultキャラクターを作成
            character_name = "Default"
        config_manager.save_config("last_character", character_name) # この場合も保存する

    log_f, _, img_p, mem_p = get_character_files_paths(character_name)

    chat_history = format_history_for_gradio(load_chat_log(log_f, character_name)[-(config_manager.HISTORY_LIMIT * 2):]) if log_f and os.path.exists(log_f) else []

    log_content = ""
    if log_f and os.path.exists(log_f):
        try:
            with open(log_f, "r", encoding="utf-8") as f: log_content = f.read()
        except Exception as e: log_content = f"ログ読込エラー: {e}"

    memory_str = json.dumps(load_memory_data_safe(mem_p), indent=2, ensure_ascii=False)
    profile_image = img_p if img_p and os.path.exists(img_p) else None

    # character_name, chat_history, chat_input_textbox, profile_image, memory_json_editor, alarm_char_dropdown, log_editor, timer_char_dropdown
    return character_name, chat_history, "", profile_image, memory_str, character_name, log_content, character_name


# ★★★ ui_handlers.py の修正点: save_memory_dataを直接呼ばず、エラーハンドリングを強化 ★★★
def handle_save_memory_click(character_name: Optional[str], json_string_data: str):
    """「想いを綴る」ボタンの処理。memory_managerを直接呼ばず、エラーハンドリングを強化。"""
    if not character_name:
        gr.Warning("キャラクターが選択されていません。記憶を保存できません。")
        return # 何も変更しないのでgr.update()は不要

    try:
        # memory_manager.py の save_memory_data は gr ライブラリに依存すべきではないので、
        # JSON文字列を直接受け取り、パースと保存を行う。
        save_memory_data(character_name, json_string_data) # memory_manager.save_memory_data を使用
        gr.Info("記憶を保存しました。")
    except json.JSONDecodeError:
        gr.Error("記憶データのJSON形式が正しくありません。保存できませんでした。")
    except Exception as e:
        gr.Error(f"記憶の保存中に予期せぬエラーが発生しました: {e}")


# ★★★ ui_handlers.py の修正点: handle_message_submission の戻り値型ヒント修正 ★★★
def handle_message_submission(*args: Any) -> Tuple[List[Optional[Tuple[Union[str, None, Tuple[str, str]], Union[str, None, Tuple[str, str]]]]], gr.update, gr.update]:
    (textbox_content, chatbot_history, current_character_name, current_model_name,
     current_api_key_name_state, file_input_list, add_timestamp_checkbox,
     send_thoughts_state, api_history_limit_state) = args
    print(f"\n--- メッセージ送信処理開始 --- {datetime.datetime.now()} ---")
    log_f, sys_p, _, mem_p = None, None, None, None
    # error_message は gr.Error で表示するので、ここでは不要
    try:
        if not all([current_character_name, current_model_name, current_api_key_name_state]):
            gr.Warning("キャラクター、モデル、APIキーをすべて選択してください。")
            return chatbot_history, gr.update(), gr.update(value=None) # ファイルリストもクリア
        log_f, sys_p, _, mem_p = get_character_files_paths(current_character_name)
        if not all([log_f, sys_p, mem_p]):
            gr.Warning(f"キャラクター '{current_character_name}' の必須ファイルパス取得に失敗。")
            return chatbot_history, gr.update(), gr.update(value=None)
        user_prompt = textbox_content.strip() if textbox_content else ""
        if not user_prompt and not file_input_list:
            # メッセージが空でもUIリセットは不要なので早期リターン。エラーでもないのでgr.Warningも不要。
            return chatbot_history, gr.update(), gr.update() # chatbot_historyはそのまま、入力とファイルはクリアしない

        log_message_content = user_prompt
        if file_input_list:
            for file_path_obj in file_input_list: # gr.FilesはFileDataオブジェクトのリストを返す
                log_message_content += f"\n[ファイル添付: {file_path_obj.name}]" # .name属性を使用
        user_header = _get_user_header_from_log(log_f, current_character_name)
        timestamp = f"\n{datetime.datetime.now().strftime('%Y-%m-%d (%a) %H:%M:%S')}" if add_timestamp_checkbox else ""
        save_message_to_log(log_f, user_header, log_message_content.strip() + timestamp)

        formatted_files_for_api = []
        if file_input_list:
            for file_path_obj in file_input_list:
                # file_path_obj.name はフルパスの場合があるので、ファイル名だけを使うか、
                # もしくは gemini_api 側でパスを処理する必要がある。ここではそのまま渡す。
                # mimetypes.guess_type にはファイルパス文字列が必要。
                mime_type, _ = mimetypes.guess_type(file_path_obj.name)
                if mime_type is None: mime_type = "application/octet-stream"
                formatted_files_for_api.append({"path": file_path_obj.name, "mime_type": mime_type})

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
        gr.Error(f"メッセージ処理中に予期せぬエラーが発生しました: {e}")
        # エラー時もチャット履歴はそのまま、入力とファイルはクリアしないことが多いが、ここではクリアする方針
        # return chatbot_history, gr.update(value=textbox_content), gr.update(value=file_input_list)

    # 正常終了時、エラー発生時ともにログは再読込して表示を更新
    if log_f and os.path.exists(log_f):
        new_log = load_chat_log(log_f, current_character_name)
        new_hist = format_history_for_gradio(new_log[-(config_manager.HISTORY_LIMIT * 2):])
    else:
        new_hist = chatbot_history # フォールバック

    return new_hist, gr.update(value=""), gr.update(value=None) # 入力テキストボックスとファイルアップロードをクリア

DAY_MAP_EN_TO_JA = {"mon": "月", "tue": "火", "wed": "水", "thu": "木", "fri": "金", "sat": "土", "sun": "日"}

def render_alarms_as_dataframe():
    alarms = alarm_manager.get_all_alarms()
    display_data = []
    for alarm in sorted(alarms, key=lambda x: x.get("time", "")): # timeでソート
        days_ja = [DAY_MAP_EN_TO_JA.get(d.lower(), d.upper()) for d in alarm.get('days', [])] # 小文字で検索
        display_data.append({"ID": alarm.get("id"), "状態": alarm.get("enabled", False), "時刻": alarm.get("time"), "曜日": ",".join(days_ja), "キャラ": alarm.get("character"), "テーマ": alarm.get("theme")})
    df = pd.DataFrame(display_data, columns=["ID", "状態", "時刻", "曜日", "キャラ", "テーマ"])
    return df

def get_display_df(df_with_id: pd.DataFrame):
    if df_with_id is None or df_with_id.empty or 'ID' not in df_with_id.columns:
        return pd.DataFrame(columns=["状態", "時刻", "曜日", "キャラ", "テーマ"]) # 空のDFを返す
    return df_with_id[["状態", "時刻", "曜日", "キャラ", "テーマ"]]

def handle_alarm_selection(evt: gr.SelectData, df_with_id: pd.DataFrame):
    if evt.selected_indices is None or df_with_id is None or df_with_id.empty: return [] # selected_indices を使用
    # evt.selected_indices はタプルのリスト [(row, col), ...] または単一のタプル (row, col)
    # ここでは行選択のみを想定しているので、行インデックスのみを取得
    if isinstance(evt.selected_indices, list) and len(evt.selected_indices) > 0:
        # 複数行選択の場合 (Dataframeのinteractive=Trueでは通常発生しないが念のため)
        selected_row_indices = sorted(list(set(idx[0] for idx in evt.selected_indices)))
    elif isinstance(evt.selected_indices, tuple) and len(evt.selected_indices) == 2 : # (row, col)
        selected_row_indices = [evt.selected_indices[0]]
    else: selected_row_indices = []

    selected_ids = [str(df_with_id.iloc[i]['ID']) for i in selected_row_indices if 0 <= i < len(df_with_id)]
    return selected_ids

def handle_alarm_selection_and_feedback(evt: gr.SelectData, df_with_id: pd.DataFrame):
    selected_ids = handle_alarm_selection(evt, df_with_id) # 上記の修正された関数を呼ぶ
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
    else:
        changed_count = 0
        status_text = "有効" if target_status else "無効"
        for alarm_id_str in selected_ids: # IDは文字列として渡ってくる想定
            alarm = alarm_manager.get_alarm_by_id(str(alarm_id_str)) # 念のためstr()
            if alarm and alarm.get("enabled") != target_status:
                if alarm_manager.toggle_alarm_enabled(str(alarm_id_str)): changed_count += 1
        if changed_count > 0: gr.Info(f"{changed_count}件のアラームを「{status_text}」に変更しました。")
    return render_alarms_as_dataframe() # 更新後の全アラームリストを返す

def handle_delete_selected_alarms(selected_ids: list):
    if not selected_ids:
        gr.Warning("削除するアラームが選択されていません。")
    else:
        deleted_count = sum(1 for sid_str in selected_ids if alarm_manager.delete_alarm(str(sid_str))) # 念のためstr()
        if deleted_count > 0: gr.Info(f"{deleted_count}件のアラームを削除しました。")
    return render_alarms_as_dataframe()

def handle_timer_submission(timer_type, duration, work, brk, cycles, char, work_theme, brk_theme, api_key, webhook, normal_theme):
    if not char or not api_key:
        gr.Warning("エラー：タイマーを設定するにはキャラクターとAPIキーを選択してください。")
        return "エラー：キャラクターとAPIキーを選択してください。"
    try:
        # UnifiedTimer のコンストラクタと start メソッドが例外を投げる可能性に備える
        timer = UnifiedTimer(timer_type, float(duration or 0), float(work or 0), float(brk or 0), int(cycles or 0), char, work_theme, brk_theme, api_key, webhook, normal_theme)
        timer.start() # ここでスレッドが開始される
        gr.Info(f"{timer_type}を開始しました。")
        return f"{timer_type}を開始しました。"
    except ValueError as ve: # 数値変換エラーなど
        gr.Error(f"タイマー設定値エラー: {ve}")
        return f"タイマー設定値エラー: {ve}"
    except Exception as e:
        traceback.print_exc()
        gr.Error(f"タイマー開始時に予期せぬエラーが発生しました: {e}")
        return f"タイマー開始エラー: {e}"

def update_model_state(model):
    config_manager.save_config("last_model", model)
    return model # current_model_name (State) の更新はGradioが行う

def update_api_key_state(api_key_name):
    ok, msg = configure_google_api(api_key_name) # APIキー設定試行
    config_manager.save_config("last_api_key_name", api_key_name)
    if ok: gr.Info(f"APIキー '{api_key_name}' 設定成功。")
    else: gr.Error(f"APIキー '{api_key_name}' 設定失敗: {msg}")
    return api_key_name # current_api_key_name_state (State) の更新はGradioが行う

def update_timestamp_state(checked): config_manager.save_config("add_timestamp", bool(checked)) # Stateなし、設定のみ保存
def update_send_thoughts_state(checked):
    config_manager.save_config("last_send_thoughts_to_api", bool(checked))
    return bool(checked) # send_thoughts_state (State) を更新
def update_api_history_limit_state(limit_ui_val):
    # UI表示名から設定キーへ変換
    key = next((k for k,v in config_manager.API_HISTORY_LIMIT_OPTIONS.items() if v==limit_ui_val), "all")
    config_manager.save_config("last_api_history_limit_option", key)
    return key # api_history_limit_state (State) を更新

def reload_chat_log(character_name: Optional[str]):
    if not character_name:
        gr.Warning("キャラクターが選択されていません。")
        return [], "キャラクターを選択してください" # chatbot, log_editor
    log_f,_,_,_ = get_character_files_paths(character_name)
    if not log_f or not os.path.exists(log_f):
        gr.Warning(f"キャラクター '{character_name}' のログファイルが見つかりません。")
        return [], "" # 空の履歴と空のログエディタ内容
    history = format_history_for_gradio(load_chat_log(log_f, character_name)[-(config_manager.HISTORY_LIMIT*2):])
    content = ""
    try:
        with open(log_f, "r", encoding="utf-8") as f: content = f.read()
    except Exception as e:
        gr.Error(f"ログファイルの読み込み中にエラー: {e}")
    return history, content

def handle_save_log_button_click(character_name: Optional[str], log_content: str):
    if not character_name: gr.Error("キャラクターが選択されていません。")
    else:
        save_log_file(character_name, log_content) # utils.save_log_file を使用
        gr.Info(f"'{character_name}'のログを保存しました。")

# ★★★ ui_handlers.py の修正点: load_alarm_to_form の selected_ids 型ヒントとエラー処理 ★★★
def load_alarm_to_form(selected_ids: List[str]): # IDは文字列のリストとして渡される
    default_char = character_manager.get_character_list()[0] if character_manager.get_character_list() else "Default"
    if not selected_ids or len(selected_ids) != 1:
        # 選択がないか複数選択の場合は新規作成モードとしてフォームをリセット
        return "アラーム追加", "", "", default_char, ["月","火","水","木","金","土","日"], "08", "00", None # editing_alarm_id_state を None に

    alarm_id_str = selected_ids[0] # 最初のIDを使用
    alarm = alarm_manager.get_alarm_by_id(str(alarm_id_str)) # 念のためstr()
    if not alarm:
        gr.Warning(f"ID '{alarm_id_str}' のアラームが見つかりません。新規作成モードにします。")
        return "アラーム追加", "", "", default_char, ["月","火","水","木","金","土","日"], "08", "00", None

    h, m = alarm.get("time", "08:00").split(":")
    days_en = alarm.get("days", [])
    days_ja = [DAY_MAP_EN_TO_JA.get(d.lower(), d.upper()) for d in days_en] # 小文字で検索

    return f"アラーム更新", alarm.get("theme", ""), alarm.get("flash_prompt_template", ""), alarm.get("character", default_char), days_ja, h, m, str(alarm_id_str) # editing_alarm_id_state にIDを設定


# ★★★ ui_handlers.py の修正点: handle_add_or_update_alarm のロジックとフィードバック改善 ★★★
def handle_add_or_update_alarm(editing_id: Optional[str], h: str, m: str, char: str, theme: str, prompt: str, days: List[str]):
    default_char_for_form = character_manager.get_character_list()[0] if character_manager.get_character_list() else "Default"
    alarm_add_button_text = "アラーム更新" if editing_id else "アラーム追加" # ボタンテキストを事前に決定

    if not char: # キャラクターが選択されていない場合
        gr.Warning("キャラクターが選択されていません。アラームの追加/更新はできません。")
        # フォームの内容は変更せず、DFのみ更新して返す（実質的に何も変わらない）
        df_with_ids = render_alarms_as_dataframe()
        display_df = get_display_df(df_with_ids)
        return display_df, df_with_ids, alarm_add_button_text, theme, prompt, char, days, h, m, editing_id


    success = False
    if editing_id: # 更新の場合
        # alarm_manager.delete_alarm(editing_id) # 先に消すのは成功時のみが良い
        if alarm_manager.update_alarm(editing_id, h, m, char, theme, prompt, days):
            gr.Info(f"アラームID '{editing_id}' を更新しました。")
            success = True
        else:
             gr.Warning(f"アラームID '{editing_id}' の更新に失敗しました。")
    else: # 新規追加の場合
        new_alarm_id = alarm_manager.add_alarm(h, m, char, theme, prompt, days)
        if new_alarm_id:
            gr.Info(f"新しいアラーム (ID: {new_alarm_id}) を追加しました。")
            success = True
        else:
            gr.Warning("新しいアラームの追加に失敗しました。")

    df_with_ids = render_alarms_as_dataframe() # 最新の状態で再描画
    display_df = get_display_df(df_with_ids)

    if success: # 成功時のみフォームをリセット
        return display_df, df_with_ids, "アラーム追加", "", "", default_char_for_form, ["月","火","水","木","金","土","日"], "08", "00", None
    else: # 失敗時はフォームの内容を維持
        # current_button_text = "アラーム更新" if editing_id else "アラーム追加" # alarm_add_button_text を使用
        return display_df, df_with_ids, alarm_add_button_text, theme, prompt, char, days, h, m, editing_id
