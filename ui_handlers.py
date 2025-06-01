# -*- coding: utf-8 -*-
from typing import List, Optional, Dict, Any, Tuple # Added Tuple
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

# --- Helper Functions for handle_message_submission ---

def _validate_submission_inputs(character_name: str | None, model_name: str | None, api_key_name: str | None) -> str | None:
    """Validates essential inputs for message submission."""
    if not character_name: return "キャラクターが選択されていません。"
    if not model_name: return "AIモデルが選択されていません。"
    if not api_key_name: return "APIキーが選択されていません。"
    return None

def _configure_api_key_if_needed(api_key_name: str) -> tuple[bool, str]:
    """Configures the Gemini API with the selected key. Returns success status and error message string (empty if success)."""
    success, message = configure_google_api(api_key_name)
    if not success:
        return False, f"APIキー設定エラー: {message or '不明なエラー'}" # Ensure message is not None
    return True, "" # Success, no error message

def _process_uploaded_files(
    file_input_list: Optional[List[Any]], # Gradio File objects. Type 'Any' for Gradio's FileData object.
    # character_name: str # Optional: if files need to be saved in character-specific subdirs
) -> tuple[str, List[Dict[str, str]], List[str]]:
    """
    Processes uploaded files. Copies them to a persistent location,
    extracts text from supported text files, and prepares a list for Gemini API.

    Returns:
        - consolidated_text (str): Concatenated text from all valid text files.
        - files_for_api (List[Dict[str, str]]): List of dicts for non-text files,
                                                 e.g., {'path': str, 'mime_type': str, 'original_filename': str}.
        - error_messages (List[str]): List of error messages encountered during processing.
    """
    consolidated_text = ""
    files_for_api: List[Dict[str, str]] = []
    error_messages: List[str] = []

    if not file_input_list:
        return consolidated_text, files_for_api, error_messages

    for file_obj in file_input_list:
        original_filename = "unknown_file" # Default in case of issues
        try:
            # Gradio's FileData object has 'name' (temp path) and 'orig_name' (original client-side name)
            temp_file_path = file_obj.name
            original_filename = getattr(file_obj, 'orig_name', os.path.basename(temp_file_path))

            file_extension = os.path.splitext(original_filename)[1].lower()
            file_type_info = SUPPORTED_FILE_MAPPINGS.get(file_extension)

            if not file_type_info:
                error_messages.append(f"ファイル形式非対応: {original_filename}")
                continue

            mime_type = file_type_info["mime_type"]
            category = file_type_info["category"]

            if category == 'text':
                content_to_add = None
                # Common encodings to try for text files
                encodings_to_try = ['utf-8', 'shift_jis', 'cp932', 'euc-jp', 'iso2022-jp', 'latin1']
                for enc in encodings_to_try:
                    try:
                        with open(temp_file_path, 'r', encoding=enc) as f_content:
                            content_to_add = f_content.read()
                        # print(f"情報: ファイル '{original_filename}' をエンコーディング '{enc}' で読み込み成功。")
                        break
                    except UnicodeDecodeError:
                        # print(f"デバッグ: ファイル '{original_filename}' のデコード失敗 (エンコーディング: {enc})。")
                        continue
                    except Exception as e_file_read: # Catch other file read errors
                        error_messages.append(f"ファイル読込エラー ({original_filename}, encoding {enc}): {str(e_file_read)}")
                        content_to_add = None
                        break

                if content_to_add is not None:
                    consolidated_text += f"\n\n--- 添付ファイル「{original_filename}」の内容 ---\n{content_to_add}"
                else:
                    # Avoid duplicate error if a specific read error was already logged
                    if not any(msg.startswith(f"ファイル読込エラー ({original_filename}") for msg in error_messages):
                        error_messages.append(f"ファイルデコード失敗 ({original_filename}): 全てのエンコーディング試行に失敗しました。")

            elif category in ['image', 'pdf', 'audio', 'video']:
                # Ensure ATTACHMENTS_DIR exists (already done at top-level but good for robustness)
                # os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
                unique_filename_for_attachment = f"{uuid.uuid4()}{file_extension}"
                saved_attachment_path = os.path.join(ATTACHMENTS_DIR, unique_filename_for_attachment)

                shutil.copy2(temp_file_path, saved_attachment_path) # Copy from temp path to persistent path
                files_for_api.append({
                    'path': saved_attachment_path,
                    'mime_type': mime_type,
                    'original_filename': original_filename # Keep original name for reference if needed
                })
                # print(f"情報: ファイル '{original_filename}' を '{saved_attachment_path}' にコピーしました。")
            else:
                 error_messages.append(f"未定義カテゴリ '{category}' のファイル: {original_filename}")

        except Exception as e_process: # Catch errors during the processing of a single file
            error_messages.append(f"ファイル処理中エラー ({original_filename}): {str(e_process)}")
            traceback.print_exc() # Log detailed error to console

    return consolidated_text.strip(), files_for_api, error_messages

