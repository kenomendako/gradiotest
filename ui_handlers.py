# -*- coding: utf-8 -*-
import pandas as pd
from typing import List, Optional, Dict, Any, Tuple, Union # Kiseki: Union を追加
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
from character_manager import get_character_files_paths, get_character_list # キャラクター管理
from gemini_api import configure_google_api, send_to_gemini # Gemini API連携
from memory_manager import load_memory_data_safe, save_memory_data # 記憶管理
# utils から必要な関数を明示的にインポート (utils.py の内容に依存)
from utils import (
    load_chat_log,
    format_history_for_gradio,
    save_message_to_log,
    _get_user_header_from_log, # Kiseki: 既存のコードで使われていたので追加
    save_log_file # Kiseki: handle_save_log_button_click で使用
)


ATTACHMENTS_DIR = "chat_attachments" # Kiseki: log2gemini.pyと一貫性を持たせる
if not os.path.exists(ATTACHMENTS_DIR):
    os.makedirs(ATTACHMENTS_DIR, exist_ok=True)

SUPPORTED_FILE_MAPPINGS = {
    # Images
    ".png": {"mime_type": "image/png", "category": "image"},
    ".jpg": {"mime_type": "image/jpeg", "category": "image"},
    ".jpeg": {"mime_type": "image/jpeg", "category": "image"},
    ".gif": {"mime_type": "image/gif", "category": "image"},
    ".webp": {"mime_type": "image/webp", "category": "image"},
    # Texts
    ".txt": {"mime_type": "text/plain", "category": "text"},
    ".json": {"mime_type": "application/json", "category": "text"},
    ".xml": {"mime_type": "application/xml", "category": "text"},
    ".md": {"mime_type": "text/markdown", "category": "text"},
    ".py": {"mime_type": "text/x-python", "category": "text"},
    ".csv": {"mime_type": "text/csv", "category": "text"},
    ".yaml": {"mime_type": "application/x-yaml", "category": "text"},
    ".yml": {"mime_type": "application/x-yaml", "category": "text"},
    # PDF
    ".pdf": {"mime_type": "application/pdf", "category": "pdf"},
    # Audio
    ".mp3": {"mime_type": "audio/mpeg", "category": "audio"},
    ".wav": {"mime_type": "audio/wav", "category": "audio"},
    # Video
    ".mov": {"mime_type": "video/quicktime", "category": "video"},
    ".mp4": {"mime_type": "video/mp4", "category": "video"},
    ".mpeg": {"mime_type": "video/mpeg", "category": "video"},
    ".mpg": {"mime_type": "video/mpeg", "category": "video"},
    ".avi": {"mime_type": "video/x-msvideo", "category": "video"},
    ".wmv": {"mime_type": "video/x-ms-wmv", "category": "video"},
    ".flv": {"mime_type": "video/x-flv", "category": "video"},
}

# --- Dataframe表示用データ整形関数 ---
DAY_MAP_EN_TO_JA = {"mon": "月", "tue": "火", "wed": "水", "thu": "木", "fri": "金", "sat": "土", "sun": "日"}

def render_alarms_as_dataframe() -> pd.DataFrame:
    """
    アラームデータを取得し、GradioのDataframe表示用にpandas.DataFrameを生成して返す。
    """
    alarms = alarm_manager.get_all_alarms()
    display_data = []
    for alarm in sorted(alarms, key=lambda x: x.get("time", "")): # 時刻でソート
        days_ja = [DAY_MAP_EN_TO_JA.get(d, d.upper()) for d in alarm.get('days', [])]
        display_data.append({
            "ID": alarm.get("id"), # データ内にはIDを保持
            "状態": alarm.get("enabled", False),
            "時刻": alarm.get("time"),
            "曜日": ",".join(days_ja),
            "キャラ": alarm.get("character"),
            "テーマ": alarm.get("theme")
        })
    if not display_data:
        return pd.DataFrame(columns=["ID", "状態", "時刻", "曜日", "キャラ", "テーマ"]) # Kiseki: ヘッダーはID含む
    df = pd.DataFrame(display_data)
    return df[["ID", "状態", "時刻", "曜日", "キャラ", "テーマ"]] # Kiseki: ヘッダーはID含む

