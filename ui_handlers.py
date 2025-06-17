# ui_handlers.py (最終・完全・確定版)
import pandas as pd
from typing import List, Optional, Dict, Any, Tuple, Union
import gradio as gr
import datetime
import json
import traceback
import os
import mimetypes

# --- プロジェクト内モジュールのインポート ---
import config_manager
import character_manager
# utils functions are used directly, ensure they are correctly defined in utils.py
from utils import load_chat_log, format_history_for_gradio, save_message_to_log, _get_user_header_from_log
# alarm_manager, gemini_api, memory_manager, timers will be imported deferred

# --- アラーム関連の表示ヘルパー関数をここに再定義 ---
DAY_MAP_EN_TO_JA = {"mon": "月", "tue": "火", "wed": "水", "thu": "木", "fri": "金", "sat": "土", "sun": "日"}
DAY_MAP_JA_TO_EN = {v: k for k, v in DAY_MAP_EN_TO_JA.items()}

def render_alarms_as_dataframe():
    import alarm_manager # 遅延インポート
    all_alarms = alarm_manager.get_all_alarms()
    df_data = []
    # Assuming DAY_MAP_EN_TO_JA is defined in this module (it was in user's last full ui_handlers.py)
    for alarm in all_alarms:
        # ★★★ 表示崩れを防ぐため、曜日を一行で表示するよう修正 ★★★
        # Sort by a predefined order "月火水木金土日" then join into a single string
        days_str = "".join(sorted([DAY_MAP_EN_TO_JA.get(d, '') for d in alarm.get("days", [])], key="月火水木金土日".find))
        df_data.append({
            "id": alarm.get("id"), "状態": alarm.get("enabled", False),
            "時刻": alarm.get("time", ""), "曜日": days_str, # Use the new days_str
            "キャラ": alarm.get("character", ""), "テーマ": alarm.get("theme", "")
        })
    df = pd.DataFrame(df_data)
    if not df.empty:
        # Sort by time only, as per user's latest instruction for this function
        df = df.sort_values(by=["時刻"]).reset_index(drop=True)
        return df
    return pd.DataFrame(columns=["id", "状態", "時刻", "曜日", "キャラ", "テーマ"])

def get_display_df(df_with_ids: pd.DataFrame) -> pd.DataFrame:
    if df_with_ids.empty or "id" not in df_with_ids.columns:
        return pd.DataFrame(columns=["状態", "時刻", "曜日", "キャラ", "テーマ"])
    return df_with_ids[["状態", "時刻", "曜日", "キャラ", "テーマ"]]

# --- (以降、既存のハンドラを修正) ---

def handle_add_new_character(character_name: str):
    if not character_name or not character_name.strip():
        gr.Warning("キャラクター名が入力されていません。")
        char_list = character_manager.get_character_list()
        # Ensure all dropdowns are updated
        return gr.update(choices=char_list), gr.update(choices=char_list), gr.update(choices=char_list), gr.update(value="") # Clear textbox

    safe_name = "".join(c for c in character_name if c.isalnum() or c in (' ', '_', '-')).strip()
    if not safe_name:
        gr.Warning("無効なキャラクター名です。")
        char_list = character_manager.get_character_list()
        # Keep original name in textbox for user to edit
        return gr.update(choices=char_list), gr.update(choices=char_list), gr.update(choices=char_list), gr.update(value=character_name)

    if character_manager.ensure_character_files(safe_name):
        gr.Info(f"新しいキャラクター「{safe_name}」さんを迎えました！")
        new_char_list = character_manager.get_character_list()
        return gr.update(choices=new_char_list, value=safe_name), gr.update(choices=new_char_list, value=safe_name), gr.update(choices=new_char_list, value=safe_name), gr.update(value="")
    else:
        gr.Error(f"キャラクター「{safe_name}」の準備に失敗しました。")
        char_list = character_manager.get_character_list()
        return gr.update(choices=char_list), gr.update(choices=char_list), gr.update(choices=char_list), gr.update(value=character_name)

