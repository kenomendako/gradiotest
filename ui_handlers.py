# -*- coding: utf-8 -*-
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
# --- モジュールインポート ---
import config_manager
import alarm_manager
from timers import UnifiedTimer
from character_manager import get_character_files_paths
from gemini_api import configure_google_api, send_to_gemini, generate_image_with_gemini
from memory_manager import load_memory_data_safe, save_memory_data # Added save_memory_data based on its use in Kiseki's log2gemini
from utils import load_chat_log, format_history_for_gradio, save_message_to_log, _get_user_header_from_log, save_log_file

# --- Dataframe表示用データ整形関数 ---
DAY_MAP_EN_TO_JA = {"mon": "月", "tue": "火", "wed": "水", "thu": "木", "fri": "金", "sat": "土", "sun": "日"}

def render_alarms_as_dataframe():
    """アラームデータを取得し、GradioのDataframe表示用にpandas.DataFrameを生成して返す。"""
    alarms = alarm_manager.get_all_alarms()
    display_data = []
    for alarm in sorted(alarms, key=lambda x: x.get("time", "")):
        days_ja = [DAY_MAP_EN_TO_JA.get(d, d.upper()) for d in alarm.get('days', [])]
        display_data.append({
            "ID": alarm.get("id"),
            "状態": alarm.get("enabled", False),
            "時刻": alarm.get("time"),
            "曜日": ",".join(days_ja),
            "キャラ": alarm.get("character"),
            "テーマ": alarm.get("theme")
        })
    df = pd.DataFrame(display_data, columns=["ID", "状態", "時刻", "曜日", "キャラ", "テーマ"])
    return df

def get_display_df(df_with_id: pd.DataFrame):
    """ID列を非表示にした表示用のDataFrameを返す"""
    if df_with_id is None or df_with_id.empty:
        return pd.DataFrame(columns=["状態", "時刻", "曜日", "キャラ", "テーマ"])
    if 'ID' in df_with_id.columns:
        return df_with_id.drop(columns=['ID'])
    return df_with_id # IDがなければそのまま返す

# --- アラームDataframeイベントハンドラ ---
def handle_alarm_dataframe_change(df_after_change: pd.DataFrame, df_original: pd.DataFrame):
    # Both df_after_change and df_original are expected to be ID-ful DataFrames
    # as per log2gemini.py Ver.3: inputs=[alarm_dataframe_original_data, alarm_dataframe_original_data]
    # However, the standard Gradio df.change() event passes the *current component value* as the first arg.
    # If alarm_dataframe (display) triggers this, df_after_change will be ID-less.
    # Kiseki's log2gemini.py Ver.3 for alarm_dataframe.change is:
    # inputs=[alarm_dataframe, alarm_dataframe_original_data], outputs=[alarm_dataframe_original_data]
    # This means df_after_change is the display DF (ID-less) and df_original is the ID-ful state.
    # The handler must reconcile this. The ui_handlers.py from Kiseki Ver.3:
    # merged = pd.merge(df_after_change, df_original, on="ID", ...) -> This expects 'ID' in df_after_change.
    # This is a slight internal contradiction in Kiseki's Ver.3 spec between log2gemini and ui_handlers for this handler.
    #
    # Safest interpretation: df_original *is* the ID-ful state *before* the UI change.
    # df_after_change *is* the new state of the UI component (ID-less).
    # We need to map rows from df_after_change to df_original to find IDs and compare '状態'.

    if df_after_change is None or df_original is None: # df_original is ID-ful
        return df_original # No change, return original ID-ful state

    # Create a temporary key for matching display rows to original ID-ful rows
    # This key should be based on uniquely identifiable fields present in the display DF

    # Add a temporary index to df_after_change to reconstruct it later if needed
    df_after_change_indexed = df_after_change.reset_index()

    # Merge with original ID-ful data to get IDs for the rows in df_after_change
    # We assume other display columns are sufficient to uniquely identify the row.
    merge_keys = ["時刻", "曜日", "キャラ", "テーマ"] # Columns present in display DF

    # Ensure df_original has these keys. It's ID-ful, so it should.
    # Ensure df_after_change (display) has these keys.
    missing_keys_display = [key for key in merge_keys if key not in df_after_change.columns]
    missing_keys_original = [key for key in merge_keys if key not in df_original.columns]

    if missing_keys_display or missing_keys_original:
        gr.Error("内部エラー: アラーム状態比較に必要な列が不足しています。")
        print(f"Error: Missing keys for merge. Display missing: {missing_keys_display}, Original missing: {missing_keys_original}")
        return df_original # Return original ID-ful state

    # Perform the merge to align rows and get IDs for UI changes
    # `df_after_change` has the new '状態' from UI, `df_original` has old '状態' and 'ID'
    # We want to find rows in `df_original` that match `df_after_change` on merge_keys, then compare '状態'

    # Create 'temp_merge_key' for both dataframes
    df_after_change['temp_merge_key'] = df_after_change.apply(lambda r: "_".join(str(r[k]) for k in merge_keys), axis=1)
    df_original['temp_merge_key'] = df_original.apply(lambda r: "_".join(str(r[k]) for k in merge_keys), axis=1)

    changed_count = 0
    for _, ui_row in df_after_change.iterrows():
        original_row_match = df_original[df_original['temp_merge_key'] == ui_row['temp_merge_key']]
        if not original_row_match.empty:
            original_alarm = original_row_match.iloc[0]
            original_id = original_alarm['ID']
            original_state = original_alarm['状態']
            ui_state = ui_row['状態']

            if ui_state != original_state:
                try:
                    alarm_manager.toggle_alarm_enabled(original_id)
                    gr.Info(f"アラーム「{ui_row['テーマ']}」の状態を更新しました。 (ID: {original_id})")
                    changed_count +=1
                except Exception as e_toggle:
                    gr.Error(f"アラーム「{ui_row['テーマ']}」の状態更新エラー: {e_toggle}")
                    print(f"Error toggling alarm: {e_toggle}")

    # Clean up temp columns
    if 'temp_merge_key' in df_after_change.columns: df_after_change.drop(columns=['temp_merge_key'], inplace=True)
    if 'temp_merge_key' in df_original.columns: df_original.drop(columns=['temp_merge_key'], inplace=True)


    if changed_count == 0 and not df_after_change.equals(get_display_df(df_original)): # Check if only non-state columns changed
         pass # No actual state toggle, but other cell might have been edited if interactive

    return render_alarms_as_dataframe() # Return fresh ID-ful DataFrame