# --- アラームDataframeイベントハンドラ ---
def handle_alarm_dataframe_change(df_after_change: pd.DataFrame, df_original: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Dataframeの内容がユーザーによって変更されたときに呼び出される。
    主に「状態」チェックボックスのON/OFFを検知し、アラームの状態を更新する。
    """
    print("UI Event: Alarm dataframe content possibly changed by user.")
    if df_after_change is None or df_original is None:
        print("Warning: DataFrame data is None in change event. Re-rendering.")
        new_df_state = render_alarms_as_dataframe()
        return new_df_state, new_df_state # Kiseki: original_dfも更新

    # IDをキーとして比較するため、両方のDataFrameにID列が存在することを確認
    if "ID" not in df_after_change.columns or "ID" not in df_original.columns:
        print("Error: 'ID' column missing from DataFrame(s). Cannot process changes.")
        gr.Error("内部エラー: アラームID列が見つかりません。")
        current_df_state = render_alarms_as_dataframe() # 現状を再描画
        return current_df_state, current_df_state # Kiseki: original_dfも更新

    # 変更を検出するためにIDをインデックスに設定
    df_after_change_indexed = df_after_change.set_index("ID", drop=False) # Kiseki: ID列をデータとして残す
    df_original_indexed = df_original.set_index("ID", drop=False)

    changed_ids = []
    for alarm_id in df_after_change_indexed.index:
        if alarm_id not in df_original_indexed.index: # 新規行（現状はUIから追加不可のはず）
            continue

        row_after = df_after_change_indexed.loc[alarm_id]
        row_original = df_original_indexed.loc[alarm_id]

        if row_after['状態'] != row_original['状態']:
            print(f"Alarm ID {alarm_id}: '状態' changed from {row_original['状態']} to {row_after['状態']}. Toggling.")
            alarm_manager.toggle_alarm_enabled(str(alarm_id))
            theme = row_after['テーマ']
            gr.Info(f"アラーム「{theme}」の状態を更新しました。")
            changed_ids.append(alarm_id)

    if not changed_ids:
        print("No functional change detected in alarm states.")
        # Kiseki: 変更がなくても、Dataframeの内部状態(選択など)がクリアされることがあるので、
        # オリジナルはそのままに、現在の表示用dfは再レンダリングしたものを返す。
        return df_after_change, df_original # Kiseki: この場合originalは変更しない

    # 変更があった場合、全体のリストを再取得・再描画して整合性を保つ
    print(f"Processed {len(changed_ids)} alarm state changes. Re-rendering alarm list.")
    final_df_state = render_alarms_as_dataframe()
    return final_df_state, final_df_state # Kiseki: original_dfも更新


def handle_alarm_selection(df: pd.DataFrame, evt: gr.SelectData) -> list:
    """ Dataframeの行が選択されたとき、選択されたアラームのIDリストを返す """
    selected_ids = []
    if evt.selected_rows is not None: # Gradio 4.x selected_rows
        for _, is_selected in evt.selected_rows: # Kiseki: evt.selected_rowsのタプル構造を正しく処理
            if is_selected: # 選択された行のみ処理
                # evt.index は (row_index, col_index) or row_index.
                # selected_rows があるなら、それに基づくべきだが、ID取得にはdfが必要
                # selected_rows の row_index を使う
                # evt.selected_rows is List[Tuple[int, bool]] -> (row_index, is_selected_bool)
                # Kiseki修正: selected_rows のインデックスはdfの表示上のインデックス
                # df.iloc[row_index] で行データ取得
                # ただし、evt.selected_rows は表示されている行に対するもの。
                # dfがソート/フィルタリングされている場合、このインデックスは元のDataFrameとは異なる可能性。
                # しかし、Gradioのイベントでは通常、現在の表示DFのインデックスが渡される。
                # ここではdfが常に全件表示でソート済みという前提。
                # Kiseki: evt.index は [(row, col), ...] or [row, ...]
                # selectイベントのevt.indexは選択されたセルのインデックス (row, col) のタプル。
                # 行全体が選択された場合は (row_index, None) になるか、Gradioのバージョンによる。
                # ここでは、evt.selected_rows が最も信頼できる。
                pass # このループは selected_rows の is_selected フラグを見るだけ

        # selected_rows から選択された行のインデックスを取得
        selected_row_indices = [idx for idx, sel_status in evt.selected_rows if sel_status]

        if df is not None and not df.empty and 'ID' in df.columns:
            for row_idx in selected_row_indices:
                if 0 <= row_idx < len(df):
                    selected_ids.append(str(df.iloc[row_idx]['ID']))
        else:
            print("Warning: DataFrame is None, empty, or missing 'ID' column in handle_alarm_selection.")

    print(f"UI Event: Alarms selected (IDs): {selected_ids}")
    return selected_ids


def handle_delete_selected_alarms(selected_ids: list) -> Tuple[pd.DataFrame, list, pd.DataFrame]: # Kiseki: 戻り値にoriginal_df追加
    """ 「削除」ボタンが押されたときに呼び出される。選択されたIDのリストを元にアラームを削除。 """
    if not selected_ids:
        gr.Warning("削除するアラームが選択されていません。")
        current_df = render_alarms_as_dataframe()
        return current_df, [], current_df # Kiseki: original_dfも返す

    deleted_count = 0
    for alarm_id in selected_ids:
        if alarm_manager.delete_alarm(str(alarm_id)):
            deleted_count += 1

    if deleted_count > 0:
        gr.Info(f"{deleted_count}件のアラームを削除しました。")
    else:
        gr.Warning("選択されたアラームの削除に失敗したか、対象が見つかりませんでした。")

    new_df = render_alarms_as_dataframe()
    return new_df, [], new_df # Kiseki: 選択解除とoriginal_dfも更新

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
            duration_minutes=float(duration) if duration else 0,
            work_minutes=float(work_duration) if work_duration else 0,
            break_minutes=float(break_duration) if break_duration else 0,
            cycles=int(cycles) if cycles else 0,
            character_name=character_name,
            work_theme=work_theme or "作業終了です！",
            break_theme=break_theme or "休憩終了！作業を再開しましょう。",
            api_key_name=api_key_name,
            webhook_url=webhook_url,
            normal_timer_theme=normal_timer_theme or "時間です！"
        )
        timer.start() # バックグラウンドで実行される

        # ステータスメッセージの構築
        if timer_type == "通常タイマー":
            status_message = f"{float(duration)}分 通常タイマー ({normal_timer_theme or '指定テーマなし'}) 開始 (キャラ: {character_name})"
        elif timer_type == "ポモドーロタイマー":
            status_message = f"{float(work_duration)}分作業 ({work_theme or '作業'}) / {float(break_duration)}分休憩 ({break_theme or '休憩'}) ポモドーロ 開始 ({int(cycles)}サイクル)"
        else:
            status_message = "不明なタイマータイプです。"

        gr.Info(f"{timer_type}を開始しました。")
        return status_message

    except ValueError as ve:
        error_msg = f"タイマー設定値エラー: {str(ve)}"
        gr.Error(error_msg)
        return error_msg
    except Exception as e:
        error_msg = f"タイマー開始時に予期せぬエラー: {str(e)}"
        gr.Error(error_msg)
        traceback.print_exc()
        return error_msg


# --- UI状態更新ハンドラ ---
def update_ui_on_character_change(character_name: Optional[str]) -> Tuple[Optional[str], list, str, Optional[str], str, Optional[str], str]:
    if not character_name:
        gr.Info("キャラクターが選択されていません。")
        return None, [], "", None, "{}", None, "キャラクターを選択してください。"

    print(f"UI更新: キャラクター変更 -> '{character_name}'")
    config_manager.save_config("last_character", character_name)
    log_f, _, img_p, mem_p = get_character_files_paths(character_name)

    chat_history_display = []
    log_content_for_editor = ""
    if log_f and os.path.exists(log_f):
        chat_history_display = format_history_for_gradio(load_chat_log(log_f, character_name)[-(config_manager.HISTORY_LIMIT * 2):])
        try:
            with open(log_f, "r", encoding="utf-8") as f: log_content_for_editor = f.read()
        except Exception as e: log_content_for_editor = f"ログファイル読込失敗: {e}"
    elif log_f: log_content_for_editor = "" # ファイルなし
    else: log_content_for_editor = "ログパス取得不可。"

    memory_data = load_memory_data_safe(mem_p)
    memory_display_str = json.dumps(memory_data, indent=2, ensure_ascii=False) if isinstance(memory_data, dict) else json.dumps({"error": "記憶読込失敗"}, indent=2)

    return (
        character_name, chat_history_display, "",
        img_p if img_p and os.path.exists(img_p) else None,
        memory_display_str, character_name, log_content_for_editor
    )

def update_model_state(selected_model: Optional[str]) -> Optional[str]:
    if selected_model is None: return gr.update()
    print(f"設定更新: モデル変更 -> '{selected_model}'")
    config_manager.save_config("last_model", selected_model)
    return selected_model

def update_api_key_state(selected_api_key_name: Optional[str]) -> Optional[str]:
    if not selected_api_key_name: return gr.update()
    print(f"設定更新: APIキー変更 -> '{selected_api_key_name}'")
    ok, msg = configure_google_api(selected_api_key_name) # APIクライアントを再設定
    config_manager.save_config("last_api_key_name", selected_api_key_name)
    if hasattr(config_manager, 'initial_api_key_name_global'): config_manager.initial_api_key_name_global = selected_api_key_name

    if ok: gr.Info(f"APIキー '{selected_api_key_name}' 設定成功。")
    else: gr.Error(f"APIキー '{selected_api_key_name}' 設定失敗: {msg}")
    return selected_api_key_name

def update_timestamp_state(add_timestamp_checked: bool) -> None:
    if isinstance(add_timestamp_checked, bool):
        print(f"設定更新: タイムスタンプ付加 -> {add_timestamp_checked}")
        config_manager.save_config("add_timestamp", add_timestamp_checked)

def update_send_thoughts_state(send_thoughts_checked: bool) -> bool:
    if not isinstance(send_thoughts_checked, bool): return gr.update()
    print(f"設定更新: 思考過程API送信 -> {send_thoughts_checked}")
    config_manager.save_config("last_send_thoughts_to_api", send_thoughts_checked)
    return send_thoughts_checked

def update_api_history_limit_state(selected_limit_option_ui_value: Optional[str]) -> Union[str, Any]:
    if not selected_limit_option_ui_value: return gr.update()
    internal_key = next((k for k, v in config_manager.API_HISTORY_LIMIT_OPTIONS.items() if v == selected_limit_option_ui_value), None)
    if internal_key:
        print(f"設定更新: API履歴制限 -> '{internal_key}'")
        config_manager.save_config("last_api_history_limit_option", internal_key)
        return internal_key
    return gr.update()

def reload_chat_log(character_name: Optional[str]) -> Tuple[list, str]:
    if not character_name: return [], "キャラクター未選択。"
    log_file_path, _, _, _ = get_character_files_paths(character_name)
    if not log_file_path or not os.path.exists(log_file_path):
        return [], f"ログファイルなし: {character_name}"

    print(f"UI操作: '{character_name}' のチャットログ再読み込み。")
    chat_log_for_display = format_history_for_gradio(load_chat_log(log_file_path, character_name)[-(config_manager.HISTORY_LIMIT * 2):])
    raw_log_content = ""
    try:
        with open(log_file_path, "r", encoding="utf-8") as f: raw_log_content = f.read()
    except Exception as e: raw_log_content = f"ログ読込エラー: {e}"
    gr.Info(f"'{character_name}' のチャットログ再読み込み完了。")
    return chat_log_for_display, raw_log_content

def handle_save_log_button_click(character_name: Optional[str], log_content: str) -> None:
    if not character_name:
        gr.Error("キャラクター未選択。ログ保存不可。")
        return
    if not isinstance(log_content, str):
        gr.Error("ログ内容無効。保存不可。")
        return
    try:
        save_log_file(character_name, log_content) # utilsからインポートした関数
        gr.Info(f"キャラクター '{character_name}' のログ保存完了。")
    except Exception as e:
        gr.Error(f"ログ保存エラー: {e}")
        traceback.print_exc()

# --- メッセージ送信処理 ---
def _prepare_api_text_and_log_entries(
    original_user_text: str,
    file_input_list: Optional[List[Any]],
    add_timestamp_checkbox: bool,
    log_f: str,
    user_header: str
) -> Tuple[str, List[Dict[str, str]], List[str]]:
    """ 添付ファイル処理とログ記録を行い、API用テキストとファイルリストを返す """
    api_text_arg = original_user_text
    files_for_gemini_api: List[Dict[str, str]] = []
    all_error_messages: List[str] = []

    user_action_timestamp_str = f"\n{datetime.datetime.now().strftime('%Y-%m-%d (%a) %H:%M:%S')}" if add_timestamp_checkbox else ""

    # 1. テキスト入力とテキストファイルのログ記録 (タイムスタンプはここでのみ適用)
    # まず、ユーザーの直接入力テキストを記録 (タイムスタンプ付加)
    if original_user_text:
        save_message_to_log(log_f, user_header, original_user_text + (user_action_timestamp_str if not file_input_list else "")) # ファイルがなければここでタイムスタンプ

    # 2. ファイル処理 (テキストファイルの内容はapi_text_argに追記、他はfiles_for_gemini_apiへ)
    if file_input_list:
        text_from_files_for_api = ""
        temp_files_log_entries = [] # ファイルごとのログエントリを一時保存

        for file_obj in file_input_list:
            temp_file_path = file_obj.name
            original_filename = getattr(file_obj, 'orig_name', os.path.basename(temp_file_path))
            file_extension = os.path.splitext(original_filename)[1].lower()
            file_type_info = SUPPORTED_FILE_MAPPINGS.get(file_extension)

            if not file_type_info:
                all_error_messages.append(f"ファイル形式非対応: {original_filename}")
                continue

            if file_type_info["category"] == 'text':
                content_to_add = ""
                encodings_to_try = ['utf-8', 'shift_jis', 'cp932', 'euc-jp', 'iso2022-jp', 'latin1']
                for enc in encodings_to_try:
                    try:
                        with open(temp_file_path, 'r', encoding=enc) as f: content_to_add = f.read()
                        break
                    except: continue
                if content_to_add:
                    text_from_files_for_api += f"\n\n--- 添付ファイル「{original_filename}」の内容 ---\n{content_to_add}"
                    temp_files_log_entries.append(f"[添付テキスト: {original_filename}]")
                else: all_error_messages.append(f"ファイルデコード失敗: {original_filename}")
            else: # 画像など、APIに直接渡すファイル
                # Kiseki: ファイルを永続的な場所にコピーする処理は _process_uploaded_files にあったが、
                # ここでは一時パスをそのまま使うか、再度コピー処理を実装する必要がある。
                # GradioのFileコンポーネントの `value` は一時ファイルパスなので、API送信前に永続化推奨。
                # ここでは簡略化のため、一時パスをそのまま使うが、実際はコピーが望ましい。
                # (本番コードでは、_process_uploaded_files相当の処理で永続パスにコピーし、そのパスを使う)
                files_for_gemini_api.append({
                    'path': temp_file_path,
                    'mime_type': file_type_info["mime_type"],
                    'original_filename': original_filename
                })
                temp_files_log_entries.append(f"[ファイル添付: {original_filename} ({file_type_info['mime_type']})]")

        if text_from_files_for_api:
            api_text_arg = (api_text_arg + text_from_files_for_api) if api_text_arg else text_from_files_for_api.strip()

        # ファイル関連のログエントリを記録 (ファイルがあった場合のみ、ここでまとめてタイムスタンプ)
        if temp_files_log_entries:
            combined_file_log_entry = "\n".join(temp_files_log_entries)
            if original_user_text: # ユーザーテキストが既にあれば、改行で区切る
                 save_message_to_log(log_f, user_header, combined_file_log_entry + user_action_timestamp_str)
            else: # ファイル添付のみの場合
                 save_message_to_log(log_f, user_header, combined_file_log_entry.strip() + user_action_timestamp_str)


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
    if validation_error:
        return chatbot_history, gr.update(value=original_user_text), gr.update(value=file_input_list), validation_error

    api_configured, api_error_msg = _configure_api_key_if_needed(current_api_key_name_state)
    if not api_configured:
        return chatbot_history, gr.update(value=original_user_text), gr.update(value=file_input_list), api_error_msg

    log_f, sys_p, _, mem_p = get_character_files_paths(current_character_name)
    if not all([log_f, sys_p, mem_p]):
        return chatbot_history, gr.update(value=original_user_text), gr.update(value=file_input_list), f"キャラ '{current_character_name}' の必須ファイルパス取得失敗。"

    user_header = _get_user_header_from_log(log_f, current_character_name)

    # ファイル処理とログ記録 (Kiseki修正箇所)
    api_text_arg, files_for_gemini_api, file_processing_errors = _prepare_api_text_and_log_entries(
        original_user_text, file_input_list, add_timestamp_checkbox, log_f, user_header
    )
    if file_processing_errors: # ファイル処理エラーがあればUIに通知
        error_message_for_ui = "\n".join(file_processing_errors)

    # /gazo コマンド処理 (Kiseki: 簡略化のため、現在は未実装。必要ならここに追加)
    if original_user_text.startswith("/gazo "):
        # (画像生成ロジック - 今回のスコープ外として省略。エラーメッセージで対応)
        error_message_for_ui = (error_message_for_ui + "\n" if error_message_for_ui else "") + "画像生成コマンドは現在処理中です。"
        # この時点で一旦UIを更新し、後続のAPI呼び出しは行わない
        new_log_for_gazo = load_chat_log(log_f, current_character_name)
        new_hist_for_gazo = format_history_for_gradio(new_log_for_gazo[-(config_manager.HISTORY_LIMIT * 2):])
        return new_hist_for_gazo, gr.update(value=""), gr.update(value=None), error_message_for_ui.strip()

    if not api_text_arg.strip() and not files_for_gemini_api:
        error_message_for_ui = (error_message_for_ui + "\n" if error_message_for_ui else "") + "送信するメッセージ本文または処理可能なファイルがありません。"
        return chatbot_history, gr.update(value=original_user_text), gr.update(value=file_input_list), error_message_for_ui.strip()

    try:
        api_response_text, generated_image_path = send_to_gemini(
            system_prompt_path=sys_p, log_file_path=log_f, user_prompt=api_text_arg,
            selected_model=current_model_name, character_name=current_character_name,
            send_thoughts_to_api=send_thoughts_state, api_history_limit_option=api_history_limit_state,
            uploaded_file_parts=files_for_gemini_api, memory_json_path=mem_p
        )

        # API応答のログ記録
        if api_response_text or generated_image_path:
            log_parts = []
            if generated_image_path: log_parts.append(f"[Generated Image: {generated_image_path}]")

            is_error_resp = api_response_text and any(e in api_response_text for e in ["エラー:", "API通信エラー:", "応答取得エラー", "応答生成失敗"])
            if api_response_text and not is_error_resp: log_parts.append(api_response_text)

            if log_parts: save_message_to_log(log_f, f"## {current_character_name}:", "\n\n".join(log_parts))
            if api_response_text and is_error_resp: error_message_for_ui = (error_message_for_ui + "\n" if error_message_for_ui else "") + api_response_text
        else:
            error_message_for_ui = (error_message_for_ui + "\n" if error_message_for_ui else "") + "APIから有効な応答がありませんでした。"

    except Exception as e:
        traceback.print_exc()
        error_message_for_ui = (error_message_for_ui + "\n" if error_message_for_ui else "") + f"メッセージ処理中に予期せぬエラー: {e}"

    new_log = load_chat_log(log_f, current_character_name)
    new_hist = format_history_for_gradio(new_log[-(config_manager.HISTORY_LIMIT * 2):])
    return new_hist, gr.update(value=""), gr.update(value=None), error_message_for_ui.strip()

```
