# ui_handlers.py (最終・完全・確定版)
import pandas as pd
from typing import List, Optional, Dict, Any, Tuple, Union # Keep existing typing imports
import gradio as gr
import datetime
import json
import traceback
import os
import mimetypes

# --- プロジェクト内モジュールのインポートを整理 ---
import config_manager # Needed for HISTORY_LIMIT, save_config, API_HISTORY_LIMIT_OPTIONS
import character_manager # Now directly used for log saving and char list
from utils import load_chat_log, format_history_for_gradio, save_message_to_log, _get_user_header_from_log
# alarm_manager, gemini_api, memory_manager, timers will be imported deferred

def handle_add_new_character(character_name: str):
    if not character_name or not character_name.strip():
        gr.Warning("キャラクター名が入力されていません。")
        char_list = character_manager.get_character_list()
        # Ensure all dropdowns are updated
        return gr.update(choices=char_list), gr.update(choices=char_list), gr.update(choices=char_list), gr.update(value="")


    # Basic sanitization, consider more robust validation if needed
    safe_name = "".join(c for c in character_name if c.isalnum() or c in (' ', '_', '-')).strip()
    if not safe_name:
        gr.Warning("無効なキャラクター名です。半角英数字、スペース、アンダースコア、ハイフンのみ使用可能です。")
        char_list = character_manager.get_character_list()
        return gr.update(choices=char_list), gr.update(choices=char_list), gr.update(choices=char_list), gr.update(value=character_name)


    if character_manager.ensure_character_files(safe_name):
        gr.Info(f"新しいキャラクター「{safe_name}」さんを迎えました！")
        new_char_list = character_manager.get_character_list()
        # Update all relevant dropdowns and clear the input textbox
        return gr.update(choices=new_char_list, value=safe_name), gr.update(choices=new_char_list, value=safe_name), gr.update(choices=new_char_list, value=safe_name), gr.update(value="")
    else:
        gr.Error(f"キャラクター「{safe_name}」の準備に失敗しました。")
        char_list = character_manager.get_character_list()
        # Keep current input in textbox for user to edit
        return gr.update(choices=char_list), gr.update(choices=char_list), gr.update(choices=char_list), gr.update(value=character_name)


def update_ui_on_character_change(character_name: Optional[str]):
    # Deferred import for memory_manager
    from memory_manager import load_memory_data_safe

    if not character_name: # Fallback if no character is selected (e.g., on initial load if list was empty)
        all_chars = character_manager.get_character_list()
        character_name = all_chars[0] if all_chars else "Default" # Should not be "Default" if list is truly empty

    config_manager.save_config("last_character", character_name)
    log_f, _, img_p, mem_p = character_manager.get_character_files_paths(character_name)

    chat_history = []
    if log_f and os.path.exists(log_f):
         # Ensure HISTORY_LIMIT is accessed via config_manager
        chat_history = format_history_for_gradio(load_chat_log(log_f, character_name)[-(config_manager.HISTORY_LIMIT * 2):])

    log_content = ""
    if log_f and os.path.exists(log_f):
        try:
            with open(log_f, "r", encoding="utf-8") as f: log_content = f.read()
        except Exception as e:
            print(f"Error reading log file {log_f}: {e}")
            log_content = f"Error reading log file: {e}"

    memory_str = "{}" # Default empty JSON string
    if mem_p and os.path.exists(mem_p):
        memory_data = load_memory_data_safe(mem_p) # Use safe load
        memory_str = json.dumps(memory_data, indent=2, ensure_ascii=False)

    # Ensure all outputs are correctly mapped in log2gemini.py
    return character_name, chat_history, "", img_p, memory_str, character_name, log_content, character_name


def handle_save_memory_click(character_name, json_string_data):
    # Deferred import for memory_manager
    from memory_manager import save_memory_data
    if not character_name:
        gr.Warning("キャラクターが選択されていません。")
        return
    save_memory_data(character_name, json_string_data) # Call the correct function

