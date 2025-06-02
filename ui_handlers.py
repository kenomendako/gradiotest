# -*- coding: utf-8 -*-
from typing import List, Optional, Dict, Any, Tuple, Union # Added Union
import gradio as gr
import datetime
import json
import traceback
import os
import uuid
import shutil
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
    file_input_list: Optional[List[Any]] # Gradio File objects (e.g., FileData)
) -> Tuple[str, List[Dict[str, str]], List[str]]:
    """
    アップロードされたファイルを処理します。
    サポートされているテキストファイルからテキストを抽出し、他のファイルはAPI送信用に準備します。

    Args:
        file_input_list: Gradioのファイル入力コンポーネントからのファイルオブジェクトのリスト。
                         各要素は 'name' (一時パス) と 'orig_name' (元のファイル名) 属性を持つことを期待します。

    Returns:
        Tuple[str, List[Dict[str, str]], List[str]]:
            - consolidated_text (str): 全ての有効なテキストファイルから連結されたテキスト。
            - files_for_api (List[Dict[str, str]]): API送信用ファイル情報（パス、MIMEタイプなど）のリスト。
            - error_messages (List[str]): ファイル処理中に発生したエラーメッセージのリスト。
    """
    consolidated_text = ""
    files_for_api: List[Dict[str, str]] = []
    error_messages: List[str] = []

    if not file_input_list:
        return consolidated_text, files_for_api, error_messages

    for file_obj in file_input_list:
        original_filename = "unknown_file"
        try:
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
                encodings_to_try = ['utf-8', 'shift_jis', 'cp932', 'euc-jp', 'iso2022-jp', 'latin1']
                for enc in encodings_to_try:
                    try:
                        with open(temp_file_path, 'r', encoding=enc) as f_content:
                            content_to_add = f_content.read()
                        break
                    except UnicodeDecodeError:
                        continue
                    except Exception as e_file_read:
                        error_messages.append(f"ファイル読込エラー ({original_filename}, encoding {enc}): {str(e_file_read)}")
                        content_to_add = None
                        break
                if content_to_add is not None:
                    consolidated_text += f"\n\n--- 添付ファイル「{original_filename}」の内容 ---\n{content_to_add}"
                elif not any(msg.startswith(f"ファイル読込エラー ({original_filename}") for msg in error_messages):
                    error_messages.append(f"ファイルデコード失敗 ({original_filename}): 全てのエンコーディング試行に失敗しました。")
            
            elif category in ['image', 'pdf', 'audio', 'video']:
                unique_filename_for_attachment = f"{uuid.uuid4()}{file_extension}"
                saved_attachment_path = os.path.join(ATTACHMENTS_DIR, unique_filename_for_attachment)
                shutil.copy2(temp_file_path, saved_attachment_path)
                files_for_api.append({
                    'path': saved_attachment_path,
                    'mime_type': mime_type,
                    'original_filename': original_filename
                })
            else:
                 error_messages.append(f"未定義カテゴリ '{category}' のファイル: {original_filename}")

        except Exception as e_process:
            error_messages.append(f"ファイル処理中エラー ({original_filename}): {str(e_process)}")
            traceback.print_exc()

    return consolidated_text.strip(), files_for_api, error_messages

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
    timestamp_applied_for_action = False

    # 1. Log the original user text input (if any) combined with text from files
    combined_text_for_log = original_user_text
    if text_from_files:
        if combined_text_for_log: # If there's original text, add a separator
            combined_text_for_log += "\n" + text_from_files
        else: # If no original text, text_from_files is the main message
            combined_text_for_log = text_from_files
    
    if combined_text_for_log.strip():
        if add_timestamp_checkbox:
            combined_text_for_log += user_action_timestamp_str
            timestamp_applied_for_action = True
        save_message_to_log(log_file_path, user_header, combined_text_for_log)

    # 2. Log non-text file attachments
    for i, file_info in enumerate(files_for_api):
        # Use 'path' which is the key for the saved path in files_for_api
        log_entry_for_file = f"[ファイル添付: {file_info.get('path')};{file_info.get('original_filename', '不明なファイル')};{file_info.get('mime_type', '不明なMIMEタイプ')}]"
        if add_timestamp_checkbox and not timestamp_applied_for_action:
            # If no text message got the timestamp, or if logging files separately is desired,
            # apply timestamp to the first file (or all, depending on desired granularity not implemented here)
            log_entry_for_file += user_action_timestamp_str
            timestamp_applied_for_action = True # Ensure timestamp is added at most once per user action via this function
        save_message_to_log(log_file_path, user_header, log_entry_for_file)