def update_ui_on_character_change(character_name: Optional[str]):
    from memory_manager import load_memory_data_safe # 遅延インポート

    if not character_name: # Should ideally not happen if dropdown has a value
        all_chars = character_manager.get_character_list()
        # Fallback to first character if list is not empty, else "Default" (which should be created)
        character_name = all_chars[0] if all_chars else "Default"
        if not all_chars and character_name == "Default": # If Default had to be created
             character_manager.ensure_character_files("Default")


    config_manager.save_config("last_character", character_name)
    log_f, _, img_p, mem_p = character_manager.get_character_files_paths(character_name)

    chat_history = []
    if log_f and os.path.exists(log_f):
        chat_history = format_history_for_gradio(load_chat_log(log_f, character_name)[-(config_manager.HISTORY_LIMIT*2):])

    log_content = ""
    if log_f and os.path.exists(log_f):
        with open(log_f, "r", encoding="utf-8") as f: log_content = f.read()

    memory_str = "{}" # Default empty JSON string
    if mem_p and os.path.exists(mem_p): # Check if memory path and file exist
        memory_data = load_memory_data_safe(mem_p)
        memory_str = json.dumps(memory_data, indent=2, ensure_ascii=False)

    return character_name, chat_history, "", img_p, memory_str, character_name, log_content, character_name

def handle_save_memory_click(character_name, json_string_data):
    from memory_manager import save_memory_data # 遅延インポート
    if not character_name:
        gr.Warning("キャラクターが選択されていません。")
        return
    try:
        save_memory_data(character_name, json_string_data) # Call the correct function
        gr.Info(f"{character_name}さんの記憶を更新しました。")
    except json.JSONDecodeError as e:
        gr.Error(f"記憶データの形式（JSON）が正しくありません: {e}")
    except Exception as e:
        gr.Error(f"記憶の保存中に予期せぬエラーが発生しました: {e}")
        traceback.print_exc()


def handle_message_submission(*args: Any):
    from gemini_api import send_to_gemini # 遅延インポート

    (textbox_content, chatbot_history, current_character_name, current_model_name,
     current_api_key_name_state, file_input_list, add_timestamp_checkbox,
     send_thoughts_state, api_history_limit_state) = args

    if not all([current_character_name, current_model_name, current_api_key_name_state]):
        gr.Warning("キャラクター、モデル、APIキーをすべて選択してください。")
        return chatbot_history, gr.update(value=""), gr.update(value=None)

    log_f, sys_p, _, mem_p = character_manager.get_character_files_paths(current_character_name)
    if not log_f: # This implies other paths might also be None
        gr.Warning(f"キャラクター '{current_character_name}' の必須ファイルパス取得に失敗。処理を中断します。")
        return chatbot_history, gr.update(value=""), gr.update(value=None)

    user_prompt = textbox_content.strip() if textbox_content else ""
    if not user_prompt and not file_input_list: # No text and no files
        return chatbot_history, gr.update(value=""), gr.update(value=None)

    log_message_content = user_prompt
    actual_file_paths_for_api = []
    if file_input_list: # file_input_list is a list of file paths from Gradio
        for file_obj in file_input_list: # Gradio file objects have a .name attribute for the path
            actual_file_path = file_obj.name if hasattr(file_obj, 'name') else str(file_obj) # Robustly get path
            log_message_content += f"\n[ファイル添付: {os.path.basename(actual_file_path)}]"
            actual_file_paths_for_api.append(actual_file_path)


    user_header = _get_user_header_from_log(log_f, current_character_name)
    timestamp = f"\n{datetime.datetime.now():%Y-%m-%d (%a) %H:%M:%S}" if add_timestamp_checkbox else ""
    save_message_to_log(log_f, user_header, log_message_content.strip() + timestamp)

    uploaded_files_info_for_api = []
    if actual_file_paths_for_api: # Use the extracted actual paths
        for path in actual_file_paths_for_api:
            mime_type, _ = mimetypes.guess_type(path)
            uploaded_files_info_for_api.append({"path": path, "mime_type": mime_type or "application/octet-stream"})

    api_response_text = ""
    generated_image_path = None
    try:
        api_response_text, generated_image_path = send_to_gemini(
            sys_p, log_f, user_prompt, current_model_name, current_character_name,
            send_thoughts_state, api_history_limit_state, uploaded_files_info_for_api, mem_p # Pass correct var
        )

        if api_response_text or generated_image_path:
            response_to_log = (f"[Generated Image: {generated_image_path}]\n\n" if generated_image_path else "") + (api_response_text or "")
            save_message_to_log(log_f, f"## {current_character_name}:", response_to_log)
    except Exception as e:
        traceback.print_exc()
        gr.Error(f"メッセージ処理中に予期せぬエラー: {e}")

    new_log = load_chat_log(log_f, current_character_name)
    new_hist = format_history_for_gradio(new_log[-(config_manager.HISTORY_LIMIT * 2):])
    return new_hist, gr.update(value=""), gr.update(value=None)