def handle_message_submission(*args: Any):
    # Deferred import for gemini_api
    from gemini_api import send_to_gemini

    (textbox_content, chatbot_history, current_character_name, current_model_name,
     current_api_key_name_state, file_input_list, add_timestamp_checkbox,
     send_thoughts_state, api_history_limit_state) = args

    if not all([current_character_name, current_model_name, current_api_key_name_state]):
        gr.Warning("キャラクター、モデル、APIキーをすべて選択してください。")
        return chatbot_history, gr.update(value=""), gr.update(value=None) # Ensure correct number of outputs

    log_f, sys_p, _, mem_p = character_manager.get_character_files_paths(current_character_name)
    if not log_f: # This implies sys_p, mem_p might also be None
        gr.Warning(f"キャラクター '{current_character_name}' の必須ファイルパス取得に失敗。")
        return chatbot_history, gr.update(value=""), gr.update(value=None)

    user_prompt = textbox_content.strip() if textbox_content else ""
    if not user_prompt and not file_input_list: # No text and no files
        return chatbot_history, gr.update(value=""), gr.update(value=None)

    log_message_content = user_prompt
    if file_input_list: # file_input_list is a list of file paths
        for file_path_obj in file_input_list: # Gradio might pass temp file objects
            actual_file_path = file_path_obj.name if hasattr(file_path_obj, 'name') else str(file_path_obj)
            log_message_content += f"\n[ファイル添付: {os.path.basename(actual_file_path)}]"


    user_header = _get_user_header_from_log(log_f, current_character_name) # from utils
    timestamp = f"\n{datetime.datetime.now():%Y-%m-%d (%a) %H:%M:%S}" if add_timestamp_checkbox else ""
    save_message_to_log(log_f, user_header, log_message_content.strip() + timestamp) # from utils

    uploaded_files_info = []
    if file_input_list:
        for file_path_obj in file_input_list:
            actual_file_path = file_path_obj.name if hasattr(file_path_obj, 'name') else str(file_path_obj)
            mime_type, _ = mimetypes.guess_type(actual_file_path)
            uploaded_files_info.append({"path": actual_file_path, "mime_type": mime_type or "application/octet-stream"})

    api_response_text = ""
    generated_image_path = None
    try:
        # Ensure mem_p is passed if send_to_gemini expects it
        api_response_text, generated_image_path = send_to_gemini(
            sys_p, log_f, user_prompt, current_model_name, current_character_name,
            send_thoughts_state, api_history_limit_state, uploaded_files_info, mem_p
        )

        if api_response_text or generated_image_path:
            response_to_log = (f"[Generated Image: {generated_image_path}]\n\n" if generated_image_path else "") + (api_response_text or "")
            save_message_to_log(log_f, f"## {current_character_name}:", response_to_log) # from utils
    except Exception as e:
        traceback.print_exc()
        gr.Error(f"メッセージ処理中に予期せぬエラー: {e}")

    # Reload log and format for display
    new_log = load_chat_log(log_f, current_character_name) # from utils
    # Ensure HISTORY_LIMIT is accessed via config_manager
    new_hist = format_history_for_gradio(new_log[-(config_manager.HISTORY_LIMIT * 2):])
    return new_hist, gr.update(value=""), gr.update(value=None) # Clear textbox, clear file upload

    # ui_handlers.py
    # (Ensure pandas as pd and alarm_manager are imported, likely deferred for alarm_manager)
    import pandas as pd # Keep at top if already there

    def render_alarms_as_dataframe():
        """アラームリストからDataFrameを生成する。ID列を含む。"""
        import alarm_manager # Deferred import
        all_alarms = alarm_manager.get_all_alarms()
        df_data = []
        DAY_MAP_EN_TO_JA = getattr(alarm_manager, 'DAY_MAP_EN_TO_JA', {}) # Safely get map
        for alarm in all_alarms: # Iterate through each alarm dictionary
            # ★★★ 表示崩れを防ぐため、区切り文字を「、」に変更 ★★★
            days_ja_str = "、".join([DAY_MAP_EN_TO_JA.get(d, "?") for d in alarm.get("days", [])])
            df_data.append({
                "id": alarm.get("id"), "状態": alarm.get("enabled", False),
                "時刻": alarm.get("time", ""), "曜日": days_ja_str,
                "キャラ": alarm.get("character", ""), "テーマ": alarm.get("theme", "")
            })
        df = pd.DataFrame(df_data) # Create DataFrame from list of dicts
        if not df.empty:
            df = df.sort_values(by=["時刻", "曜日"]).reset_index(drop=True)
            return df
        # DataFrameが空の場合でも、正しい列構成で返す
        return pd.DataFrame(columns=["id", "状態", "時刻", "曜日", "キャラ", "テーマ"])