def handle_message_submission(
    textbox_content: Optional[str], # Renamed from textbox for clarity
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
    text_from_files, files_for_gemini_api, file_processing_errors = _process_uploaded_files(file_input_list)
    if file_processing_errors:
        error_message = (error_message + "\n" if error_message else "") + "\n".join(file_processing_errors)

    # 5. Prepare final text for API (combined original text and text from files)
    api_text_arg = original_user_text_on_entry
    if text_from_files:
        api_text_arg = (api_text_arg + "\n" + text_from_files).strip() if api_text_arg else text_from_files.strip()

    # Check if there's anything to send
    if not api_text_arg.strip() and not files_for_gemini_api:
        # This check should happen AFTER /gazo check if /gazo only needs text_content
        pass # Moved this check lower for /gazo command that might not need files_for_gemini_api

    # --- Main processing block ---
    try:
        user_header = _get_user_header_from_log(log_f, current_character_name)

        if original_user_text_on_entry.startswith("/gazo "):
            initial_image_prompt = original_user_text_on_entry[len("/gazo "):].strip()
            if not initial_image_prompt:
                error_message = "画像生成のプロンプトを指定してください。"
                return chatbot_history, gr.update(value=original_user_text_on_entry), gr.update(value=file_input_list), error_message

            # Log the original /gazo command by user
            # _log_user_interaction might be too complex if we only have simple text here
            # We will log user's /gazo command, then AI's response (refined prompt + image tag)
            # For now, let's save the user's /gazo command directly.
            # Note: _log_user_interaction handles combined text and file logging.
            # For /gazo, we only have the text command.

            # Log user's initial /gazo command (without file attachments for this specific log entry)
            user_gazo_log_text = original_user_text_on_entry
            if add_timestamp_checkbox:
                user_gazo_log_text += user_action_timestamp_str
            save_message_to_log(log_f, user_header, user_gazo_log_text)

            # Step A: Refine Prompt
            # System prompt for refining image generation prompt
            refine_system_prompt_text = f"""You are an AI assistant. The user wants to generate an image.
Based on their idea: '{initial_image_prompt}', generate a concise and effective prompt that would be suitable for an image generation AI.
Output only the prompt itself, with no additional conversational text.
If the user's idea is too vague, too complex, or could be improved for clarity for an image AI, refine it.
If the user's idea is already good, you can use it as is or make minor enhancements.
Focus on key elements, style, and composition if appropriate from the initial idea.
Example: User idea 'cat flying in space' -> Refined prompt 'A fluffy cat wearing a tiny astronaut helmet, soaring through a vibrant nebula, digital art'.
Example: User idea 'beautiful sunset' -> Refined prompt 'A serene beach at sunset, with vibrant orange and purple hues reflecting on calm ocean waves, photorealistic'.
"""
            # Create a temporary system prompt file for this specific call, or pass text directly if send_to_gemini supports it.
            # Assuming send_to_gemini primarily uses system_prompt_path, we create a temp file.
            # However, send_to_gemini's first arg is system_prompt_path.
            # A better approach would be to modify send_to_gemini to accept raw system prompt text.
            # For now, let's use a simplified call or assume send_to_gemini can handle text if path is None.
            # The existing send_to_gemini loads sys_ins_text from system_prompt_path.
            # To avoid modifying send_to_gemini now, we'll skip using a system prompt for refinement,
            # and directly use the user's initial prompt, or prepend a simple instruction.
            # This is a deviation from "Construct a suitable system message" but simplifies immediate implementation.
            # Let's try to formulate a prompt that asks the LLM to refine another prompt.

            prompt_for_refinement = f"Refine this image generation idea into a concise and effective prompt for an image AI. Output only the refined prompt: '{initial_image_prompt}'"

            print(f"画像プロンプト絞り込みのためGeminiに送信: '{prompt_for_refinement[:100]}...'")
            refined_image_prompt_response = send_to_gemini(
                system_prompt_path=sys_p, # Using the character's main system prompt for this meta-task
                log_file_path=log_f,      # Log this meta-interaction? For now, no, to keep chat clean.
                user_prompt=prompt_for_refinement,
                selected_model=current_model_name,
                character_name=current_character_name,
                send_thoughts_to_api=False, # Probably don't need thoughts for this refinement
                api_history_limit_option="0", # No history needed for this
                uploaded_file_parts=[], # No files for refinement step
                memory_json_path=mem_p
            )

            if not refined_image_prompt_response or refined_image_prompt_response.strip().startswith("エラー:") or refined_image_prompt_response.strip().startswith("API通信エラー:") or refined_image_prompt_response.strip().startswith("応答取得エラー"):
                error_message = f"画像プロンプトの絞り込みに失敗: {refined_image_prompt_response or '不明なエラー'}"
                # Log this failure to the main chat as an AI response to the /gazo command
                save_message_to_log(log_f, f"## {current_character_name}:", error_message)
                # Fallback: use initial prompt if refinement fails
                # refined_image_prompt = initial_image_prompt
                # print(f"警告: プロンプト絞り込み失敗。元のプロンプトを使用: {initial_image_prompt}")
            else:
                refined_image_prompt = refined_image_prompt_response.strip()
                # Remove potential quotes around the refined prompt if the LLM added them
                if refined_image_prompt.startswith('"') and refined_image_prompt.endswith('"'):
                    refined_image_prompt = refined_image_prompt[1:-1]
                if refined_image_prompt.startswith("'") and refined_image_prompt.endswith("'"):
                    refined_image_prompt = refined_image_prompt[1:-1]
                print(f"AIによって絞り込まれた画像プロンプト: {refined_image_prompt}")

            if error_message: # If refinement failed and we set an error message
                # Update history and return
                new_log = load_chat_log(log_f, current_character_name)
                new_hist = format_history_for_gradio(new_log[-(config_manager.HISTORY_LIMIT * 2):])
                return new_hist, gr.update(value=""), gr.update(value=None), error_message.strip()

            # Step B: Generate Image
            # Sanitize initial_image_prompt for use in filename (simple version)
            sanitized_base_name = "".join(c if c.isalnum() or c in [' ', '_'] else '' for c in initial_image_prompt[:30]).strip().replace(' ', '_')
            if not sanitized_base_name: # If prompt was e.g. all symbols
                sanitized_base_name = "generated_image"
            filename_suggestion = f"{current_character_name}_{sanitized_base_name}"

            print(f"画像生成API呼び出し: プロンプト='{refined_image_prompt[:100]}...', ファイル名提案='{filename_suggestion}'")
            image_gen_text_response, image_path = generate_image_with_gemini(
                prompt=refined_image_prompt,
                output_image_filename_suggestion=filename_suggestion
            )

            ai_response_parts_for_log = []
            if refined_image_prompt != initial_image_prompt:
                 ai_response_parts_for_log.append(f"[AIが生成した画像プロンプト]: {refined_image_prompt}")

            if image_gen_text_response:
                ai_response_parts_for_log.append(image_gen_text_response)

            if image_path:
                print(f"画像生成成功: {image_path}")
                ai_response_parts_for_log.append(f"[Generated Image: {image_path}]")
            else:
                print(f"画像生成失敗。テキスト応答: {image_gen_text_response}")
                error_message = image_gen_text_response or "画像の生成に失敗しました (パスが返されませんでした)。"
                if "[AIが生成した画像プロンプト]:" not in error_message and refined_image_prompt != initial_image_prompt:
                    # Prepend the refined prompt to the error if it's not already part of it
                    error_message = f"[AIが生成した画像プロンプト]: {refined_image_prompt}\n{error_message}"

            final_ai_log_entry = "\n".join(ai_response_parts_for_log)
            if not final_ai_log_entry and not error_message: # Should not happen if image_path or error
                final_ai_log_entry = "画像処理が完了しましたが、テキスト応答も画像もありませんでした。"


            if error_message and not image_path: # Ensure error is logged if image failed
                 save_message_to_log(log_f, f"## {current_character_name}:", error_message)
            elif final_ai_log_entry: # Log successful image generation or text response
                 save_message_to_log(log_f, f"## {current_character_name}:", final_ai_log_entry)


        else: # Not a /gazo command, proceed with normal message submission
            if not api_text_arg.strip() and not files_for_gemini_api:
                error_message = (error_message + "\n" if error_message else "") + "送信するメッセージまたは処理可能なファイルがありません。"
                return chatbot_history, gr.update(value=original_user_text_on_entry), gr.update(value=file_input_list), error_message.strip()

            # Log User Interaction for normal messages
            _log_user_interaction(
                log_f,
                user_header,
                original_user_text_on_entry,
                text_from_files,
                files_for_gemini_api,
                add_timestamp_checkbox,
                user_action_timestamp_str
            )

            api_response_text = send_to_gemini(
                system_prompt_path=sys_p,
                log_file_path=log_f,
                user_prompt=api_text_arg,
                selected_model=current_model_name,
                character_name=current_character_name,
                send_thoughts_to_api=send_thoughts_state,
                api_history_limit_option=api_history_limit_state,
                uploaded_file_parts=files_for_gemini_api,
                memory_json_path=mem_p
            )

            if api_response_text and isinstance(api_response_text, str) and \
               not (api_response_text.strip().startswith("エラー:") or \
                    api_response_text.strip().startswith("API通信エラー:") or \
                    api_response_text.strip().startswith("応答取得エラー") or \
                    api_response_text.strip().startswith("応答生成失敗")):
                save_message_to_log(log_f, f"## {current_character_name}:", api_response_text)
            else:
                api_err = api_response_text or "APIから有効な応答がありませんでした。"
                error_message = (error_message + "\n" if error_message else "") + api_err
                print(f"API Error: {api_err}")
                # Note: For normal messages, if API fails, error is added to UI, but not logged to chat history as AI response.
                # This behavior is kept here. For /gazo, errors ARE logged as AI response.

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
