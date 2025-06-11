# -*- coding: utf-8 -*-
from typing import List, Optional, Dict, Any, Tuple, Union # Added Union
import gradio as gr
import datetime
import json
import traceback
import os
import uuid
import shutil
import re # Added for /gazo command refinement
# 分割したモジュールから必要な関数や変数をインポート
import config_manager
from timers import UnifiedTimer # Timer, PomodoroTimer はUnifiedTimerに統合されたと仮定し、直接は使わない想定
from character_manager import get_character_files_paths
from gemini_api import configure_google_api, send_to_gemini, generate_image_with_gemini
from memory_manager import load_memory_data_safe # save_memory_data はgemini_api内で呼ばれる想定
from utils import load_chat_log, format_history_for_gradio, save_message_to_log, _get_user_header_from_log

ATTACHMENTS_DIR = "chat_attachments"
os.makedirs(ATTACHMENTS_DIR, exist_ok=True) # Ensure ATTACHMENTS_DIR exists at startup

SUPPORTED_FILE_MAPPINGS = {
    # (変更なし)
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

def _validate_submission_inputs(
    character_name: Optional[str],
    model_name: Optional[str],
    api_key_name: Optional[str]
) -> Optional[str]:
    """
    メッセージ送信に必要な入力（キャラクター名、モデル名、APIキー名）を検証します。

    Args:
        character_name: 選択されたキャラクター名。
        model_name: 選択されたAIモデル名。
        api_key_name: 選択されたAPIキー名。

    Returns:
        検証エラーメッセージ文字列。問題がなければNone。
    """
    if not character_name:
        return "キャラクターが選択されていません。"
    if not model_name:
        return "AIモデルが選択されていません。"
    if not api_key_name:
        return "APIキーが選択されていません。"
    return None

def _configure_api_key_if_needed(api_key_name: str) -> Tuple[bool, str]:
    """
    選択されたAPIキーでGemini APIを設定します。

    Args:
        api_key_name: 設定するAPIキーの名前。

    Returns:
        Tuple[bool, str]: 設定成功のブール値と、エラーメッセージ（成功時は空文字列）。
    """
    success, message = configure_google_api(api_key_name)
    if not success:
        return False, f"APIキー設定エラー: {message or '不明なエラー'}"
    return True, ""

def _process_uploaded_files(
    file_input_list: Optional[List[Any]]
) -> Tuple[str, str, List[Dict[str, str]], List[str]]:
    """
    アップロードされたファイルを処理します。
    - API用の全文テキスト
    - ログ用の要約テキスト
    - API送信用ファイル情報
    - エラーメッセージ
    の4つを返します。
    """
    text_for_api = ""
    text_for_log = ""
    files_for_api: List[Dict[str, str]] = []
    error_messages: List[str] = []

    if not file_input_list:
        return text_for_api, text_for_log, files_for_api, error_messages

    # Ensure ATTACHMENTS_DIR exists
    if not os.path.exists(ATTACHMENTS_DIR):
        try:
            os.makedirs(ATTACHMENTS_DIR)
        except OSError as e:
            error_messages.append(f"添付ファイル保存ディレクトリ作成失敗: {ATTACHMENTS_DIR}, Error: {e}")
            # If directory creation fails, we can't process file-based attachments.
            # Depending on desired behavior, could return early or just log errors for files.
            # For now, we'll let it try to process, and individual file ops might fail.

    for file_obj in file_input_list:
        original_filename = "unknown_file"
        try:
            temp_file_path = file_obj.name # This is a temporary path from Gradio
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
                # Define encodings to try for text files
                encodings_to_try = ['utf-8', 'shift_jis', 'cp932', 'euc-jp', 'iso2022-jp', 'latin1']
                for enc in encodings_to_try:
                    try:
                        with open(temp_file_path, 'r', encoding=enc) as f_content:
                            content_to_add = f_content.read()
                        break # Successfully read
                    except UnicodeDecodeError:
                        continue # Try next encoding
                    except Exception as e_read: # Catch other potential read errors
                        # error_messages.append(f"ファイル読込エラー ({original_filename}, encoding {enc}): {e_read}")
                        # Let it try other encodings
                        continue

                if content_to_add is not None:
                    text_for_api += f"\n\n--- 添付ファイル「{original_filename}」の内容 ---\n{content_to_add}"
                    text_for_log += f"\n[添付テキスト: {original_filename}]" # Log only the tag
                elif not any(msg.startswith(f"ファイルデコード失敗 ({original_filename}") for msg in error_messages): # Avoid duplicate generic error
                    error_messages.append(f"ファイルデコード失敗 ({original_filename}): 全てのエンコーディング試行に失敗しました。")

            elif category in ['image', 'pdf', 'audio', 'video']:
                # Ensure os and uuid are imported
                _script_dir = os.path.dirname(os.path.abspath(__file__))
                # Now, chat_attachments is directly within _script_dir (e.g. eteruno_app/chat_attachments)
                save_dir = os.path.join(_script_dir, "chat_attachments")
                os.makedirs(save_dir, exist_ok=True) # Ensure absolute path directory exists

                unique_filename_for_attachment = f"{uuid.uuid4()}{file_extension}"
                saved_attachment_path = os.path.join(save_dir, unique_filename_for_attachment)

                shutil.copy2(temp_file_path, saved_attachment_path) # Copy from temp path to persistent storage

                files_for_api.append({
                    'path': saved_attachment_path, # This is the path to the copy in ATTACHMENTS_DIR
                    'mime_type': mime_type,
                    'original_filename': original_filename
                })
                # For non-text files, log a generic attachment tag
                text_for_log += f"\n[ファイル添付: {saved_attachment_path}]" # Use the absolute path
            else:
                 error_messages.append(f"未定義カテゴリ '{category}' のファイル: {original_filename}")

        except Exception as e_process:
            error_messages.append(f"ファイル処理中エラー ({original_filename}): {str(e_process)}")
            traceback.print_exc()

    return text_for_api.strip(), text_for_log.strip(), files_for_api, error_messages

def _log_user_interaction(
    log_file_path: str,
    user_header: str,
    original_user_text: str,
    text_from_files: str,
    files_for_api: List[Dict[str, str]], # Renamed from files_for_gemini_api for clarity
    add_timestamp_checkbox: bool,
    user_action_timestamp_str: str
) -> None:
    """
    ユーザーのテキスト入力と添付ファイル情報をログファイルに記録します。

    Args:
        log_file_path: ログファイルのパス。
        user_header: ユーザーを示すログヘッダー（例: "## User:"）。
        original_user_text: ユーザーがテキストボックスに入力した元のテキスト。
        text_from_files: 添付されたテキストファイルから抽出された連結テキスト。
        files_for_api: APIに送信される非テキストファイルの情報リスト。
        add_timestamp_checkbox: タイムスタンプを追加するかどうかのフラグ。
        user_action_timestamp_str: フォーマット済みのタイムスタンプ文字列（タイムスタンプ追加時）。
    """
    # This function's logic will be replaced by the direct logging within handle_message_submission
    # based on the user's new provided structure.
    # For now, to make the diff work, we keep the signature but the body will be effectively unused
    # if handle_message_submission is changed as per the prompt.
    # However, the prompt for handle_message_submission *does* call _log_user_interaction.
    # The prompt for handle_message_submission seems to imply that the _log_user_interaction
    # will be replaced by direct calls to save_message_to_log.
    # Let's assume _log_user_interaction is *not* used by the new handle_message_submission logic.
    # The prompt asks to replace a block *within* handle_message_submission that *calls* _process_uploaded_files,
    # and another block that *does* the logging and API sending.
    # So, _log_user_interaction as a helper might become obsolete or needs to be adjusted.
    # For now, I will leave _log_user_interaction as is, and the changes below will
    # effectively bypass its old role if the new handle_message_submission code is self-contained for logging.

    # The new handle_message_submission code seems to construct `final_text_for_log`
    # and then calls `save_message_to_log` directly. This means this helper might not be needed.
    # However, to ensure the diff applies cleanly without deleting this function if it's still called elsewhere
    # or if the user's intention was to modify it, I'll keep it for now.
    # The prompt for Part 2 does not mention removing or altering _log_user_interaction.
    # It only mentions replacing blocks *within* handle_message_submission.

    # Based on the NEW handle_message_submission code, this function _log_user_interaction
    # is NOT directly called. The logging logic is now embedded.
    # To avoid breaking the diff if this function is indeed removed or significantly changed
    # by a part of the prompt I'm not directly addressing, I will leave its old body.
    # The prompt is specific about replacing BLOCKS inside handle_message_submission.

    timestamp_applied_for_action = False
    combined_text_for_log = original_user_text
    if text_from_files:
        if combined_text_for_log:
            combined_text_for_log += "\n" + text_from_files
        else:
            combined_text_for_log = text_from_files
    
    if combined_text_for_log.strip():
        if add_timestamp_checkbox:
            combined_text_for_log += user_action_timestamp_str
            timestamp_applied_for_action = True
        save_message_to_log(log_file_path, user_header, combined_text_for_log)

    for i, file_info in enumerate(files_for_api):
        log_entry_for_file = f"[ファイル添付: {file_info.get('path')};{file_info.get('original_filename', '不明なファイル')};{file_info.get('mime_type', '不明なMIMEタイプ')}]"
        if add_timestamp_checkbox and not timestamp_applied_for_action:
            log_entry_for_file += user_action_timestamp_str
            timestamp_applied_for_action = True
        save_message_to_log(log_file_path, user_header, log_entry_for_file)


def handle_message_submission(
    textbox_content: Optional[str],
    chatbot_history: List[List[Optional[str]]], # Renamed from chatbot
    current_character_name: Optional[str],
    current_model_name: Optional[str],
    current_api_key_name_state: Optional[str],
    file_input_list: Optional[List[Any]], # Gradio File objects
    add_timestamp_checkbox: bool,
    send_thoughts_state: bool,
    api_history_limit_state: str
) -> Tuple[List[List[Optional[str]]], Any, Any, str]:
    """
    ユーザーからのメッセージ送信を処理し、AIに応答を問い合わせ、チャット履歴を更新します。

    Args:
        textbox_content: テキストボックスの現在の内容。
        chatbot_history: 現在のチャット履歴 (Gradio形式)。
        current_character_name: 選択されているキャラクター名。
        current_model_name: 選択されているAIモデル名。
        current_api_key_name_state: 選択されているAPIキー名。
        file_input_list: アップロードされたファイルのリスト (Gradio FileData オブジェクトなど)。
        add_timestamp_checkbox: メッセージにタイムスタンプを追加するかのブール値。
        send_thoughts_state: AIの思考過程をAPIに送信するかのブール値。
        api_history_limit_state: APIに送信する履歴の制限設定。

    Returns:
        Tuple[List[List[Optional[str]]], Any, Any, str]:
            - 更新されたチャット履歴 (Gradio形式)。
            - テキストボックスの更新指示 (通常は空文字列にクリアするためのgr.update)。
            - ファイル入力の更新指示 (通常はクリアするためのgr.update)。
            - 表示用のエラーメッセージ文字列 (エラーがなければ空)。
    """
    print(f"\n--- メッセージ送信処理開始 --- {datetime.datetime.now()} ---")
    error_message = ""
    original_user_text_on_entry = textbox_content.strip() if textbox_content else ""
    image_path = None # Initialize image_path here for broader scope

    # 1. Input Validation
    validation_error = _validate_submission_inputs(current_character_name, current_model_name, current_api_key_name_state)
    if validation_error:
        return chatbot_history, gr.update(value=original_user_text_on_entry), gr.update(value=file_input_list), validation_error

    # 2. API Key Configuration
    if not current_api_key_name_state: # Should have been caught by _validate_submission_inputs, but double check
         return chatbot_history, gr.update(value=original_user_text_on_entry), gr.update(value=file_input_list), "APIキーが選択されていません (内部エラー)。"
    
    api_configured, api_error_msg = _configure_api_key_if_needed(current_api_key_name_state)
    if not api_configured:
        return chatbot_history, gr.update(value=original_user_text_on_entry), gr.update(value=file_input_list), api_error_msg

    # 3. Get Character File Paths
    if not current_character_name: # Should have been caught by _validate_submission_inputs
        return chatbot_history, gr.update(value=original_user_text_on_entry), gr.update(value=file_input_list), "キャラクターが選択されていません (内部エラー)。"

    log_f, sys_p, _, mem_p = get_character_files_paths(current_character_name)
    if not all([log_f, sys_p, mem_p]):
        error_message = f"キャラクター '{current_character_name}' の必須ファイル（ログ、プロンプト、記憶）のパス取得に失敗しました。"
        return chatbot_history, gr.update(value=original_user_text_on_entry), gr.update(value=file_input_list), error_message

    # Timestamp for the user action
    user_action_timestamp_str = ""
    if add_timestamp_checkbox and (original_user_text_on_entry or file_input_list):
        now = datetime.datetime.now()
        user_action_timestamp_str = f"\n{now.strftime('%Y-%m-%d (%a) %H:%M:%S')}"

    # 4. Process Uploaded Files
    text_for_api_from_files, text_for_log_from_files, files_for_gemini_api, file_processing_errors = _process_uploaded_files(file_input_list)
    if file_processing_errors:
        error_message = (error_message + "\n" if error_message else "") + "\n".join(file_processing_errors)

# 5. Prepare final text for API (combined original text and text from files)
    api_text_arg = original_user_text_on_entry # Start with the text typed by the user
    if text_for_api_from_files: # Add content from text files (for API context)
        api_text_arg = (api_text_arg + "\n" + text_for_api_from_files).strip() if api_text_arg else text_for_api_from_files.strip()

    # --- Main processing block ---
    try:
        user_header = _get_user_header_from_log(log_f, current_character_name)

        # --- START OF JULES' REPLACEMENT BLOCK ---
        if original_user_text_on_entry.startswith("/gazo "):
            print(f"--- /gazo Debug --- /gazo command detected.")
            initial_image_prompt = original_user_text_on_entry[len("/gazo "):].strip()
            if not initial_image_prompt:
                error_message = "画像生成のプロンプトを指定してください。" # This error is for UI return
                return chatbot_history, gr.update(value=original_user_text_on_entry), gr.update(value=file_input_list), error_message

            # Log the user's original /gazo command
            user_gazo_log_text = original_user_text_on_entry
            if add_timestamp_checkbox:
                user_gazo_log_text += user_action_timestamp_str
            save_message_to_log(log_f, user_header, user_gazo_log_text)
            
            # Step A: Refine Prompt
            refined_image_prompt = initial_image_prompt 
            refinement_issues_notes = ""
            # did_refinement_succeed = False # Optional: useful for more complex branching if needed later

            prompt_for_refinement = f"""
**Instruction:** You are a prompt refiner. Your sole task is to refine the following user idea into an effective image generation prompt.
Output *only* the refined prompt itself, with no explanations, conversation, or markdown formatting (like quotes) around it.
If the idea is already a good prompt, output it as is.

**User Idea for Image Generation:**
{initial_image_prompt}

**Refined Prompt:**
"""
            print(f"--- /gazo Debug --- Initial User Prompt: '{initial_image_prompt}'")
            print(f"--- Debug /gazo --- Prompt for refinement (first 300 chars): {prompt_for_refinement[:300]}...")

            refined_image_prompt_response = send_to_gemini(
                system_prompt_path=sys_p, 
                log_file_path=log_f, # Log this meta-interaction? Decided against for now to keep chat cleaner.
                user_prompt=prompt_for_refinement,
                selected_model=current_model_name, 
                character_name=current_character_name,
                send_thoughts_to_api=False, 
                api_history_limit_option="0", 
                uploaded_file_parts=[], 
                memory_json_path=mem_p
            )
            
            print(f"--- /gazo Debug --- Raw Refinement Response: '{refined_image_prompt_response}'")
            
            use_initial_prompt_due_to_refinement_issue = False

            if not refined_image_prompt_response: # Check for empty response first
                refinement_issues_notes = "(プロンプト絞り込みモデルの応答が空だったため、元のプロンプトを使用します。)"
                print(f"警告: {refinement_issues_notes}")
                use_initial_prompt_due_to_refinement_issue = True
            else:
                stripped_response = refined_image_prompt_response.strip()
                if stripped_response.startswith("エラー:") or \
                   stripped_response.startswith("API通信エラー:") or \
                   stripped_response.startswith("応答取得エラー"):
                    refinement_issues_notes = f"(プロンプトの自動絞り込み処理でAPIエラーが発生したため、元のプロンプトを使用します。エラー詳細: {stripped_response})"
                    print(f"警告: プロンプト絞り込みAPI呼び出し失敗。{refinement_issues_notes}")
                    use_initial_prompt_due_to_refinement_issue = True
            
            if not use_initial_prompt_due_to_refinement_issue:
                # Convert to lowercase for case-insensitive keyword matching
                temp_cleaned_response_lower = refined_image_prompt_response.strip().lower()

                # Comprehensive list of keywords indicating refusal or unhelpfulness
                disqualification_keywords = [
                    "sorry", "unable", "cannot", "instead", "text-based",
                    "description of", "describe", "画像は生成できません", "できません",
                    "申し訳ありません", "画像の説明", "テキストベース", "as an ai language model",
                    "i do not have the capability", "i am a language model",
                    "i'm not able to create images"
                    # "エラー:", "API通信エラー:", "応答取得エラー" are checked above
                ]
                
                is_disqualified_by_keyword = False
                for keyword in disqualification_keywords:
                    if keyword in temp_cleaned_response_lower:
                        refinement_issues_notes = f"(プロンプト絞り込みモデルが非協力的/会話的な応答を返したため ('{keyword}'検出)、元のプロンプトを使用します。)"
                        print(f"警告: {refinement_issues_notes} Raw refinement response was: '{refined_image_prompt_response[:200]}...'")
                        is_disqualified_by_keyword = True
                        break
                
                if is_disqualified_by_keyword:
                    use_initial_prompt_due_to_refinement_issue = True
                else:
                    # Proceed with cleaning and using the refined prompt
                    candidate_prompt_str = refined_image_prompt_response.strip()
                    
                    # Remove "Refined Prompt:" prefix (case-insensitive)
                    keyword_parts = re.split(r"refined prompt:", candidate_prompt_str, flags=re.IGNORECASE)
                    if len(keyword_parts) > 1:
                        candidate_prompt_str = keyword_parts[-1].strip()

                    # Remove surrounding quotes
                    if (candidate_prompt_str.startswith('"') and candidate_prompt_str.endswith('"')) or \
                       (candidate_prompt_str.startswith("'") and candidate_prompt_str.endswith("'")):
                        candidate_prompt_str = candidate_prompt_str[1:-1].strip()
                    
                    # Select the last non-empty line if multiple lines exist, otherwise use the string as is if it's short and single-line
                    lines = [line.strip() for line in candidate_prompt_str.splitlines() if line.strip()]
                    
                    final_candidate_from_lines = ""
                    if lines:
                        # If the original candidate_prompt_str (after prefix/quote stripping) was single-line and not excessively long, prefer it.
                        if candidate_prompt_str.count('\n') == 0 and len(candidate_prompt_str) > 0 and len(candidate_prompt_str) < 350: # Max length for "good" single line
                             final_candidate_from_lines = candidate_prompt_str
                        else: # Otherwise, take the last line.
                             final_candidate_from_lines = lines[-1] 
                    
                    print(f"--- Debug /gazo --- Candidate prompt after cleaning: '{final_candidate_from_lines}'")

                    # Validate the cleaned candidate prompt (length, newlines, re-check keywords)
                    max_prompt_len = 400 
                    max_newlines = 2 # Allowing one newline, so < max_newlines means 0 or 1.

                    if final_candidate_from_lines and \
                       len(final_candidate_from_lines) <= max_prompt_len and \
                       final_candidate_from_lines.count('\n') < max_newlines:
                        
                        # Final keyword check on the cleaned, selected candidate line
                        is_still_disqualified_after_cleaning = False
                        for keyword in disqualification_keywords: # Use the same list
                            if keyword in final_candidate_from_lines.lower():
                                is_still_disqualified_after_cleaning = True
                                break
                        
                        if not is_still_disqualified_after_cleaning:
                            refined_image_prompt = final_candidate_from_lines
                            if refined_image_prompt == initial_image_prompt: 
                                refinement_issues_notes = "(絞り込み後のプロンプトは元のプロンプトと同じです。)"
                            else: 
                                refinement_issues_notes = "" # Successful refinement, no specific issue note needed unless it was same as original
                            print(f"情報: プロンプト絞り込み成功。使用プロンプト: '{refined_image_prompt}'")
                        else:
                            refinement_issues_notes = f"(絞り込み候補プロンプト内に非協力的/会話的なキーワード ('{keyword}') が再度検出されたため、元のプロンプトを使用します。)"
                            print(f"警告: {refinement_issues_notes} Candidate was: '{final_candidate_from_lines[:200]}...'")
                            use_initial_prompt_due_to_refinement_issue = True
                    else: 
                        if not final_candidate_from_lines: 
                            refinement_issues_notes = "(プロンプト絞り込みモデルの応答から有効なプロンプトを抽出できませんでした (空または処理後空)。元のプロンプトを使用します。)"
                        elif len(final_candidate_from_lines) > max_prompt_len:
                            refinement_issues_notes = f"(絞り込み後のプロンプト候補が長すぎるため ({len(final_candidate_from_lines)} > {max_prompt_len}文字)、元のプロンプトを使用します。)"
                        else: # Too many newlines
                            refinement_issues_notes = f"(絞り込み後のプロンプト候補に改行が多すぎるため ({final_candidate_from_lines.count('\n')} >= {max_newlines})、元のプロンプトを使用します。)"
                        print(f"警告: {refinement_issues_notes} Candidate was: '{final_candidate_from_lines[:max_prompt_len+50]}...'")
                        use_initial_prompt_due_to_refinement_issue = True

            if use_initial_prompt_due_to_refinement_issue:
                refined_image_prompt = initial_image_prompt
                # The specific reason for using initial_image_prompt should already be in refinement_issues_notes

            # Final safety check: if refined_image_prompt is somehow empty or whitespace, default to initial_image_prompt.
            if not refined_image_prompt.strip():
                refined_image_prompt = initial_image_prompt
                if not refinement_issues_notes: # Only set if no prior issue was noted
                    refinement_issues_notes = "(最終的な絞り込みプロンプトが空または空白のみだったため、元のプロンプトを使用します。)"
                elif not refinement_issues_notes.endswith("元のプロンプトを使用します。)"): # Append if note exists but doesn't mention using original
                    refinement_issues_notes += " (結果として元のプロンプトを使用します。)"
                print(f"警告: 最終的な絞り込みプロンプトが空または空白のみでした。元のプロンプトを使用します: '{initial_image_prompt}'")

            # Log refinement issues and the final prompt for generation
            print(f"--- /gazo Debug --- Refinement Issues Notes: '{refinement_issues_notes}'")
            print(f"--- /gazo Debug --- Final Prompt for Image Generation: '{refined_image_prompt}'")

            # Step B: Generate Image
            ai_response_parts_for_log = []
            ai_response_parts_for_log.append(f"[画像生成に使用されたプロンプト]: {refined_image_prompt}")
            if refinement_issues_notes and refinement_issues_notes.strip(): # Only add if there are notes
                 ai_response_parts_for_log.append(refinement_issues_notes.strip())

            sanitized_base_name = "".join(c if c.isalnum() or c in [' ', '_'] else '' for c in initial_image_prompt[:30]).strip().replace(' ', '_')
            if not sanitized_base_name: 
                sanitized_base_name = "generated_image"
            filename_suggestion = f"{current_character_name}_{sanitized_base_name}"
            
            print(f"--- Debug /gazo --- Calling generate_image_with_gemini with prompt: '{refined_image_prompt[:100]}...'")
            image_gen_text_response, image_path = generate_image_with_gemini(
                prompt=refined_image_prompt,
                output_image_filename_suggestion=filename_suggestion
            )
            print(f"--- Debug /gazo --- Image model text response: '{image_gen_text_response}'")
            print(f"--- Debug /gazo --- Image path: '{image_path}'")
            
            ui_error_message_for_return = "" # This is FOR THE UI (red error box)

            if image_gen_text_response and image_gen_text_response.strip(): 
                ai_response_parts_for_log.append(f"[画像モデルからのテキスト]: {image_gen_text_response.strip()}")

            if image_path:
                print(f"画像生成成功: {image_path}")
                ai_response_parts_for_log.append(f"[Generated Image: {image_path}]")
            else: # Image generation failed
                print(f"画像生成失敗。")
                ai_response_parts_for_log.append("[ERROR]: 画像の生成に失敗しました。") 
                # Set UI error message based on image model's text response, or a generic message
                if image_gen_text_response and image_gen_text_response.strip():
                    ui_error_message_for_return = image_gen_text_response.strip()
                else:
                    ui_error_message_for_return = "画像の生成に失敗しました (画像パスが返されませんでした)。"
            
            final_ai_log_entry = "\n".join(filter(None, ai_response_parts_for_log)) 
            save_message_to_log(log_f, f"## {current_character_name}:", final_ai_log_entry)
            
            error_message = ui_error_message_for_return # This sets the red error text in Gradio UI
        # --- END OF JULES' REPLACEMENT BLOCK ---

        else: # Not a /gazo command
            # --- ここからが【最重要修正点】 ---
            # 1. まず、テキスト部分だけをログに記録する
            # text_for_api_from_files にはテキストファイルの内容が入るので、これも含める
            text_log_entry = original_user_text_on_entry.strip() # User's typed text
            if text_for_api_from_files: # This is the full content of uploaded text files.
                 text_log_entry = (text_log_entry + "\n" + text_for_api_from_files).strip()

            # タイムスタンプは、テキスト部分にのみ適用する
            if text_log_entry: # Log if there's any text (typed or from text files)
                if add_timestamp_checkbox:
                    text_log_entry += user_action_timestamp_str
                save_message_to_log(log_f, user_header, text_log_entry)

            # 2. 次に、添付ファイル（画像など）を一つずつ、別のログエントリーとして記録する
            # files_for_gemini_api には、テキスト以外のファイル情報が格納されている
            for file_info in files_for_gemini_api:
                # ログに記録するのは、[ファイル添付: <絶対パス>] というタグのみ
                file_log_entry = f"[ファイル添付: {file_info['path']}]" # file_info['path'] is absolute path
                save_message_to_log(log_f, user_header, file_log_entry) # No separate timestamp for these file entries
            # --- ここまでが【最重要修正点】 ---

            # APIへの送信（全文コンテキストを使用）
            # Ensure there's something to send to API (either text or files for API)
            if not api_text_arg.strip() and not files_for_gemini_api: # files_for_gemini_api now holds non-text files for API
                 error_message = (error_message + "\n" if error_message else "") + "送信するメッセージまたは処理可能なファイルがありません。"
                 return chatbot_history, gr.update(value=original_user_text_on_entry), gr.update(value=file_input_list), error_message.strip()

            api_response_text, generated_image_path = send_to_gemini(
                system_prompt_path=sys_p,
                log_file_path=log_f,
                user_prompt=api_text_arg, # This argument is restored
                selected_model=current_model_name,
                character_name=current_character_name,
                send_thoughts_to_api=send_thoughts_state,
                api_history_limit_option=api_history_limit_state,
                uploaded_file_parts=files_for_gemini_api, # This argument was already there but its usage in send_to_gemini is now restored
                memory_json_path=mem_p
            )

            if api_response_text or generated_image_path:
                log_parts = []
                if generated_image_path:
                    log_parts.append(f"[Generated Image: {generated_image_path}]")

                is_error_response = False
                if api_response_text and isinstance(api_response_text, str):
                    stripped_response = api_response_text.strip()
                    if stripped_response.startswith("エラー:") or \
                       stripped_response.startswith("API通信エラー:") or \
                       stripped_response.startswith("応答取得エラー") or \
                       stripped_response.startswith("応答生成失敗"):
                        is_error_response = True

                if api_response_text and not is_error_response:
                    log_parts.append(api_response_text)

                if log_parts:
                    final_log_entry = "\n\n".join(log_parts)
                    save_message_to_log(log_f, f"## {current_character_name}:", final_log_entry)

                if api_response_text and is_error_response:
                     error_message = (error_message + "\n" if error_message else "") + api_response_text
            else:
                 no_content_error = "APIから有効な応答がありませんでした (テキストも画像もなし)。"
                 error_message = (error_message + "\n" if error_message else "") + no_content_error
                 print(f"API Info: {no_content_error}")

    except Exception as e:
        traceback.print_exc()
        err_msg = f"メッセージ処理中に予期せぬエラーが発生: {str(e)}"
        error_message = (error_message + "\n" if error_message else "") + err_msg
        return chatbot_history, gr.update(value=original_user_text_on_entry), gr.update(value=file_input_list), error_message.strip()

    # Update Chat History and Return (common for both /gazo and normal messages)
    if not error_message or image_path: # If /gazo was successful (image_path exists), error_message might be a text response
        new_log = load_chat_log(log_f, current_character_name)
        new_hist = format_history_for_gradio(new_log[-(config_manager.HISTORY_LIMIT * 2):])
    else: # If there was an error (and for /gazo, image_path is None)
        # If it was a /gazo error, it's already logged. We need to load history.
        if original_user_text_on_entry.startswith("/gazo "):
            new_log = load_chat_log(log_f, current_character_name)
            new_hist = format_history_for_gradio(new_log[-(config_manager.HISTORY_LIMIT * 2):])
        else: # For non-/gazo errors, keep old history if API call failed.
            new_hist = chatbot_history

    return new_hist, gr.update(value=""), gr.update(value=None), error_message.strip()

def update_ui_on_character_change(
    character_name: Optional[str]
) -> Tuple[Optional[str], Any, Any, Any, Any, Optional[str]]:
    """
    キャラクター選択の変更に応じてUIの各要素（チャット履歴、キャラクター名表示など）を更新します。

    Args:
        character_name: 選択されたキャラクター名。Noneの場合もあります。

    Returns:
        Tuple[Optional[str], Any, Any, Any, Any, Optional[str]]:
            - current_character_name_state: 更新後のキャラクター名。
            - chatbot: 更新されたチャット履歴表示 (gr.update)。
            - textbox: テキストボックスの更新 (通常はクリア、gr.update)。
            - character_image: キャラクター画像の更新 (gr.update)。
            - memory_display: 記憶データの表示更新 (gr.update)。
            - timer_character_dropdown: タイマー設定用キャラクタードロップダウンの更新 (gr.update)。
    """
    if not character_name:
        # キャラクターが選択解除されたか、初期状態で選択がない場合
        gr.Info("キャラクターが選択されていません。")
        return (
            None,                                  # current_character_name_state
            gr.update(value=[]),                   # chatbot
            gr.update(value=""),                   # textbox
            gr.update(value=None),                 # character_image
            gr.update(value="{}"),                 # memory_display
            gr.update(value=None)                  # timer_character_dropdown
        )
    
    print(f"UI更新: キャラクター変更 -> '{character_name}'")
    config_manager.save_config("last_character", character_name)
    
    log_f, _, img_p, mem_p = get_character_files_paths(character_name)
    
    # チャット履歴の読み込みとフォーマット
    chat_history_display = []
    if log_f and os.path.exists(log_f):
        # ログファイルが存在する場合のみ読み込む
        chat_history_for_gradio = format_history_for_gradio(
            load_chat_log(log_f, character_name)[-(config_manager.HISTORY_LIMIT * 2):]
        )
        chat_history_display = chat_history_for_gradio
    else:
        gr.Warning(f"キャラクター '{character_name}' のログファイルが見つかりません: {log_f}")

    # 記憶データの読み込み
    memory_data = load_memory_data_safe(mem_p)
    memory_display_str = json.dumps(memory_data, indent=2, ensure_ascii=False) \
                         if isinstance(memory_data, dict) else \
                         json.dumps({"error": "記憶データの読み込みまたは解析に失敗しました。"}, indent=2)

    # 各UIコンポーネントの更新指示を返す
    return (
        character_name,                        # current_character_name_state
        gr.update(value=chat_history_display), # chatbot
        gr.update(value=""),                   # textbox (キャラクター変更時はクリア)
        gr.update(value=img_p if img_p and os.path.exists(img_p) else None), # character_image
        gr.update(value=memory_display_str),   # memory_display
        gr.update(value=character_name)        # timer_character_dropdown
    )

def update_model_state(selected_model: Optional[str]) -> Union[Optional[str], Any]:
    """
    選択されたAIモデル名を更新し、設定ファイルに保存します。

    Args:
        selected_model: UIで選択されたモデル名。

    Returns:
        Union[Optional[str], Any]: 選択されたモデル名（GradioのState更新用）、または gr.update()。
    """
    if selected_model is None:
        # モデルが選択解除されたか、利用可能なモデルがない場合
        # gr.Warning("AIモデルが選択されていません。") # 必要に応じて通知
        return gr.update() # Stateは変更しない、またはデフォルトに戻すなど状況による
    
    print(f"設定更新: モデル変更 -> '{selected_model}'")
    config_manager.save_config("last_model", selected_model)
    return selected_model # Gradio Stateを更新するために選択されたモデル名を返す

def update_api_key_state(selected_api_key_name: Optional[str]) -> Union[Optional[str], Any]:
    """
    選択されたAPIキー名を更新し、設定ファイルに保存し、API設定を試みます。

    Args:
        selected_api_key_name: UIで選択されたAPIキーの名前。

    Returns:
        Union[Optional[str], Any]: 選択されたAPIキー名（GradioのState更新用）、または gr.update()。
    """
    if not selected_api_key_name:
        # APIキーが選択解除された場合
        # gr.Warning("APIキーが選択されていません。") # 必要に応じて通知
        return gr.update()

    print(f"設定更新: APIキー変更 -> '{selected_api_key_name}'")
    ok, msg = configure_google_api(selected_api_key_name)
    config_manager.save_config("last_api_key_name", selected_api_key_name)
    
    # グローバルなAPIキー名も更新（アラーム機能などで外部から参照される場合があるため）
    # config_manager を介して行うのが望ましいが、既存のコードに合わせて直接代入している場合は注意
    # 例: config_manager.set_global_api_key_name(selected_api_key_name) のような関数を config_manager に用意する
    # ここでは initial_api_key_name_global が config_manager の変数であることを前提とする
    if hasattr(config_manager, 'initial_api_key_name_global'):
         config_manager.initial_api_key_name_global = selected_api_key_name
    else:
        print("警告: config_manager.initial_api_key_name_global が見つかりません。")


    if ok:
        gr.Info(f"APIキー '{selected_api_key_name}' の設定に成功しました。")
    else:
        gr.Error(f"APIキー '{selected_api_key_name}' の設定に失敗しました: {msg}")
    
    return selected_api_key_name # Gradio Stateを更新するために選択されたAPIキー名を返す

def update_timestamp_state(add_timestamp_checked: bool) -> None:
    """
    タイムスタンプ追加チェックボックスの状態を設定ファイルに保存します。

    Args:
        add_timestamp_checked: チェックボックスの状態 (True/False)。

    Returns:
        None: この関数はUIの値を直接返さず、副作用（設定保存）のみ持ちます。
              GradioのState更新はチェックボックス自体が行います。
    """
    if isinstance(add_timestamp_checked, bool):
        print(f"設定更新: タイムスタンプ付加設定 -> {add_timestamp_checked}")
        config_manager.save_config("add_timestamp", add_timestamp_checked)
    else:
        # 通常発生しないはずだが、予期せぬ型が来た場合のフォールバック
        gr.Warning(f"タイムスタンプ設定の更新に失敗しました。無効な値: {add_timestamp_checked}")
    return None # チェックボックスのStateはGradioが管理するため、明示的な返り値は不要

def update_send_thoughts_state(send_thoughts_checked: bool) -> Union[bool, Any]:
    """
    「思考過程をAPIに送信する」チェックボックスの状態を更新し、設定ファイルに保存します。

    Args:
        send_thoughts_checked: チェックボックスの状態 (True/False)。

    Returns:
        Union[bool, Any]: チェックされた状態（GradioのState更新用）、または gr.update()。
    """
    if not isinstance(send_thoughts_checked, bool):
        # 予期せぬ型の場合、現在の状態を維持 (gr.update() で更新しない)
        gr.Warning(f"「思考過程を送信」設定の更新に失敗しました。無効な値: {send_thoughts_checked}")
        return gr.update()
        
    print(f"設定更新: 思考過程API送信設定 -> {send_thoughts_checked}")
    config_manager.save_config("last_send_thoughts_to_api", send_thoughts_checked)
    return send_thoughts_checked # Gradio Stateを更新

def update_api_history_limit_state(selected_limit_option_ui_value: Optional[str]) -> Union[str, Any]:
    """
    API履歴制限の選択を更新し、設定ファイルに保存します。

    Args:
        selected_limit_option_ui_value: UIで選択された履歴制限の表示名。

    Returns:
        Union[str, Any]: 対応する内部キー値（GradioのState更新用）、または gr.update()。
    """
    if not selected_limit_option_ui_value:
        gr.Warning("API履歴制限が選択されていません。")
        return gr.update() # 現在のStateを維持

    # UI表示名から内部設定キーを逆引き
    # config_manager.API_HISTORY_LIMIT_OPTIONS が {"internal_key": "UI Display Value", ...} の形式であると想定
    internal_key = next(
        (k for k, v in config_manager.API_HISTORY_LIMIT_OPTIONS.items() if v == selected_limit_option_ui_value),
        None
    )
    
    if internal_key:
        print(f"設定更新: API履歴制限 -> '{internal_key}' (UI表示: '{selected_limit_option_ui_value}')")
        config_manager.save_config("last_api_history_limit_option", internal_key)
        return internal_key # Gradio Stateを更新 (内部キーを返す)
    else:
        gr.Error(f"無効なAPI履歴制限オプションが選択されました: '{selected_limit_option_ui_value}'")
        return gr.update() # 現在のStateを維持

def reload_chat_log(character_name: Optional[str]) -> List[List[Optional[str]]]:
    """
    指定されたキャラクターのチャットログを再読み込みしてGradio表示形式で返します。

    Args:
        character_name: チャットログを読み込むキャラクターの名前。

    Returns:
        List[List[Optional[str]]]: GradioのChatbotコンポーネント用のチャット履歴。
                                     エラー時は空リスト。
    """
    if not character_name:
        gr.Info("ログ再読み込み: キャラクターが選択されていません。")
        return []

    log_file_path, _, _, _ = get_character_files_paths(character_name)
    
    if not log_file_path or not os.path.exists(log_file_path):
        gr.Warning(f"ログ再読み込み: キャラクター '{character_name}' のログファイルが見つかりません ({log_file_path})。")
        return []
    
    print(f"UI操作: '{character_name}' のチャットログを再読み込みします。")
    # HISTORY_LIMIT * 2 はユーザーとAIの発言ペアを考慮していると推測
    chat_log_for_display = format_history_for_gradio(
        load_chat_log(log_file_path, character_name)[-(config_manager.HISTORY_LIMIT * 2):]
    )
    gr.Info(f"'{character_name}' のチャットログを再読み込みしました。")
    return chat_log_for_display

def handle_timer_submission(
    timer_type: str,
    duration: Optional[float], # 分単位で入力される想定だが、UnifiedTimerが秒に変換
    work_duration: Optional[float], # 分単位
    break_duration: Optional[float], # 分単位
    cycles: Optional[int],
    current_character_name: Optional[str],
    work_theme: Optional[str],
    break_theme: Optional[str],
    api_key_name: Optional[str], # タイマー通知で使用するAPIキー
    webhook_url: Optional[str], # タイマー通知で使用するWebhook URL
    normal_timer_theme: Optional[str]
) -> None:
    """
    タイマー設定フォームからの送信を処理し、適切なタイマーを開始します。

    Args:
        timer_type: "通常タイマー" または "ポモドーロタイマー"。
        duration: 通常タイマーの期間（分）。
        work_duration: ポモドーロタイマーの作業期間（分）。
        break_duration: ポモドーロタイマーの休憩期間（分）。
        cycles: ポモドーロタイマーのサイクル数。
        current_character_name: タイマー通知のキャラクター名。
        work_theme: ポモドーロタイマーの作業終了時テーマ。
        break_theme: ポモドーロタイマーの休憩終了時テーマ。
        api_key_name: 通知に使用するAPIキーの名前。
        webhook_url: 通知に使用するWebhook URL。
        normal_timer_theme: 通常タイマーのテーマ。

    Returns:
        None: UIへのフィードバックはgr.Info/gr.Errorで行うため、直接の戻り値なし。
    """
    # 1. 必須項目の検証
    if not current_character_name:
        gr.Error("キャラクターが選択されていません。タイマーを設定するにはキャラクターを選択してください。")
        return
    if not api_key_name: # APIキーも通知に必須と仮定
        gr.Error("APIキーが選択されていません。タイマー通知のためにAPIキーを選択してください。")
        return
    # webhook_url はオプションかもしれないので、ここでは必須チェックしない (UnifiedTimer内で処理)

    if timer_type == "通常タイマー":
        if duration is None or duration <= 0: # 0以下の値も無効とする
            gr.Error("通常タイマーの時間を正しく入力してください（0より大きい値）。")
            return
    elif timer_type == "ポモドーロタイマー":
        if not (work_duration and work_duration > 0 and \
                break_duration and break_duration > 0 and \
                cycles and cycles > 0):
            gr.Error("ポモドーロタイマーの作業時間、休憩時間、サイクル数を正しく入力してください（全て0より大きい値）。")
            return
    else:
        gr.Error(f"不明なタイマータイプです: {timer_type}")
        return

    print(f"タイマー設定実行: タイプ='{timer_type}', キャラクター='{current_character_name}', "
          f"作業テーマ='{work_theme}', 休憩テーマ='{break_theme}', 通常テーマ='{normal_timer_theme}'")

    try:
        # UnifiedTimerのコンストラクタに渡す値が存在しない可能性を考慮し、Noneを許容する
        # duration, work_duration, break_duration は UnifiedTimer 側で * 60 されるので、そのまま渡す
        unified_timer = UnifiedTimer(
            timer_type=timer_type,
            duration=duration if duration is not None else 0, # Noneを0に変換 (UnifiedTimerが処理)
            work_duration=work_duration if work_duration is not None else 0,
            break_duration=break_duration if break_duration is not None else 0,
            cycles=cycles if cycles is not None else 0,
            character_name=current_character_name,
            work_theme=work_theme or "作業終了です！", # デフォルトテーマを設定
            break_theme=break_theme or "休憩終了！作業を再開しましょう。",
            api_key_name=api_key_name,
            webhook_url=webhook_url, # Noneの可能性あり
            normal_timer_theme=normal_timer_theme or "時間になりました！"
        )
        unified_timer.start()
        gr.Info(f"{timer_type}を開始しました。")
    except Exception as e:
        gr.Error(f"タイマーの開始中にエラーが発生しました: {str(e)}")
        traceback.print_exc()