def handle_alarm_selection(evt: gr.SelectData, df_with_id: pd.DataFrame):
    # df_with_id is alarm_dataframe_original_data (ID-ful)
    if evt.indices is None or df_with_id is None or df_with_id.empty: return []
    selected_ids = []
    selected_row_indices = sorted(list(set([index[0] for index in evt.indices]))) # Unique row indices from UI selection
    for row_index in selected_row_indices:
        if 0 <= row_index < len(df_with_id): # Check bounds against the ID-ful dataframe
            selected_ids.append(str(df_with_id.iloc[row_index]['ID']))
    return selected_ids

def handle_delete_selected_alarms(selected_ids: list):
    if not selected_ids:
        gr.Warning("削除するアラームが選択されていません。")
    else:
        deleted_count = 0
        for alarm_id_str in selected_ids:
            if alarm_manager.delete_alarm(str(alarm_id_str)):
                deleted_count +=1
        if deleted_count > 0: gr.Info(f"{deleted_count}件のアラームを削除しました。")
        else: gr.Warning("選択されたアラームを削除できませんでした。")
    return render_alarms_as_dataframe() # Return fresh ID-ful DataFrame

# --- タイマーイベントハンドラ ---
def handle_timer_submission(timer_type, duration, work_duration, break_duration, cycles, character_name, work_theme, break_theme, api_key_name, webhook_url, normal_timer_theme):
    if not character_name or not api_key_name:
        gr.Error("キャラクターとAPIキーを選択してください。"); return "設定エラー"
    try:
        status_message = "" # Ensure status_message is initialized
        if timer_type == "通常タイマー":
            if not (duration and float(duration) > 0):
                gr.Error("通常タイマーの時間を正しく入力してください。"); return "設定エラー"
            status_message = f"{duration}分の通常タイマーを開始しました。"
        elif timer_type == "ポモドーロタイマー": # Explicitly check for Pomodoro
            if not (work_duration and float(work_duration) > 0 and
                    break_duration and float(break_duration) > 0 and
                    cycles and int(cycles) > 0):
                gr.Error("ポモドーロの各項目を正しく入力してください。"); return "設定エラー"
            status_message = f"{work_duration}分作業/{break_duration}分休憩のポモドーロタイマーを開始。"
        else: # Should not happen if Radio items are fixed
            gr.Error("不明なタイマータイプです。"); return "設定エラー"


        unified_timer = UnifiedTimer(timer_type, float(duration or 0), float(work_duration or 0), float(break_duration or 0), int(cycles or 0), character_name, work_theme, break_theme, api_key_name, webhook_url, normal_timer_theme)
        unified_timer.start()
        gr.Info(f"{timer_type}を開始しました。"); return status_message
    except ValueError as ve:
        error_msg = f"タイマー設定値エラー: {ve}"; gr.Error(error_msg); traceback.print_exc(); return error_msg
    except Exception as e:
        error_msg = f"タイマー開始エラー: {e}"; gr.Error(error_msg); traceback.print_exc(); return error_msg