def handle_alarm_selection_and_feedback(df_with_ids: pd.DataFrame, evt: gr.SelectData):
    """Dataframeでの行選択を処理し、選択されたIDとフィードバックメッセージを返す。単一選択・複数選択の両方に対応。"""

    if evt.index is None:
        return [], "アラームを選択してください"

    # Gradioのイベントデータを正規化 (This handles both single tuple and list of tuples)
    indices_list = evt.index if isinstance(evt.index, list) else [evt.index]

    if not indices_list: # Should not happen if evt.index was not None
        return [], "アラームを選択してください"

    try:
        # 選択された行のインデックスだけを重複なく抽出する
        # Ensure idx is a tuple and has at least one element before idx[0]
        selected_row_indices = sorted(list(set([idx[0] for idx in indices_list if isinstance(idx, tuple) and len(idx) > 0])))
    except (TypeError, IndexError) as e:
        print(f"Error processing event indices in handle_alarm_selection_and_feedback: {evt.index} -> {e}")
        traceback.print_exc()
        return [], "選択情報の取得に失敗しました。再度お試しください。"

    if not selected_row_indices or df_with_ids.empty:
        return [], "アラームを選択してください"

    try:
        valid_indices = [i for i in selected_row_indices if i < len(df_with_ids)]
        if not valid_indices: return [], "選択した行が見つかりません。"

        selected_ids = df_with_ids.iloc[valid_indices]["id"].tolist()

        if len(selected_ids) == 1:
            row = df_with_ids.iloc[valid_indices[0]]
            return selected_ids, f"選択中: 「{row['テーマ']}」 ({row['時刻']})"
        else:
            return selected_ids, f"{len(selected_ids)}件のアラームを選択中"

    except (KeyError, IndexError) as e:
        print(f"エラー: データアクセス中にエラー: {e}")
        traceback.print_exc()
        return [], "IDの取得に失敗しました。"


def load_alarm_to_form(selected_ids: list):
    import alarm_manager # 遅延インポート

    if not selected_ids or len(selected_ids) != 1:
        chars = character_manager.get_character_list()
        # Use DAY_MAP_JA_TO_EN.keys() as it's JA days for checkbox group
        return "アラーム追加", "", "", chars[0] if chars else None, list(DAY_MAP_JA_TO_EN.keys()), "08", "00", None

    alarm = alarm_manager.get_alarm_by_id(selected_ids[0])
    if not alarm: # Alarm not found
        gr.Warning(f"ID '{selected_ids[0]}'のアラームが見つかりません。")
        chars = character_manager.get_character_list()
        return "アラーム追加", "", "", chars[0] if chars else None, list(DAY_MAP_JA_TO_EN.keys()), "08", "00", None

    h, m = alarm.get("time", "08:00").split(":")
    # Ensure days are correctly mapped from EN (stored) to JA (display)
    days_ja = [DAY_MAP_EN_TO_JA.get(d_en, "?") for d_en in alarm.get("days", [])]
    return "アラーム更新", alarm.get("theme", ""), alarm.get("flash_prompt_template", ""), alarm.get("character", ""), days_ja, h, m, alarm.get("id")

def toggle_selected_alarms_status(selected_ids: list, new_status: bool):
    import alarm_manager # 遅延インポート
    if not selected_ids:
        gr.Warning("操作するアラームが選択されていません。")
    else:
        for alarm_id_val in selected_ids: # Use different var name
            alarm_manager.update_alarm(alarm_id_val, {"enabled": new_status})
        gr.Info(f"{len(selected_ids)}件のアラームを{'有効化' if new_status else '無効化'}しました。")
    return render_alarms_as_dataframe() # Always re-render

def handle_delete_selected_alarms(selected_ids: list):
    import alarm_manager # 遅延インポート
    if not selected_ids:
        gr.Warning("削除するアラームが選択されていません。")
    else:
        count = sum(1 for alarm_id_val in selected_ids if alarm_manager.delete_alarm(alarm_id_val))
        gr.Info(f"{count}件のアラームを削除しました。")
    return render_alarms_as_dataframe() # Always re-render

def handle_add_or_update_alarm(editing_id, h, m, char, theme, prompt, days_ja):
    import alarm_manager # 遅延インポート
    if not char or not theme.strip():
        gr.Warning("キャラクターとテーマは必須です。")
        # Return current values to keep form populated
        return render_alarms_as_dataframe(), render_alarms_as_dataframe(), editing_id if editing_id else "アラーム追加", theme, prompt, char, days_ja, h, m, editing_id

    # Convert JA days to EN for storage
    days_en = [DAY_MAP_JA_TO_EN.get(d_ja, d_ja.lower()[:3]) for d_ja in days_ja] # Fallback for safety

    if editing_id:
        data = {"time": f"{h}:{m}", "character": char, "theme": theme.strip(), "flash_prompt_template": prompt.strip() if prompt else None, "days": days_en}
        alarm_manager.update_alarm(editing_id, data)
        gr.Info(f"アラーム「{theme}」を更新しました。")
    else:
        alarm_manager.add_alarm(h, m, char, theme.strip(), prompt.strip() if prompt else None, days_ja) # add_alarm expects days_ja
        gr.Info(f"アラーム「{theme}」を追加しました。")

    new_df = render_alarms_as_dataframe()
    chars = character_manager.get_character_list()
    return new_df, new_df, "アラーム追加", "", "", chars[0] if chars else None, list(DAY_MAP_JA_TO_EN.keys()), "08", "00", None