def _log_user_interaction(
    log_file_path: str,
    user_header: str,
    original_user_text: str,
    text_from_files: str, # To know if text files were part of the input
    files_for_gemini_api: List[Dict[str, str]], # List of non-text files
    add_timestamp_checkbox: bool,
    user_action_timestamp_str: str # Already formatted timestamp string
) -> None:
    """Logs the user's text input and information about attached files in a structured way."""

    timestamp_applied_for_action = False

    # 1. Log the original user text input
    if original_user_text:
        text_to_log = original_user_text
        if add_timestamp_checkbox:
            text_to_log += user_action_timestamp_str
            timestamp_applied_for_action = True
        save_message_to_log(log_file_path, user_header, text_to_log)

    # 2. Log if text from files was included (as a single consolidated message)
    if text_from_files: # text_from_files already contains the formatted "--- Attached file... ---"
        # This text is part of what's sent to the API (api_text_arg).
        # For the log, we indicate that text file contents were part of the submission.
        # The actual content of text_from_files is already logged if original_user_text was empty
        # and text_from_files became the main part of api_text_arg.
        # To avoid duplicate logging of the content of text files if they were part of api_text_arg,
        # here we only log a placeholder if original_user_text was also present.
        # If original_user_text was empty, text_from_files effectively becomes the user's main message.

        # Simplified: The combined (original_user_text + text_from_files) is already part of api_text_arg.
        # If api_text_arg is what's logged as the primary user message, this separate logging might be redundant
        # or could be a placeholder like "[Content from text files was included in the message]".
        # For now, assuming the main api_text_arg (which includes text_from_files) is logged elsewhere
        # or that the current logging in handle_message_submission for api_text_arg is sufficient.
        # This helper will focus on logging non-text file attachments clearly.
        # However, if original_user_text is empty, text_from_files IS the main message.

        # Let's refine: log a generic placeholder if original_user_text was present,
        # otherwise, text_from_files was the main message and already logged (or will be).
        if original_user_text: # If there was main text, just note that text files were also there.
            log_entry_for_text_files = "[添付テキストファイルの内容はメインメッセージに結合されました]"
            if add_timestamp_checkbox and not timestamp_applied_for_action:
                log_entry_for_text_files += user_action_timestamp_str
                timestamp_applied_for_action = True
            save_message_to_log(log_file_path, user_header, log_entry_for_text_files)

    # 3. Log non-text file attachments
    for i, file_info in enumerate(files_for_gemini_api):
        log_entry_for_file = f"[ファイル添付: {file_info.get('saved_path')};{file_info.get('original_filename', '不明なファイル')};{file_info.get('mime_type', '不明なMIMEタイプ')}]"
        if add_timestamp_checkbox and not timestamp_applied_for_action and i == 0:
            # If no text message got the timestamp, the first file attachment gets it.
            log_entry_for_file += user_action_timestamp_str
            timestamp_applied_for_action = True
        save_message_to_log(log_file_path, user_header, log_entry_for_file)