# --- UI状態更新ハンドラ (完全版, Kiseki Ver.3) ---
def update_ui_on_character_change(character_name: Optional[str]):
    if not character_name:
        # Return empty/default values for all outputs of character_dropdown.change in log2gemini.py
        # outputs=[current_character_name, chatbot_display, chat_input_textbox, profile_image_display, memory_json_editor, alarm_char_dropdown, timer_char_dropdown, log_editor]
        return None, [], "", None, "{}", None, None, "キャラ未選択"

    config_manager.save_config("last_character", character_name) # Save the change

    log_f, _, img_p, mem_p = get_character_files_paths(character_name)

    # Use HISTORY_LIMIT from config_manager global if available, else default
    history_limit = getattr(config_manager, 'HISTORY_LIMIT', 100)

    chat_history = format_history_for_gradio(load_chat_log(log_f, character_name)[-history_limit * 2:]) if log_f and os.path.exists(log_f) else []

    log_content = ""
    if log_f and os.path.exists(log_f):
        try:
            with open(log_f, "r", encoding="utf-8") as f: log_content = f.read()
        except Exception as e_log:
            log_content = f"ログファイル読込エラー: {e_log}"

    memory_str = json.dumps(load_memory_data_safe(mem_p), indent=2, ensure_ascii=False)
    profile_image = img_p if img_p and os.path.exists(img_p) else None

    # Match the outputs in log2gemini.py for character_dropdown.change
    # current_character_name (state), chatbot_display, chat_input_textbox, profile_image_display,
    # memory_json_editor, alarm_char_dropdown, timer_char_dropdown, log_editor
    return character_name, chat_history, "", profile_image, memory_str, character_name, character_name, log_content

def update_model_state(model):
    config_manager.save_config("last_model", model)
    return model

def update_api_key_state(api_key_name):
    ok, msg = configure_google_api(api_key_name)
    config_manager.save_config("last_api_key_name", api_key_name)
    if ok: gr.Info(f"APIキー '{api_key_name}' 設定成功。")
    else: gr.Error(f"APIキー '{api_key_name}' 設定失敗: {msg}")
    return api_key_name

def update_timestamp_state(checked):
    config_manager.save_config("add_timestamp", bool(checked))
    # No return needed as it's not updating a gr.State directly in log2gemini for this one

def update_send_thoughts_state(checked):
    config_manager.save_config("last_send_thoughts_to_api", bool(checked))
    return bool(checked) # Return value for the gr.State

def update_api_history_limit_state(limit_ui_val):
    # Ensure API_HISTORY_LIMIT_OPTIONS is available in config_manager, not a hardcoded dict
    api_history_options = getattr(config_manager, 'API_HISTORY_LIMIT_OPTIONS',
                                  {"none": "履歴なし", "summary": "短期記憶(要約)", "short": "短期記憶(最新5件)", "long": "長期記憶(最新10件)", "all": "全履歴"}) # Fallback
    key = next((k for k, v in api_history_options.items() if v == limit_ui_val), "all")
    config_manager.save_config("last_api_history_limit_option", key)
    return key # Return value for the gr.State

def reload_chat_log(character_name):
    if not character_name: return [], "キャラクター未選択"
    log_f,_,_,_ = get_character_files_paths(character_name)
    if not log_f or not os.path.exists(log_f): return [], "ログファイルなし"
    history_limit = getattr(config_manager, 'HISTORY_LIMIT', 100)
    history = format_history_for_gradio(load_chat_log(log_f, character_name)[-history_limit * 2:])
    content = ""
    try:
        with open(log_f, "r", encoding="utf-8") as f: content = f.read()
    except Exception as e: content = f"ログファイル読込エラー: {e}"
    gr.Info(f"'{character_name}'のログを再読み込みしました。"); return history, content

def handle_save_log_button_click(character_name, log_content):
    if not character_name: gr.Error("キャラクターが選択されていません。"); return
    try:
        save_log_file(character_name, log_content);
        gr.Info(f"'{character_name}'のログを保存しました。")
    except Exception as e:
        gr.Error(f"ログ保存エラー: {e}"); traceback.print_exc()

