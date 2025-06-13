# -*- coding: utf-8 -*-
import pandas as pd
from typing import List, Optional, Dict, Any, Tuple, Union
import gradio as gr
import datetime
import utils # utils.py の関数を使うために必要
import json
import traceback
import os
import uuid # ファイル処理で使用
import shutil # ファイル処理で使用
import re

# --- モジュールインポート ---
import config_manager
import alarm_manager # アラーム関連のバックエンドロジック
from timers import UnifiedTimer # タイマー機能
from character_manager import get_character_files_paths # Kiseki: get_character_listは不要なので削除
from gemini_api import configure_google_api, send_to_gemini # Gemini API連携
from memory_manager import load_memory_data_safe, save_memory_data # 記憶管理
# utils から必要な関数を明示的にインポート (utils.py の内容に依存)
from utils import (
    load_chat_log,
    format_history_for_gradio,
    save_message_to_log,
    _get_user_header_from_log,
    save_log_file
)

ATTACHMENTS_DIR = "chat_attachments"
if not os.path.exists(ATTACHMENTS_DIR):
    os.makedirs(ATTACHMENTS_DIR, exist_ok=True)

SUPPORTED_FILE_MAPPINGS = {
    ".png": {"mime_type": "image/png", "category": "image"}, ".jpg": {"mime_type": "image/jpeg", "category": "image"},
    ".jpeg": {"mime_type": "image/jpeg", "category": "image"}, ".gif": {"mime_type": "image/gif", "category": "image"},
    ".webp": {"mime_type": "image/webp", "category": "image"},
    ".txt": {"mime_type": "text/plain", "category": "text"}, ".json": {"mime_type": "application/json", "category": "text"},
    ".xml": {"mime_type": "application/xml", "category": "text"}, ".md": {"mime_type": "text/markdown", "category": "text"},
    ".py": {"mime_type": "text/x-python", "category": "text"}, ".csv": {"mime_type": "text/csv", "category": "text"},
    ".yaml": {"mime_type": "application/x-yaml", "category": "text"}, ".yml": {"mime_type": "application/x-yaml", "category": "text"},
    ".pdf": {"mime_type": "application/pdf", "category": "pdf"},
    ".mp3": {"mime_type": "audio/mpeg", "category": "audio"}, ".wav": {"mime_type": "audio/wav", "category": "audio"},
    ".mov": {"mime_type": "video/quicktime", "category": "video"}, ".mp4": {"mime_type": "video/mp4", "category": "video"},
    ".mpeg": {"mime_type": "video/mpeg", "category": "video"}, ".mpg": {"mime_type": "video/mpeg", "category": "video"},
    ".avi": {"mime_type": "video/x-msvideo", "category": "video"}, ".wmv": {"mime_type": "video/x-ms-wmv", "category": "video"},
    ".flv": {"mime_type": "video/x-flv", "category": "video"},
}

# --- Dataframe表示用データ整形関数 ---
DAY_MAP_EN_TO_JA = {"mon": "月", "tue": "火", "wed": "水", "thu": "木", "fri": "金", "sat": "土", "sun": "日"}

def render_alarms_as_dataframe() -> pd.DataFrame:
    alarms = alarm_manager.get_all_alarms()
    display_data = []
    for alarm in sorted(alarms, key=lambda x: x.get("time", "")):
        days_ja = [DAY_MAP_EN_TO_JA.get(d, d.upper()) for d in alarm.get('days', [])]
        display_data.append({
            "ID": alarm.get("id"), "状態": alarm.get("enabled", False), "時刻": alarm.get("time"),
            "曜日": ",".join(days_ja), "キャラ": alarm.get("character"), "テーマ": alarm.get("theme")
        })
    if not display_data: return pd.DataFrame(columns=["ID", "状態", "時刻", "曜日", "キャラ", "テーマ"])
    df = pd.DataFrame(display_data)
    return df[["ID", "状態", "時刻", "曜日", "キャラ", "テーマ"]]