def handle_message_submission(
    textbox: str,
    chatbot: List[List[Optional[str]]],
    current_character_name: str,
    current_model_name: str,
    current_api_key_name_state: str,
    file_input_list: Optional[List[str]],
    add_timestamp_checkbox: bool,
    send_thoughts_state: bool,
    api_history_limit_state: str
) -> Tuple[List[List[Optional[str]]], str, Optional[List[str]], str]: # Added return type hint
    print(f"\n--- メッセージ送信処理開始 --- {datetime.datetime.now()} ---")
    os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
    error_message = ""
    # Preserve the original text from the textbox parameter for potential restoration
    original_user_text_on_entry = textbox.strip() if textbox else ""

    # 1. Input Validation
    validation_error = _validate_submission_inputs(current_character_name, current_model_name, current_api_key_name_state)
    if validation_error:
        # Return 4 values: chatbot state, textbox state (empty), file input state (None), error message
        return chatbot, "", None, validation_error

    # 2. API Key Configuration
    api_configured, api_error_msg = _configure_api_key_if_needed(current_api_key_name_state)
    if not api_configured:
        # Restore the original text if API key config fails
        return chatbot, gr.update(value=original_user_text_on_entry), gr.update(value=None), api_error_msg

    # 3. Get Character File Paths (moved after API key check for clarity)
    log_f, sys_p, _, mem_p = get_character_files_paths(current_character_name)
    if not all([log_f, sys_p, mem_p]): # mem_p is memory_json_path
        error_message = f"キャラクター '{current_character_name}' の必須ファイル（ログ、プロンプト、記憶）のパス取得に失敗しました。"
        # Restore original text as this is a setup issue, not a transient input error
        return chatbot, gr.update(value=original_user_text_on_entry), gr.update(value=None), error_message

    original_user_text = textbox.strip() if textbox else "" # This is the current text, might be empty if cleared by previous error
    # file_input_list is now a list of file objects from gr.Files
    
    api_text_arg = original_user_text # Base text for API
    processed_files_info = [] 
    unsupported_files_messages = []
    
    # Timestamp for the overall user action, applied to the first text log entry
    # or to individual file logs if no text is present.
    user_action_timestamp_str = ""
    # Check original_user_text (from textbox) or file_input_list (if files were provided)
    if add_timestamp_checkbox and (original_user_text_on_entry or file_input_list):
        now = datetime.datetime.now()
        user_action_timestamp_str = f"\n{now.strftime('%Y-%m-%d (%a) %H:%M:%S')}"

    # 4. Process Uploaded Files (Helper function call)
    # Pass character_name for potential character-specific attachment subdirectories (though not used in current _process_uploaded_files)
    text_from_files, files_for_gemini_api, file_processing_errors = _process_uploaded_files(file_input_list)
    if file_processing_errors:
        error_message = (error_message + "\n" if error_message else "") + "\n".join(file_processing_errors)

    # 5. Prepare final text for API
    api_text_arg = original_user_text_on_entry + text_from_files # text_from_files is already pre-formatted

    # Check if there's anything to send
    if not api_text_arg.strip() and not files_for_gemini_api:
        error_message = (error_message + "\n" if error_message else "") + "送信するメッセージまたは処理可能なファイルがありません。"
        return chatbot, gr.update(value=original_user_text_on_entry), gr.update(value=None), error_message.strip()

    # --- Main processing block ---
    try:
        # 6. Log User Interaction
        user_header = _get_user_header_from_log(log_file_path, character_name)
        # The api_text_arg already contains original_user_text_on_entry + text_from_files.
        # We log this combined text if it's not empty.
        # Then, log non-text file attachments separately.
        
        # Log the combined text message that will be sent to the API (or was intended to)
        # This includes text from files.
        if api_text_arg.strip(): # Log only if there's actual text content
            text_to_log_for_user = api_text_arg
            if add_timestamp_checkbox: # Timestamp applies to the whole user submission turn
                text_to_log_for_user += user_action_timestamp_str
            save_message_to_log(log_file_path, user_header, text_to_log_for_user)
            # If only files were attached, and api_text_arg was initially empty but got populated by text_from_files,
            # then this log entry correctly includes that text and the timestamp.
        
        # Log non-text file attachments (images, pdfs etc.)
        # These are logged as placeholders because their content isn't text.
        # Timestamp is applied to the first of these IF no text was logged before with a timestamp.
        timestamp_applied_to_files = not (api_text_arg.strip() and add_timestamp_checkbox)
        for i, file_info in enumerate(files_for_gemini_api):
            log_entry_for_file = f"[ファイル添付: {file_info.get('saved_path')};{file_info.get('original_filename', '不明なファイル')};{file_info.get('mime_type', '不明なMIMEタイプ')}]"
            if add_timestamp_checkbox and not timestamp_applied_to_files and i == 0:
                 log_entry_for_file += user_action_timestamp_str
                 timestamp_applied_to_files = True # Ensure timestamp is added only once for the file group
            save_message_to_log(log_file_path, user_header, log_entry_for_file)
        
        # 7. Call Gemini API
        api_response_text = send_to_gemini(
            system_prompt_path,
            log_file_path,
            api_text_arg, # Combined text
            model_name,
            character_name,
            send_thoughts_to_api,
            api_history_limit_option,
            files_for_gemini_api, # Processed non-text files
            memory_json_path
        )

        # 8. Handle API Response (Error or Success)
        if api_response_text and isinstance(api_response_text, str) and \
           not (api_response_text.strip().startswith("エラー:") or \
                api_response_text.strip().startswith("API通信エラー:") or \
                api_response_text.strip().startswith("応答取得エラー") or \
                api_response_text.strip().startswith("応答生成失敗")):
            # Success from API
            save_message_to_log(log_file_path, f"## {character_name}:", api_response_text)
        else:
            # API returned an error string or response was None/empty
            error_messages_list.append(api_response_text or "APIから有効な応答がありませんでした。")
            # No need to return here, error_message will be returned at the end.

    except Exception as e: # Catch-all for unexpected errors during processing/logging/API call
        error_messages_list.append(f"処理中に予期せぬエラーが発生: {e}")
        traceback.print_exc()
        # Return original text to allow user to retry if it was a transient issue
        return chatbot, gr.update(value=original_user_text_on_entry), gr.update(value=None), error_message.strip()

    # 9. Update Chat History and Return
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