# --- メッセージ送信処理 (Kiseki Ver.3 - "内容は変更なし" but using previous more complete stub) ---
def handle_message_submission(
    textbox_content: Optional[str],
    chatbot_history: List[Tuple[Optional[str], Optional[str]]],
    character_name: Optional[str],
    model_name: Optional[str],
    api_key_name: Optional[str],
    file_list: Optional[List[str]], # List of file paths
    add_timestamp: bool,
    send_thoughts: bool,
    history_limit_key: str # This is the key like "all", "short"
):
    if not character_name or not model_name or not api_key_name:
        gr.Error("キャラクター、モデル、またはAPIキーが選択されていません。")
        # To match expected outputs: chatbot_display, chat_input_textbox, file_upload_button, timer_status_display
        return chatbot_history, textbox_content or "", file_list, "設定エラー"

    api_ok, msg = configure_google_api(api_key_name) # Ensure API key is configured
    if not api_ok:
        gr.Error(f"APIキー設定エラー: {msg}")
        return chatbot_history, textbox_content or "", file_list, f"APIキーエラー: {msg}"

    log_f, sys_p, _, mem_p = get_character_files_paths(character_name)
    if not all([log_f, sys_p, mem_p]):
         gr.Error(f"キャラ '{character_name}' の必須ファイルパス取得失敗。")
         return chatbot_history, textbox_content or "", file_list, "ファイルパスエラー"

    user_header = _get_user_header_from_log(log_f, character_name)

    current_text_input = textbox_content.strip() if textbox_content else ""
    api_text_for_gemini = current_text_input

    # Basic file processing placeholder - actual implementation from earlier versions would be more complex
    processed_file_parts_for_api = []
    file_log_entries = []
    if file_list:
        for file_path in file_list:
            try:
                # In a real scenario, utils.safe_upload_file or similar would be used
                # For now, just log and potentially add filename to prompt
                original_filename = os.path.basename(file_path)
                # This part needs to be robust: determine mime type, prepare for API
                # For placeholder:
                # processed_file_parts_for_api.append({'path': file_path, 'mime_type': 'application/octet-stream'}) # Example
                file_log_entries.append(f"[添付ファイル: {original_filename}]")
            except Exception as e_file:
                gr.Warning(f"ファイル処理エラー ({original_filename}): {e_file}")
        if file_log_entries:
             api_text_for_gemini += "\n" + "\n".join(file_log_entries)


    timestamp_log_entry = datetime.datetime.now().strftime(" (%Y-%m-%d %H:%M:%S)") if add_timestamp else ""

    if current_text_input or file_log_entries: # Log if there was text or files
        log_entry_for_user = current_text_input
        if file_log_entries:
            log_entry_for_user += ("\n" if current_text_input else "") + "\n".join(file_log_entries)
        save_message_to_log(log_f, user_header, log_entry_for_user + timestamp_log_entry)

    if not api_text_for_gemini.strip(): # Check if there's anything to send to Gemini
        gr.Warning("送信する有効なコンテンツがありません。")
        return chatbot_history, "", None, "入力なし" # Clear textbox, clear files

    try:
        # This is where the actual call to gemini_api.send_to_gemini would be.
        # Using a more complete placeholder based on Kiseki's Ver.1 ui_handlers.py structure:

        # response_text, generated_image_path = gemini_api.send_to_gemini(
        #     system_prompt_path=sys_p,
        #     log_file_path=log_f,
        #     user_prompt=api_text_for_gemini,
        #     selected_model=model_name,
        #     character_name=character_name,
        #     send_thoughts_to_api=send_thoughts,
        #     api_history_limit_option=history_limit_key,
        #     uploaded_file_parts=processed_file_parts_for_api,
        #     memory_json_path=mem_p
        # )
        # Placeholder:
        response_text = f"AI ({character_name}): 「{current_text_input}」について返信 (ファイル処理は省略されました)。"
        generated_image_path = None


        if response_text:
            save_message_to_log(log_f, f"## {character_name}:", response_text + timestamp_log_entry)

        # Update chatbot history
        new_history_entry = [current_text_input if current_text_input else None, response_text]
        if generated_image_path: # If an image was generated by API
            new_history_entry_img = [None, (generated_image_path,)]
            chatbot_history.append(new_history_entry_img) # Add image to chat

        chatbot_history.append(new_history_entry)

        # timer_status_display output is for general status, not just errors.
        return chatbot_history, "", None, "メッセージ送信成功" # Clear input, clear files, success message

    except Exception as e_send:
        print(f"メッセージ送信処理中にエラー: {e_send}\n{traceback.format_exc()}")
        error_detail = f"送信エラー: {e_send}"
        gr.Error(error_detail)
        return chatbot_history, current_text_input, file_list, error_detail # Keep inputs, show error