def get_display_df(df_with_ids: pd.DataFrame): # This is a utility for the UI, keep as is
    if df_with_ids.empty or "id" not in df_with_ids.columns:
        return pd.DataFrame(columns=["状態", "時刻", "曜日", "キャラ", "テーマ"]) # Ensure consistent columns
    return df_with_ids[["状態", "時刻", "曜日", "キャラ", "テーマ"]]


def handle_alarm_selection_and_feedback(df_with_ids: pd.DataFrame, evt: gr.SelectData):
    """Dataframeでの行選択を処理し、選択されたIDとフィードバックメッセージを返す。単一選択・複数選択の両方に対応した堅牢な実装。"""
    if evt.index is None:
        return [], "アラームを選択してください"

    indices_list = evt.index if isinstance(evt.index, list) else [evt.index]

    if not indices_list:
        return [], "アラームを選択してください"
    try:
        # Ensure indices are valid before trying to access them
        selected_row_indices = sorted(list(set(idx[0] for idx in indices_list if idx and len(idx) > 0)))

        valid_indices = [i for i in selected_row_indices if i < len(df_with_ids)]
        if not valid_indices: return [], "選択した行が見つかりません。"

        selected_ids = df_with_ids.iloc[valid_indices]["id"].tolist()

        if len(selected_ids) == 1:
            selected_alarm_row = df_with_ids.iloc[valid_indices[0]]
            return selected_ids, f"選択中: 「{selected_alarm_row['テーマ']}」 ({selected_alarm_row['時刻']})"
        else:
            return selected_ids, f"{len(selected_ids)}件のアラームを選択中"
    except (TypeError, IndexError, KeyError) as e: # Catch potential errors during iloc or dict access
        traceback.print_exc()
        return [], "選択情報の取得に失敗しました。"


def load_alarm_to_form(selected_ids: list): # Keep list for type hint for now
    # Deferred import for alarm_manager
    import alarm_manager
    DAY_MAP_JA_TO_EN = getattr(alarm_manager, 'DAY_MAP_JA_TO_EN', {})
    DAY_MAP_EN_TO_JA = getattr(alarm_manager, 'DAY_MAP_EN_TO_JA', {})

    if not selected_ids or len(selected_ids) != 1:
        char_list = character_manager.get_character_list()
        default_char = char_list[0] if char_list else None
        # Ensure DAY_MAP_JA_TO_EN.keys() is used, not .values() if it's JA to EN
        return "アラーム追加", "", "", default_char, list(DAY_MAP_JA_TO_EN.keys()), "08", "00", None

    alarm_id = selected_ids[0]
    alarm_data = alarm_manager.get_alarm_by_id(alarm_id)

    if not alarm_data:
        gr.Warning(f"ID '{alarm_id}'のアラームが見つかりません。")
        char_list = character_manager.get_character_list() # Provide char_list for consistency
        default_char = char_list[0] if char_list else None
        return "アラーム追加", "", "", default_char, list(DAY_MAP_JA_TO_EN.keys()), "08", "00", None

    hour, minute = alarm_data.get("time", "08:00").split(":")
    days_ja = [DAY_MAP_EN_TO_JA.get(day_en, "?") for day_en in alarm_data.get("days", [])]

    return ("アラーム更新", alarm_data.get("theme", ""), alarm_data.get("flash_prompt_template", ""),
            alarm_data.get("character", ""), days_ja, hour, minute, alarm_id)