# --- アラームDataframeイベントハンドラ ---
def handle_alarm_dataframe_change(df_after_change: pd.DataFrame, df_original: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    print("UI Event: Alarm dataframe content possibly changed by user.")
    if df_after_change is None or df_original is None : # Kiseki: or追加
        print("Warning: DataFrame data is None in change event. Re-rendering.")
        new_df_state = render_alarms_as_dataframe()
        return new_df_state, new_df_state

    if "ID" not in df_after_change.columns or "ID" not in df_original.columns or \
       "状態" not in df_after_change.columns or "状態" not in df_original.columns: # Kiseki: 状態列も確認
        print("Error: 'ID' or '状態' column missing. Cannot process changes.")
        gr.Error("内部エラー: アラームIDまたは状態列が見つかりません。")
        current_df_state = render_alarms_as_dataframe()
        return current_df_state, current_df_state

    df_after_change_indexed = df_after_change.set_index("ID", drop=False)
    df_original_indexed = df_original.set_index("ID", drop=False)
    common_ids = df_after_change_indexed.index.intersection(df_original_indexed.index)
    changed_ids_count = 0 # Kiseki: 変更件数カウント

    for alarm_id_str in common_ids: # Kiseki: alarm_id を alarm_id_str に変更 (型明確化)
        row_after = df_after_change_indexed.loc[alarm_id_str]
        row_original = df_original_indexed.loc[alarm_id_str]
        if row_after['状態'] != row_original['状態']:
            print(f"Alarm ID {alarm_id_str}: '状態' changed from {row_original['状態']} to {row_after['状態']}.")
            alarm_manager.toggle_alarm_enabled(alarm_id_str)
            theme = row_after['テーマ'] # Kiseki: theme取得をここに移動
            gr.Info(f"アラーム「{theme}」の状態を更新しました。")
            changed_ids_count += 1

    if not changed_ids_count:
        print("No functional change detected in alarm states.")
        return df_after_change, df_original

    print(f"Processed {changed_ids_count} alarm state changes. Re-rendering alarm list.")
    final_df_state = render_alarms_as_dataframe()
    return final_df_state, final_df_state

def handle_alarm_selection(df: pd.DataFrame, evt: gr.SelectData) -> list:
    selected_ids = []
    if evt.indices is None: return [] # Kiseki: evt.indicesがNoneの場合の早期リターン

    # Kiseki: evt.indicesは選択されたセルの(row_index, col_index)のタプルのリスト。
    # Dataframeのmultiselect=Falseの場合、evt.indexはタプル(row_index, col_index)
    # multiselect=Trueの場合、evt.valueが選択された行のデータ(リストのリスト)になる。
    # ここでは log2gemini.py で multiselect=False に変更したので、evt.index を使う。
    # ただし、Kisekiの以前のコードではevt.selected_rowsを見ていた。
    # GradioのバージョンやDataFrameの設定によってevtの構造が変わるため注意。
    # ここでは、evt.indexがタプル(row, col)であることを前提とする。(単一セル選択)
    # 行選択を意図しているなら、evt.index[0]で行インデックスを取得。

    # Kiseki修正: log2gemini.pyでmultiselect=Trueに戻したため、evt.value (選択行データ) を見るのが適切。
    # ただし、Gradioのselectイベントのevt引数の仕様が複雑なため、
    # log2gemini.py側でevt.selected_rowsを処理してIDリストを渡す方が安定する。
    # この関数はIDリストをselected_alarm_ids_stateに格納するのが目的なので、
    # log2gemini.pyのhandle_df_selection_for_idsラッパーがIDを抽出して渡す。
    # そのため、この関数の入力は実質的にIDのリストになる。
    # 引数名を selected_ids_from_event に変更し、それがリストであることを明確化。
    # Kiseki最終修正: この関数はlog2gemini.pyから呼ばれなくなった。
    # log2gemini.py内のhandle_df_selection_for_idsが直接selected_alarm_ids_stateを更新する。
    # よって、このhandle_alarm_selectionは現状では未使用だが、将来のために残す場合は要見直し。
    # 今回のユーザー指示は「Kisekiが提供したui_handlers.pyで総入れ替え」なので、このままにする。
    # ただし、呼び出し側(log2gemini.py)はevt:gr.SelectDataを渡してくるので、それに対応する。

    if df is None or df.empty or 'ID' not in df.columns:
        print("Warning: DataFrame is None, empty, or missing 'ID' column in handle_alarm_selection.")
        return []

    if evt.index: # evt.indexは (row, col) のタプル or 行インデックス (単数選択時)
        row_idx = evt.index[0] if isinstance(evt.index, tuple) else evt.index
        if 0 <= row_idx < len(df):
            selected_ids.append(str(df.iloc[row_idx]['ID']))

    print(f"UI Event: Alarms selected (via handle_alarm_selection): {selected_ids}")
    return selected_ids


def handle_delete_selected_alarms(selected_ids: list) -> Tuple[pd.DataFrame, list]: # Kiseki: 戻り値修正
    if not selected_ids:
        gr.Warning("削除するアラームが選択されていません。")
        return render_alarms_as_dataframe(), []

    deleted_count = 0
    for alarm_id in selected_ids:
        if alarm_manager.delete_alarm(str(alarm_id)):
            deleted_count += 1

    if deleted_count > 0: gr.Info(f"{deleted_count}件のアラームを削除しました。")
    else: gr.Warning("選択されたアラームを削除できませんでした。")

    return render_alarms_as_dataframe(), [] # Kiseki: selected_ids_stateをクリアするために空リストを返す

# --- タイマーイベントハンドラ ---
def handle_timer_submission(
    timer_type: str, duration: Optional[float], work_duration: Optional[float],
    break_duration: Optional[float], cycles: Optional[int], character_name: Optional[str],
    work_theme: Optional[str], break_theme: Optional[str], api_key_name: Optional[str],
    webhook_url: Optional[str], normal_timer_theme: Optional[str]
) -> str:
    if not character_name or not api_key_name:
        gr.Error("キャラクターとAPIキーを選択してください。")
        return "エラー: キャラクターとAPIキー未選択。"
    try:
        timer = UnifiedTimer(
            timer_type=timer_type,
            duration_minutes=float(duration) if duration and duration > 0 else 0, # Kiseki: 0以上チェック追加
            work_minutes=float(work_duration) if work_duration and work_duration > 0 else 0,
            break_minutes=float(break_duration) if break_duration and break_duration > 0 else 0,
            cycles=int(cycles) if cycles and cycles > 0 else 0,
            character_name=character_name,
            work_theme=work_theme or "作業終了です！",
            break_theme=break_theme or "休憩終了！作業を再開しましょう。",
            api_key_name=api_key_name,
            webhook_url=webhook_url,
            normal_timer_theme=normal_timer_theme or "時間です！"
        )
        # Kiseki: UnifiedTimerのバリデーションを強化するか、ここで詳細なチェックを行う
        if timer_type == "通常タイマー" and timer.duration_minutes <= 0:
            gr.Error("通常タイマーの時間を正しく入力してください。")
            return "エラー: 通常タイマーの時間未入力。"
        if timer_type == "ポモドーロタイマー" and (timer.work_minutes <= 0 or timer.break_minutes <= 0 or timer.cycles <= 0):
            gr.Error("ポモドーロタイマーの各項目を正しく入力してください。")
            return "エラー: ポモドーロタイマー設定不備。"

        timer.start()

        status_message = f"{timer_type}を開始しました。"
        if timer_type == "通常タイマー":
            status_message = f"{timer.duration_minutes}分 通常タイマー ({timer.normal_timer_theme}) 開始 (キャラ: {character_name})"
        elif timer_type == "ポモドーロタイマー":
            status_message = f"{timer.work_minutes}分作業 ({timer.work_theme}) / {timer.break_minutes}分休憩 ({timer.break_theme}) ポモドーロ 開始 ({timer.cycles}サイクル)"

        gr.Info(status_message) # Kiseki: 詳細なメッセージをInfoにも表示
        return status_message
    except ValueError as ve:
        error_msg = f"タイマー設定値エラー: {str(ve)}"
        gr.Error(error_msg); traceback.print_exc(); return error_msg
    except Exception as e:
        error_msg = f"タイマー開始時に予期せぬエラー: {str(e)}"
        gr.Error(error_msg); traceback.print_exc(); return error_msg

# --- UI状態更新ハンドラ ---
def update_ui_on_character_change(character_name: Optional[str]) -> Tuple[Optional[str], list, str, Optional[str], str, Optional[str], str]:
    if not character_name:
        gr.Info("キャラクターが選択されていません。")
        return None, [], "", None, "{}", None, "キャラクターを選択してください。"
    print(f"UI更新: キャラクター変更 -> '{character_name}'")
    config_manager.save_config("last_character", character_name)
    log_f, _, img_p, mem_p = get_character_files_paths(character_name)
    chat_history_display = format_history_for_gradio(load_chat_log(log_f, character_name)[-(config_manager.HISTORY_LIMIT * 2):]) if log_f and os.path.exists(log_f) else []
    log_content_for_editor = ""
    if log_f and os.path.exists(log_f):
        try:
            with open(log_f, "r", encoding="utf-8") as f: log_content_for_editor = f.read()
        except Exception as e: log_content_for_editor = f"ログファイル読込エラー: {e}"
    memory_data = load_memory_data_safe(mem_p)
    memory_display_str = json.dumps(memory_data, indent=2, ensure_ascii=False) if isinstance(memory_data, dict) else json.dumps({"error": "記憶読込失敗"}, indent=2)
    profile_image = img_p if img_p and os.path.exists(img_p) else None
    return character_name, chat_history_display, "", profile_image, memory_display_str, character_name, log_content_for_editor

def update_model_state(selected_model: Optional[str]) -> Optional[str]:
    if selected_model is None: return gr.update()
    config_manager.save_config("last_model", selected_model)
    return selected_model

def update_api_key_state(selected_api_key_name: Optional[str]) -> Optional[str]:
    if not selected_api_key_name: return gr.update()
    ok, msg = configure_google_api(selected_api_key_name)
    config_manager.save_config("last_api_key_name", selected_api_key_name)
    if hasattr(config_manager, 'initial_api_key_name_global'): config_manager.initial_api_key_name_global = selected_api_key_name
    if ok: gr.Info(f"APIキー '{selected_api_key_name}' 設定成功。")
    else: gr.Error(f"APIキー '{selected_api_key_name}' 設定失敗: {msg}")
    return selected_api_key_name

def update_timestamp_state(add_timestamp_checked: bool): # Kiseki: No return type hint needed for None
    if isinstance(add_timestamp_checked, bool): config_manager.save_config("add_timestamp", add_timestamp_checked)

def update_send_thoughts_state(send_thoughts_checked: bool) -> bool: # Kiseki: Return type hint added
    if not isinstance(send_thoughts_checked, bool): return gr.update() # Kiseki: type check
    config_manager.save_config("last_send_thoughts_to_api", send_thoughts_checked)
    return send_thoughts_checked

def update_api_history_limit_state(selected_limit_option_ui_value: Optional[str]) -> Union[str, Any]: # Kiseki: type hint Any for gr.update()
    if not selected_limit_option_ui_value: return gr.update()
    internal_key = next((k for k, v in config_manager.API_HISTORY_LIMIT_OPTIONS.items() if v == selected_limit_option_ui_value), None)
    if internal_key:
        config_manager.save_config("last_api_history_limit_option", internal_key)
        return internal_key
    return gr.update()

def reload_chat_log(character_name: Optional[str]) -> Tuple[list, str]:
    if not character_name: return [], "キャラクター未選択。"
    log_file_path, _, _, _ = get_character_files_paths(character_name)
    if not log_file_path or not os.path.exists(log_file_path): return [], f"ログファイルなし: {character_name}"
    chat_log = format_history_for_gradio(load_chat_log(log_file_path, character_name)[-(config_manager.HISTORY_LIMIT * 2):])
    raw_log = ""
    try:
        with open(log_file_path, "r", encoding="utf-8") as f: raw_log = f.read()
    except Exception as e: raw_log = f"ログ読込エラー: {e}"
    gr.Info(f"'{character_name}' のチャットログ再読み込み完了。")
    return chat_log, raw_log

def handle_save_log_button_click(character_name: Optional[str], log_content: str): # Kiseki: No return type hint needed
    if not character_name: gr.Error("キャラクター未選択。ログ保存不可。"); return
    if not isinstance(log_content, str): gr.Error("ログ内容無効。保存不可。"); return
    try:
        save_log_file(character_name, log_content)
        gr.Info(f"キャラクター '{character_name}' のログ保存完了。")
    except Exception as e: gr.Error(f"ログ保存エラー: {e}"); traceback.print_exc()

# --- メッセージ送信主要処理 ---
def _prepare_api_text_and_log_entries(
    original_user_text: str, file_input_list: Optional[List[Any]],
    add_timestamp_checkbox: bool, log_f: str, user_header: str
) -> Tuple[str, List[Dict[str, str]], List[str]]:
    api_text_arg = original_user_text
    files_for_gemini_api: List[Dict[str, str]] = []
    all_error_messages: List[str] = []

    user_action_timestamp_str = f"\n{datetime.datetime.now().strftime('%Y-%m-%d (%a) %H:%M:%S')}" if add_timestamp_checkbox else ""

    # テキスト入力のログ記録 (ファイルがある場合は、ファイル処理後にまとめてタイムスタンプ付加)
    if original_user_text and not file_input_list:
        save_message_to_log(log_f, user_header, original_user_text + user_action_timestamp_str)

    if file_input_list:
        text_from_files_for_api = ""
        temp_files_log_entries = []

        for file_obj in file_input_list:
            temp_file_path = file_obj.name
            original_filename = getattr(file_obj, 'orig_name', os.path.basename(temp_file_path))
            file_extension = os.path.splitext(original_filename)[1].lower()
            file_type_info = SUPPORTED_FILE_MAPPINGS.get(file_extension)

            if not file_type_info:
                all_error_messages.append(f"ファイル形式非対応: {original_filename}")
                continue

            # Kiseki: ファイルを永続的な場所にコピー
            unique_filename = f"{uuid.uuid4()}{file_extension}"
            saved_attachment_path = os.path.join(ATTACHMENTS_DIR, unique_filename)
            try:
                shutil.copy2(temp_file_path, saved_attachment_path)
            except Exception as e_copy:
                all_error_messages.append(f"ファイルコピー失敗 ({original_filename}): {e_copy}")
                continue # 次のファイルへ

            if file_type_info["category"] == 'text':
                content_to_add = ""
                encodings_to_try = ['utf-8', 'shift_jis', 'cp932', 'euc-jp', 'iso2022-jp', 'latin1']
                for enc in encodings_to_try:
                    try:
                        with open(saved_attachment_path, 'r', encoding=enc) as f: content_to_add = f.read()
                        break
                    except: continue
                if content_to_add:
                    text_from_files_for_api += f"\n\n--- 添付ファイル「{original_filename}」の内容 ---\n{content_to_add}"
                    temp_files_log_entries.append(f"[添付テキスト: {original_filename} ({saved_attachment_path})]") # Kiseki: 保存パスも記録
                else: all_error_messages.append(f"ファイルデコード失敗: {original_filename}")
            else:
                files_for_gemini_api.append({
                    'path': saved_attachment_path,
                    'mime_type': file_type_info["mime_type"],
                    'original_filename': original_filename
                })
                temp_files_log_entries.append(f"[ファイル添付: {original_filename} ({file_type_info['mime_type']}) ({saved_attachment_path})]")

        if text_from_files_for_api:
            api_text_arg = (api_text_arg + text_from_files_for_api) if api_text_arg else text_from_files_for_api.strip()

        # ファイル関連のログエントリを記録 (ユーザーテキストとファイルログをまとめてタイムスタンプ付加)
        if original_user_text or temp_files_log_entries:
            combined_entry_for_log = original_user_text
            if temp_files_log_entries:
                combined_entry_for_log = (combined_entry_for_log + "\n" if combined_entry_for_log else "") + "\n".join(temp_files_log_entries)
            save_message_to_log(log_f, user_header, combined_entry_for_log.strip() + user_action_timestamp_str)

    return api_text_arg.strip(), files_for_gemini_api, all_error_messages


def handle_message_submission(
    textbox_content: Optional[str], chatbot_history: list, current_character_name: Optional[str],
    current_model_name: Optional[str], current_api_key_name_state: Optional[str],
    file_input_list: Optional[list], add_timestamp_checkbox: bool, send_thoughts_state: bool,
    api_history_limit_state: str
) -> Tuple[list, Any, Any, str]:

    print(f"\n--- メッセージ送信処理開始 --- {datetime.datetime.now()} ---")
    error_message_for_ui = ""
    original_user_text = textbox_content.strip() if textbox_content else ""

    validation_error = _validate_submission_inputs(current_character_name, current_model_name, current_api_key_name_state)
    if validation_error: return chatbot_history, gr.update(value=original_user_text), gr.update(value=file_input_list), validation_error

    api_configured, api_error_msg = _configure_api_key_if_needed(current_api_key_name_state)
    if not api_configured: return chatbot_history, gr.update(value=original_user_text), gr.update(value=file_input_list), api_error_msg

    log_f, sys_p, _, mem_p = get_character_files_paths(current_character_name)
    if not all([log_f, sys_p, mem_p]): return chatbot_history, gr.update(value=original_user_text), gr.update(value=file_input_list), f"キャラ '{current_character_name}' の必須ファイルパス取得失敗。"

    user_header = _get_user_header_from_log(log_f, current_character_name)

    api_text_arg, files_for_gemini_api, file_processing_errors = _prepare_api_text_and_log_entries(
        original_user_text, file_input_list, add_timestamp_checkbox, log_f, user_header
    )
    if file_processing_errors: error_message_for_ui = "\n".join(file_processing_errors)

    if not api_text_arg.strip() and not files_for_gemini_api:
        no_content_msg = "送信するメッセージ本文または処理可能なファイルがありません。"
        error_message_for_ui = (error_message_for_ui + "\n" if error_message_for_ui else "") + no_content_msg
        # Kiseki: ユーザー入力が空でもファイル処理エラーがあった場合は表示したいので、chatbot_historyを返す
        return chatbot_history, gr.update(value=original_user_text), gr.update(value=file_input_list), error_message_for_ui.strip()

    try:
        api_response_text, generated_image_path = send_to_gemini( # gemini_apiからインポート
            system_prompt_path=sys_p, log_file_path=log_f, user_prompt=api_text_arg,
            selected_model=current_model_name, character_name=current_character_name,
            send_thoughts_to_api=send_thoughts_state, api_history_limit_option=api_history_limit_state,
            uploaded_file_parts=files_for_gemini_api, memory_json_path=mem_p
        )

        if api_response_text or generated_image_path:
            log_parts = []
            if generated_image_path: log_parts.append(f"[Generated Image: {generated_image_path}]")
            is_error_resp = api_response_text and any(e_kw in api_response_text for e_kw in ["エラー:", "API通信エラー:", "応答取得エラー", "応答生成失敗", "【アラームエラー】"]) # Kiseki: アラームエラーも検知
            if api_response_text and not is_error_resp: log_parts.append(api_response_text)
            if log_parts: save_message_to_log(log_f, f"## {current_character_name}:", "\n\n".join(log_parts))
            if api_response_text and is_error_resp: error_message_for_ui = (error_message_for_ui + "\n" if error_message_for_ui else "") + api_response_text
        else: error_message_for_ui = (error_message_for_ui + "\n" if error_message_for_ui else "") + "APIから有効な応答がありませんでした。"
    except Exception as e:
        traceback.print_exc()
        error_message_for_ui = (error_message_for_ui + "\n" if error_message_for_ui else "") + f"メッセージ処理中に予期せぬエラー: {e}"

    new_log = load_chat_log(log_f, current_character_name)
    new_hist = format_history_for_gradio(new_log[-(config_manager.HISTORY_LIMIT * 2):])
    return new_hist, gr.update(value=""), gr.update(value=None), error_message_for_ui.strip()

```