def update_model_state(new_model):
    config_manager.save_config("last_model", new_model)
    return new_model

def update_api_key_state(new_key_name):
    from gemini_api import configure_google_api # 遅延インポート
    if new_key_name in config_manager.API_KEYS:
        configure_google_api(new_key_name)
        config_manager.save_config("last_api_key_name", new_key_name)
    else: gr.Warning("無効なAPIキー名です。")
    return new_key_name

def update_timestamp_state(enabled): config_manager.save_config("add_timestamp", enabled) # No return needed
def update_send_thoughts_state(enabled): config_manager.save_config("last_send_thoughts_to_api", enabled); return enabled

def update_api_history_limit_state(value): # Value is display string e.g. "直近10ターン"
    # Convert display value back to key
    key = next((k for k, v_display in config_manager.API_HISTORY_LIMIT_OPTIONS.items() if v_display == value), "all")
    config_manager.save_config("last_api_history_limit_option", key)
    return key # Return the key for state

def handle_save_log_button_click(character_name: str, log_content: str):
    if not character_name: gr.Warning("キャラクターが選択されていません。"); return
    try:
        character_manager.save_log_file(character_name, log_content)
        gr.Info(f"{character_name}さんのログを保存しました。")
    except Exception as e: gr.Error(f"ログの保存中にエラー: {e}"); traceback.print_exc()


def reload_chat_log(character_name: str):
    if not character_name: return [], ""
    log_f, _, _, _ = character_manager.get_character_files_paths(character_name)
    log_content_val = ""
    if log_f and os.path.exists(log_f):
        with open(log_f, 'r', encoding='utf-8') as f: log_content_val = f.read()
    return format_history_for_gradio(load_chat_log(log_f, character_name)[-config_manager.HISTORY_LIMIT*2:]), log_content_val


def handle_timer_submission(timer_type, dur_min, work_min, break_min, cycles, char_name, work_theme_val, break_theme_val, api_key, webhook_url_val, normal_theme_val):
    from timers import UnifiedTimer # 遅延インポート
    if not char_name or not api_key:
        gr.Warning("キャラクターとAPIキーを選択してください。")
        return "キャラクターとAPIキーを選択してください。" # Return message to status output

    timer = UnifiedTimer.get_instance()
    if timer.is_running(): timer.stop(); print("既存のタイマーを停止しました。")

    timer.set_properties(char_name, api_key, webhook_url_val)

    msg_out = ""
    if timer_type == "通常タイマー":
        if not (dur_min and dur_min > 0): gr.Warning("タイマー時間を正しく設定してください。"); return "タイマー時間を正しく設定してください。"
        theme_to_use = normal_theme_val or "タイマー終了！"
        timer.set_normal_timer(dur_min * 60, theme_to_use)
        msg_out = f"{char_name}さんによる「{theme_to_use}」タイマーを{dur_min}分でセットしました。"
    elif timer_type == "ポモドーロタイマー":
        if not (work_min and work_min > 0 and break_min and break_min > 0 and cycles and cycles > 0):
            gr.Warning("ポモドーロの各時間を正しく設定してください。"); return "ポモドーロの各時間を正しく設定してください。"
        work_th = work_theme_val or "作業終了！"; break_th = break_theme_val or "休憩終了！"
        timer.set_pomodoro(work_min * 60, break_min * 60, cycles, work_th, break_th)
        msg_out = f"{char_name}さんによるポモドーロタイマーをセット (作業{work_min}分, 休憩{break_min}分, {cycles}サイクル)。"
    else:
        gr.Warning("無効なタイマータイプです。"); return "無効なタイマータイプです。"

    timer.start()
    gr.Info(msg_out)
    return msg_out

def stop_existing_timer_on_startup(): # Called by log2gemini.py
    from timers import UnifiedTimer # 遅延インポート
    timer = UnifiedTimer.get_instance()
    if timer.is_running():
        timer.stop()
        print("アプリケーション起動時、既存のタイマーを停止しました。 (ui_handlers.stop_existing_timer_on_startup)")
