# -*- coding: utf-8 -*-
import gradio as gr
import datetime
import json
import traceback
import os
import uuid
import shutil
# 分割したモジュールから必要な関数や変数をインポート
import config_manager
from timers import Timer, PomodoroTimer, UnifiedTimer  # Use absolute import if 'my_timer_module.py' is in the same directory
from alarm_manager import start_alarm_timer  # Assuming it is defined in alarm_manager
from character_manager import get_character_files_paths
from gemini_api import configure_google_api, send_to_gemini
from memory_manager import save_memory_data, load_memory_data_safe
from utils import load_chat_log, format_history_for_gradio, save_message_to_log, _get_user_header_from_log

ATTACHMENTS_DIR = "chat_attachments"

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

# --- Gradio UI イベントハンドラ ---
# file_input is now a list of file objects (tempfile._TemporaryFileWrapper)
def handle_message_submission(textbox, chatbot, current_character_name, current_model_name, current_api_key_name_state, file_input_list, add_timestamp_checkbox, send_thoughts_state, api_history_limit_state):
    print(f"\n--- メッセージ送信処理開始 --- {datetime.datetime.now()} ---")
    os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
    error_message = ""
    # Preserve the original text from the textbox parameter for potential restoration
    original_user_text_on_entry = textbox.strip() if textbox else ""

    if not all([current_character_name, current_model_name, current_api_key_name_state]):
        error_message = "キャラクター、AIモデル、APIキーが選択されていません。設定を確認してください。"
        return chatbot, gr.update(value=""), gr.update(value=None), error_message

    # APIキー設定エラー処理
    ok, msg = configure_google_api(current_api_key_name_state)
    if not ok:
        error_message = f"APIキー設定エラー: {msg}"
        # Restore the original text if API key config fails
        return chatbot, gr.update(value=original_user_text_on_entry), gr.update(value=None), error_message

    log_f, sys_p, _, mem_p = get_character_files_paths(current_character_name)
    if not all([log_f, sys_p, mem_p]):
        error_message = f"キャラクター '{current_character_name}' のファイル（ログ、プロンプト、記憶）が見つかりません。"
        return chatbot, gr.update(value=""), gr.update(value=None), error_message

    original_user_text = textbox.strip() if textbox else "" # This is the current text, might be empty if cleared by previous error
    # file_input_list is now a list of file objects from gr.Files
    
    api_text_arg = original_user_text # Base text for API
    processed_files_info = [] 
    unsupported_files_messages = []
    
    # Timestamp for the overall user action, applied to the first text log entry
    # or to individual file logs if no text is present.
    user_action_timestamp_str = ""
    if add_timestamp_checkbox and (original_user_text or (file_input_list and len(file_input_list) > 0)):
        now = datetime.datetime.now()
        user_action_timestamp_str = f"\n{now.strftime('%Y-%m-%d (%a) %H:%M:%S')}"

    if not original_user_text and not file_input_list:
        error_message = "送信するメッセージまたはファイルがありません。"
        # Return 4 values: chatbot state, textbox state, file input state (clear), error message
        return chatbot, gr.update(value=original_user_text_on_entry), gr.update(value=None), error_message 

    try:
        if file_input_list:
            for file_obj in file_input_list:
                original_filename = "unknown_file"
                try:
                    # Try to get original name, fallback to a generic name from temp path
                    original_filename = file_obj.orig_name if hasattr(file_obj, 'orig_name') and file_obj.orig_name else os.path.basename(file_obj.name)
                    temp_file_path = file_obj.name
                    
                    file_extension = os.path.splitext(original_filename)[1].lower()
                    file_type_info = SUPPORTED_FILE_MAPPINGS.get(file_extension)

                    if not file_type_info:
                        unsupported_files_messages.append(f"ファイル形式非対応: {original_filename}")
                        continue

                    mime_type = file_type_info["mime_type"]
                    category = file_type_info["category"]
                    
                    current_file_info = {
                        'original_filename': original_filename,
                        'temp_path': temp_file_path,
                        'saved_path': None, # Will be set for non-text files
                        'mime_type': mime_type,
                        'category': category,
                        'content_for_api': None # For text files, their content
                    }

                    if category == 'text':
                        content_to_add = None
                        encodings_to_try = ['utf-8', 'shift_jis', 'cp932']
                        for enc in encodings_to_try:
                            try:
                                with open(temp_file_path, 'r', encoding=enc) as f_content:
                                    content_to_add = f_content.read()
                                print(f"Successfully read {original_filename} with encoding {enc}") # For debugging
                                break # Success
                            except UnicodeDecodeError:
                                print(f"Failed to decode {original_filename} with {enc}, trying next...") # For debugging
                                continue # Try next encoding
                            except Exception as e: # Other file errors
                                unsupported_files_messages.append(f"ファイル読込エラー ({original_filename}, encoding {enc}): {e}")
                                content_to_add = None # Ensure it's None if other error occurred
                                break # Don't try other encodings if a non-decode error happened
                        
                        if content_to_add is not None:
                            current_file_info['content_for_api'] = content_to_add
                        else:
                            # If all encodings failed or another error occurred
                            if not any(msg.startswith(f"ファイル読込エラー ({original_filename}") for msg in unsupported_files_messages): # Avoid duplicate general error if specific decode errors logged
                                unsupported_files_messages.append(f"ファイルデコード失敗 ({original_filename}): 全てのエンコーディング試行に失敗しました。")
                            continue # Skip this file from processed_files_info
                    elif category in ['image', 'pdf', 'audio', 'video']:
                        unique_filename_for_attachment = f"{uuid.uuid4()}{file_extension}"
                        saved_attachment_path = os.path.join(ATTACHMENTS_DIR, unique_filename_for_attachment)
                        shutil.copy2(temp_file_path, saved_attachment_path)
                        current_file_info['saved_path'] = saved_attachment_path
                    
                    processed_files_info.append(current_file_info)

                except Exception as e:
                    # Catch errors during individual file processing
                    unsupported_files_messages.append(f"処理エラー ({original_filename}): {e}")
                    traceback.print_exc() # Log detailed error to console

        # Consolidate text file contents into api_text_arg
        consolidated_text_file_contents = ""
        for p_file in processed_files_info:
            if p_file['category'] == 'text' and p_file['content_for_api']:
                consolidated_text_file_contents += f"\n\n--- 以下は添付ファイル「{p_file['original_filename']}」の内容 ---\n{p_file['content_for_api']}"
        
        if consolidated_text_file_contents:
            api_text_arg += consolidated_text_file_contents

        # Prepare files for Gemini API (non-text files that are saved)
        files_for_gemini_api = []
        for p_file in processed_files_info:
            if p_file['category'] != 'text' and p_file['saved_path']:
                files_for_gemini_api.append({'path': p_file['saved_path'], 'mime_type': p_file['mime_type']})
        
        # --- API Call ---
        # The send_to_gemini function will need to be adapted to handle a list of file parts.
        # For now, we pass it, assuming it will be updated.
        # Corrected to handle single return value from send_to_gemini
        resp = send_to_gemini(sys_p, log_f, api_text_arg, current_model_name, current_character_name, send_thoughts_state, api_history_limit_state, files_for_gemini_api, mem_p)

        # --- Error response from API ---
        if resp and (resp.strip().startswith("エラー:") or resp.strip().startswith("API通信エラー:") or resp.strip().startswith("応答取得エラー") or resp.strip().startswith("応答生成失敗")):
            # error_message is already initialized and might contain unsupported file messages
            error_message += f"\nGemini APIエラー: {resp}" if error_message else f"Gemini APIエラー: {resp}"
            # Preserve original text and return any accumulated error messages
            return chatbot, gr.update(value=original_user_text_on_entry), gr.update(value=None), error_message.strip()


        # --- User Message Logging ---
        user_header = _get_user_header_from_log(log_f, current_character_name)
        
        logged_any_user_action = False # Flag to ensure timestamp is applied only to the first logged action
        user_action_timestamp_str_used = False

        # 1. Log original user text if present
        if original_user_text:
            text_to_log = original_user_text
            if add_timestamp_checkbox and not user_action_timestamp_str_used:
                text_to_log += user_action_timestamp_str # Use the pre-calculated timestamp
                user_action_timestamp_str_used = True
            save_message_to_log(log_f, user_header, text_to_log)
            logged_any_user_action = True

        # 2. Log info about processed files
        for p_file in processed_files_info:
            log_entry = ""
            # Determine if this specific file log should get the main action timestamp
            # This happens if no original text was logged, and this is the first file being logged.
            timestamp_for_this_file_log = ""
            if add_timestamp_checkbox and not logged_any_user_action and not user_action_timestamp_str_used:
                timestamp_for_this_file_log = user_action_timestamp_str
                user_action_timestamp_str_used = True # Mark timestamp as used
            
            if p_file['category'] == 'text':
                # Log a placeholder for text files, as their content is in api_text_arg
                # These are logged individually without their content, as content is part of api_text_arg.
                log_entry = f"[添付テキストファイル: {p_file['original_filename']}]" + timestamp_for_this_file_log
            elif p_file['saved_path']: # Images, PDFs, Audio, Video that were saved
                log_entry = f"[file_attachment:{p_file['saved_path']};{p_file['original_filename']};{p_file['mime_type']}]" + timestamp_for_this_file_log
            
            if log_entry:
                save_message_to_log(log_f, user_header, log_entry)
                logged_any_user_action = True # Mark that some user action has been logged

        # Aggregate unsupported file messages with other errors
        if unsupported_files_messages:
            error_message = (error_message + "\n" if error_message else "") + "\n".join(unsupported_files_messages)
            
        # --- AI Response Logging ---
        if resp and resp.strip():
            save_message_to_log(log_f, f"## {current_character_name}:", resp)
        
    except Exception as e:
        error_message = (error_message + "\n" if error_message else "") + f"処理中に予期せぬエラーが発生: {e}"
        traceback.print_exc()
        return chatbot, gr.update(value=original_user_text_on_entry), gr.update(value=None), error_message.strip()

    new_log = load_chat_log(log_f, current_character_name)
    new_hist = format_history_for_gradio(new_log[-(config_manager.HISTORY_LIMIT * 2):])
    
    # Return "" for textbox, gr.update(value=None) for gr.Files to clear it, and any error messages
    return new_hist, "", gr.update(value=None), error_message.strip() if error_message else ""

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