def toggle_selected_alarms_status(selected_ids: list, new_status: bool):
    # Deferred import for alarm_manager
    import alarm_manager
    if not selected_ids:
        gr.Warning("操作するアラームが選択されていません。")
        # Return the current state of the dataframe, not re-render if no selection
        # This requires the dataframe to be an input to this function or handled differently
        return render_alarms_as_dataframe() # Re-render for now

    for alarm_id in selected_ids:
        alarm_manager.update_alarm(alarm_id, {"enabled": new_status})

    status_text = "有効化" if new_status else "無効化"
    gr.Info(f"{len(selected_ids)}件のアラームを{status_text}しました。")
    return render_alarms_as_dataframe()


def handle_delete_selected_alarms(selected_ids: list):
    # Deferred import for alarm_manager
    import alarm_manager
    if not selected_ids:
        gr.Warning("削除するアラームが選択されていません。")
        return render_alarms_as_dataframe() # Re-render for now

    count = 0
    for alarm_id in selected_ids:
        if alarm_manager.delete_alarm(alarm_id):
            count += 1

    gr.Info(f"{count}件のアラームを削除しました。")
    return render_alarms_as_dataframe()


def handle_add_or_update_alarm(editing_alarm_id, hour, minute, character, theme, flash_prompt, days_ja):
    # Deferred import for alarm_manager
    import alarm_manager
    DAY_MAP_JA_TO_EN = getattr(alarm_manager, 'DAY_MAP_JA_TO_EN', {})

    if not character:
        gr.Warning("キャラクターを選択してください。")
        return render_alarms_as_dataframe(), render_alarms_as_dataframe(), "アラーム追加", theme, flash_prompt, character, days_ja, hour, minute, editing_alarm_id

    if not theme or not theme.strip():
        gr.Warning("テーマを入力してください。")
        return render_alarms_as_dataframe(), render_alarms_as_dataframe(), "アラーム追加", theme, flash_prompt, character, days_ja, hour, minute, editing_alarm_id

    days_en = [DAY_MAP_JA_TO_EN.get(day_ja, day_ja.lower()[:3]) for day_ja in days_ja] # Fallback for safety

    if editing_alarm_id:
        update_data = {
            "time": f"{hour}:{minute}", "character": character, "theme": theme.strip(),
            "flash_prompt_template": flash_prompt.strip() if flash_prompt else None, "days": days_en,
        }
        alarm_manager.update_alarm(editing_alarm_id, update_data)
        gr.Info(f"アラーム「{theme}」を更新しました。")
    else:
        alarm_manager.add_alarm(hour, minute, character, theme.strip(), flash_prompt.strip() if flash_prompt else None, days_ja) # Pass days_ja
        gr.Info(f"アラーム「{theme}」を追加しました。")

    new_df = render_alarms_as_dataframe()
    all_chars = character_manager.get_character_list()
    default_char = all_chars[0] if all_chars else None

    return (new_df, new_df, "アラーム追加", "", "", default_char,
            list(DAY_MAP_JA_TO_EN.keys()), "08", "00", None)

def update_model_state(new_model_name: str): # Add type hint
    config_manager.save_config("last_model", new_model_name)
    return new_model_name # Return the name to update state if Gradio component expects it

def update_api_key_state(new_api_key_name: str): # Add type hint
    # Deferred import for gemini_api
    from gemini_api import configure_google_api
    if new_api_key_name in config_manager.API_KEYS:
        configure_google_api(new_api_key_name)
        config_manager.save_config("last_api_key_name", new_api_key_name)
    else:
        gr.Warning(f"無効なAPIキー名です: {new_api_key_name}") # More informative
    return new_api_key_name # Return the name

def update_timestamp_state(add_timestamp_enabled: bool): # Add type hint
    config_manager.save_config("add_timestamp", add_timestamp_enabled)
    # No return needed if this just updates config and doesn't directly set a gr.State

def update_send_thoughts_state(send_thoughts_enabled: bool): # Add type hint
    config_manager.save_config("last_send_thoughts_to_api", send_thoughts_enabled)
    return send_thoughts_enabled # Return the state

def update_api_history_limit_state(limit_option_display_value: str): # Add type hint
    # Convert display value back to key if necessary, assuming API_HISTORY_LIMIT_OPTIONS is available
    limit_option_key = next((k for k, v in config_manager.API_HISTORY_LIMIT_OPTIONS.items() if v == limit_option_display_value), "all")
    config_manager.save_config("last_api_history_limit_option", limit_option_key)
    return limit_option_key # Return the key


def handle_save_log_button_click(character_name: str, log_content: str):
    """ログエディタの内容を保存する。character_manager.save_log_fileを正しく呼び出す。"""
    if not character_name:
        gr.Warning("キャラクターが選択されていません。")
        return

    try:
        # No longer need function-scoped import from utils
        character_manager.save_log_file(character_name, log_content)
        gr.Info(f"{character_name}さんのログを保存しました。")
    except Exception as e:
        gr.Error(f"ログの保存中にエラーが発生しました: {e}")
        traceback.print_exc() # Ensure traceback is imported


def reload_chat_log(character_name: str):
    if not character_name: return [], "" # Return empty list for history and empty string for log content

    log_f, _, _, _ = character_manager.get_character_files_paths(character_name)

    chat_history_display = []
    log_file_content = ""

    if log_f and os.path.exists(log_f):
        try:
            # Ensure HISTORY_LIMIT is accessed via config_manager
            chat_history_display = format_history_for_gradio(load_chat_log(log_f, character_name)[-(config_manager.HISTORY_LIMIT*2):])
            with open(log_f, 'r', encoding='utf-8') as f:
                log_file_content = f.read()
        except Exception as e:
            print(f"Error processing log file for reload {log_f}: {e}")
            log_file_content = f"Error loading log: {e}"

    return chat_history_display, log_file_content


def handle_timer_submission(timer_type, duration_minutes, pomo_work_minutes, pomo_break_minutes, pomo_cycles,
                            character_name, work_theme, break_theme, api_key_name, webhook_url,
                            normal_timer_theme):
    # Deferred import for timers
    from timers import UnifiedTimer

    if not character_name or not api_key_name:
        # gr.Info("キャラクターとAPIキーを選択してください。") # This does not show error, use Warning
        gr.Warning("キャラクターとAPIキーを選択してください。")
        return "キャラクターとAPIキーを選択してください。"

    timer = UnifiedTimer.get_instance()
    if timer.is_running(): # Stop any existing timer first
        timer.stop()
        print("既存のタイマーを停止しました。")

    timer.set_properties(character_name, api_key_name, webhook_url) # Use actual webhook_url from config or UI

    message = ""
    if timer_type == "通常タイマー":
        if not (duration_minutes and duration_minutes > 0):
            gr.Warning("通常タイマーの時間を正しく設定してください。")
            return "タイマー時間を正しく設定してください。"
        actual_theme = normal_timer_theme or "タイマー終了！"
        timer.set_normal_timer(duration_minutes * 60, actual_theme)
        message = f"{character_name}さんによる「{actual_theme}」タイマーを{duration_minutes}分でセットしました。"
    elif timer_type == "ポモドーロタイマー":
        if not (pomo_work_minutes and pomo_work_minutes > 0 and \
                pomo_break_minutes and pomo_break_minutes > 0 and \
                pomo_cycles and pomo_cycles > 0):
            gr.Warning("ポモドーロタイマーの各時間を正しく設定してください。")
            return "ポモドーロの各時間を正しく設定してください。"

        actual_work_theme = work_theme or "作業終了！"
        actual_break_theme = break_theme or "休憩終了！"
        timer.set_pomodoro(pomo_work_minutes * 60, pomo_break_minutes * 60, pomo_cycles,
                           actual_work_theme, actual_break_theme)
        message = f"{character_name}さんによるポモドーロタイマーをセット (作業{pomo_work_minutes}分, 休憩{pomo_break_minutes}分, {pomo_cycles}サイクル)。"
    else:
        gr.Warning("無効なタイマータイプです。")
        return "無効なタイマータイプです。"

    timer.start()
    gr.Info(message) # Show success message to user via Gradio
    return message # Return message to update UI status component


def stop_existing_timer_on_startup(): # This function is called by log2gemini.py via demo.load
    # Deferred import for timers
    from timers import UnifiedTimer
    timer = UnifiedTimer.get_instance()
    if timer.is_running():
        timer.stop()
        print("アプリケーション起動時、既存のタイマーを停止しました。 (ui_handlers.stop_existing_timer_on_startup)")
