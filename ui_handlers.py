# -*- coding: utf-8 -*-
from typing import List, Optional, Dict, Any, Tuple, Union
import gradio as gr
import datetime
import json
import traceback
import os
import uuid
import shutil
import re
import urllib.parse
# 分割したモジュールから必要な関数や変数をインポート
import config_manager
from timers import UnifiedTimer
from character_manager import get_character_files_paths
from gemini_api import configure_google_api, send_to_gemini, generate_image_with_gemini
from memory_manager import load_memory_data_safe
from utils import load_chat_log, save_message_to_log, _get_user_header_from_log, format_history_for_gradio as original_format_history_for_gradio

ATTACHMENTS_DIR = "chat_attachments"
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

# --- Gradio UI イベントハンドラ ---

# --- Helper Functions for handle_message_submission ---

def _validate_submission_inputs(
    character_name: Optional[str],
    model_name: Optional[str],
    api_key_name: Optional[str]
) -> Optional[str]:
    if not character_name:
        return "キャラクターが選択されていません。"
    if not model_name:
        return "AIモデルが選択されていません。"
    if not api_key_name:
        return "APIキーが選択されていません。"
    return None

def _configure_api_key_if_needed(api_key_name: str) -> Tuple[bool, str]:
    success, message = configure_google_api(api_key_name)
    if not success:
        return False, f"APIキー設定エラー: {message or '不明なエラー'}"
    return True, ""

def _process_uploaded_files(
    file_input_list: Optional[List[Any]]
) -> Tuple[str, List[Dict[str, str]], List[str]]:
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
    files_for_api: List[Dict[str, str]],
    add_timestamp_checkbox: bool,
    user_action_timestamp_str: str
) -> None:
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
    chatbot_history: List[List[Optional[str]]],
    current_character_name: Optional[str],
    current_model_name: Optional[str],
    current_api_key_name_state: Optional[str],
    file_input_list: Optional[List[Any]],
    add_timestamp_checkbox: bool,
    send_thoughts_state: bool,
    api_history_limit_state: str
) -> Tuple[List[List[Optional[str]]], Any, Any, str]:
    print(f"\n--- メッセージ送信処理開始 --- {datetime.datetime.now()} ---")
    error_message = ""
    original_user_text_on_entry = textbox_content.strip() if textbox_content else ""
    image_path = None

    validation_error = _validate_submission_inputs(current_character_name, current_model_name, current_api_key_name_state)
    if validation_error:
        return chatbot_history, gr.update(value=original_user_text_on_entry), gr.update(value=file_input_list), validation_error

    if not current_api_key_name_state:
         return chatbot_history, gr.update(value=original_user_text_on_entry), gr.update(value=file_input_list), "APIキーが選択されていません (内部エラー)。"

    api_configured, api_error_msg = _configure_api_key_if_needed(current_api_key_name_state)
    if not api_configured:
        return chatbot_history, gr.update(value=original_user_text_on_entry), gr.update(value=file_input_list), api_error_msg

    if not current_character_name:
        return chatbot_history, gr.update(value=original_user_text_on_entry), gr.update(value=file_input_list), "キャラクターが選択されていません (内部エラー)。"

    log_f, sys_p, _, mem_p = get_character_files_paths(current_character_name)
    if not all([log_f, sys_p, mem_p]):
        error_message = f"キャラクター '{current_character_name}' の必須ファイル（ログ、プロンプト、記憶）のパス取得に失敗しました。"
        return chatbot_history, gr.update(value=original_user_text_on_entry), gr.update(value=file_input_list), error_message

    user_action_timestamp_str = ""
    if add_timestamp_checkbox and (original_user_text_on_entry or file_input_list):
        now = datetime.datetime.now()
        user_action_timestamp_str = f"\n{now.strftime('%Y-%m-%d (%a) %H:%M:%S')}"

    text_from_files, files_for_gemini_api, file_processing_errors = _process_uploaded_files(file_input_list)
    if file_processing_errors:
        error_message = (error_message + "\n" if error_message else "") + "\n".join(file_processing_errors)

    api_text_arg = original_user_text_on_entry
    if text_from_files:
        api_text_arg = (api_text_arg + "\n" + text_from_files).strip() if api_text_arg else text_from_files.strip()

    try:
        user_header = _get_user_header_from_log(log_f, current_character_name)

        if original_user_text_on_entry.startswith("/gazo "):
            print(f"--- /gazo Debug --- /gazo command detected.")
            initial_image_prompt = original_user_text_on_entry[len("/gazo "):].strip()
            if not initial_image_prompt:
                error_message = "画像生成のプロンプトを指定してください。"
                return chatbot_history, gr.update(value=original_user_text_on_entry), gr.update(value=file_input_list), error_message

            user_gazo_log_text = original_user_text_on_entry
            if add_timestamp_checkbox:
                user_gazo_log_text += user_action_timestamp_str
            save_message_to_log(log_f, user_header, user_gazo_log_text)

            refined_image_prompt = initial_image_prompt
            refinement_issues_notes = ""
            prompt_for_refinement = f"""
**Instruction:** You are a prompt refiner. Your sole task is to refine the following user idea into an effective image generation prompt.
Output *only* the refined prompt itself, with no explanations, conversation, or markdown formatting (like quotes) around it.
If the idea is already a good prompt, output it as is.
**User Idea for Image Generation:**
{initial_image_prompt}
**Refined Prompt:**
"""
            refined_image_prompt_response = send_to_gemini(
                system_prompt_path=sys_p, log_file_path=log_f, user_prompt=prompt_for_refinement,
                selected_model=current_model_name, character_name=current_character_name,
                send_thoughts_to_api=False, api_history_limit_option="0",
                uploaded_file_parts=[], memory_json_path=mem_p
            )
            use_initial_prompt_due_to_refinement_issue = False
            if not refined_image_prompt_response:
                refinement_issues_notes = "(プロンプト絞り込みモデルの応答が空だったため、元のプロンプトを使用します。)"
                use_initial_prompt_due_to_refinement_issue = True
            else:
                stripped_response = refined_image_prompt_response.strip()
                if stripped_response.startswith("エラー:") or stripped_response.startswith("API通信エラー:") or stripped_response.startswith("応答取得エラー"):
                    refinement_issues_notes = f"(プロンプトの自動絞り込み処理でAPIエラーが発生したため、元のプロンプトを使用します。エラー詳細: {stripped_response})"
                    use_initial_prompt_due_to_refinement_issue = True

            if not use_initial_prompt_due_to_refinement_issue:
                temp_cleaned_response_lower = refined_image_prompt_response.strip().lower()
                disqualification_keywords = [
                    "sorry", "unable", "cannot", "instead", "text-based", "description of", "describe",
                    "画像は生成できません", "できません", "申し訳ありません", "画像の説明", "テキストベース",
                    "as an ai language model", "i do not have the capability", "i am a language model",
                    "i'm not able to create images"
                ]
                is_disqualified_by_keyword = any(keyword in temp_cleaned_response_lower for keyword in disqualification_keywords)

                if is_disqualified_by_keyword:
                    refinement_issues_notes = f"(プロンプト絞り込みモデルが非協力的/会話的な応答を返したため、元のプロンプトを使用します。)"
                    use_initial_prompt_due_to_refinement_issue = True
                else:
                    candidate_prompt_str = refined_image_prompt_response.strip()
                    keyword_parts = re.split(r"refined prompt:", candidate_prompt_str, flags=re.IGNORECASE)
                    if len(keyword_parts) > 1: candidate_prompt_str = keyword_parts[-1].strip()
                    if (candidate_prompt_str.startswith('"') and candidate_prompt_str.endswith('"')) or \
                       (candidate_prompt_str.startswith("'") and candidate_prompt_str.endswith("'")):
                        candidate_prompt_str = candidate_prompt_str[1:-1].strip()
                    lines = [line.strip() for line in candidate_prompt_str.splitlines() if line.strip()]
                    final_candidate_from_lines = lines[-1] if lines else ""
                    if candidate_prompt_str.count('\n') == 0 and 0 < len(candidate_prompt_str) < 350:
                         final_candidate_from_lines = candidate_prompt_str

                    max_prompt_len, max_newlines = 400, 2
                    if final_candidate_from_lines and len(final_candidate_from_lines) <= max_prompt_len and final_candidate_from_lines.count('\n') < max_newlines and \
                       not any(keyword in final_candidate_from_lines.lower() for keyword in disqualification_keywords):
                        refined_image_prompt = final_candidate_from_lines
                        if refined_image_prompt == initial_image_prompt: refinement_issues_notes = "(絞り込み後のプロンプトは元のプロンプトと同じです。)"
                    else:
                        # Set notes based on which condition failed
                        use_initial_prompt_due_to_refinement_issue = True
            if use_initial_prompt_due_to_refinement_issue: refined_image_prompt = initial_image_prompt
            if not refined_image_prompt.strip():
                refined_image_prompt = initial_image_prompt
                if not refinement_issues_notes: refinement_issues_notes = "(最終的な絞り込みプロンプトが空または空白のみだったため、元のプロンプトを使用します。)"

            ai_response_parts_for_log = [f"[画像生成に使用されたプロンプト]: {refined_image_prompt}"]
            if refinement_issues_notes and refinement_issues_notes.strip():
                 ai_response_parts_for_log.append(refinement_issues_notes.strip())
            sanitized_base_name = "".join(c if c.isalnum() or c in [' ', '_'] else '' for c in initial_image_prompt[:30]).strip().replace(' ', '_') or "generated_image"
            filename_suggestion = f"{current_character_name}_{sanitized_base_name}"

            image_gen_text_response, image_path = generate_image_with_gemini(prompt=refined_image_prompt, output_image_filename_suggestion=filename_suggestion)
            ui_error_message_for_return = ""
            if image_gen_text_response and image_gen_text_response.strip():
                ai_response_parts_for_log.append(f"[画像モデルからのテキスト]: {image_gen_text_response.strip()}")
            if image_path:
                ai_response_parts_for_log.append(f"[Generated Image: {image_path}]")
            else:
                ai_response_parts_for_log.append("[ERROR]: 画像の生成に失敗しました。")
                ui_error_message_for_return = image_gen_text_response.strip() if image_gen_text_response and image_gen_text_response.strip() else "画像の生成に失敗しました (画像パスが返されませんでした)。"
            save_message_to_log(log_f, f"## {current_character_name}:", "\n".join(filter(None, ai_response_parts_for_log)))
            error_message = ui_error_message_for_return
        else:
            if not api_text_arg.strip() and not files_for_gemini_api:
                error_message = (error_message + "\n" if error_message else "") + "送信するメッセージまたは処理可能なファイルがありません。"
                return chatbot_history, gr.update(value=original_user_text_on_entry), gr.update(value=file_input_list), error_message.strip()
            _log_user_interaction(log_f, user_header, original_user_text_on_entry, text_from_files, files_for_gemini_api, add_timestamp_checkbox, user_action_timestamp_str)
            api_response_text = send_to_gemini(
                system_prompt_path=sys_p, log_file_path=log_f, user_prompt=api_text_arg,
                selected_model=current_model_name, character_name=current_character_name,
                send_thoughts_to_api=send_thoughts_state, api_history_limit_option=api_history_limit_state,
                uploaded_file_parts=files_for_gemini_api, memory_json_path=mem_p
            )
            if api_response_text is not None: print(f"DEBUG_UI_HANDLERS: api_response_text received: '{api_response_text[:500]}' (Length: {len(api_response_text)}, Type: {type(api_response_text)})")
            else: print(f"DEBUG_UI_HANDLERS: api_response_text received is None (Type: {type(api_response_text)})")

            if api_response_text and isinstance(api_response_text, str) and \
               not (api_response_text.strip().startswith("エラー:") or api_response_text.strip().startswith("API通信エラー:") or \
                    api_response_text.strip().startswith("応答取得エラー") or api_response_text.strip().startswith("応答生成失敗")):
                if api_response_text is not None: print(f"DEBUG_UI_HANDLERS: api_response_text before saving to log: '{api_response_text[:500]}' (Length: {len(api_response_text)}, Type: {type(api_response_text)})")
                else: print(f"DEBUG_UI_HANDLERS: api_response_text before saving to log is None (Type: {type(api_response_text)})")
                save_message_to_log(log_f, f"## {current_character_name}:", api_response_text)
            else:
                api_err = api_response_text or "APIから有効な応答がありませんでした。"
                error_message = (error_message + "\n" if error_message else "") + api_err
    except Exception as e:
        traceback.print_exc()
        err_msg = f"メッセージ処理中に予期せぬエラーが発生: {str(e)}"
        error_message = (error_message + "\n" if error_message else "") + err_msg
        return chatbot_history, gr.update(value=original_user_text_on_entry), gr.update(value=file_input_list), error_message.strip()

    new_hist = chatbot_history
    if not error_message or image_path:
        new_log = load_chat_log(log_f, current_character_name)
        print(f"DEBUG_UI_HANDLERS: new_log after load_chat_log (last 5 entries): {new_log[-5:]}")
        new_hist = format_history_for_gradio_wrapper(new_log[-(config_manager.HISTORY_LIMIT * 2):])
    elif original_user_text_on_entry.startswith("/gazo "): # /gazo error
        new_log = load_chat_log(log_f, current_character_name)
        print(f"DEBUG_UI_HANDLERS: new_log after load_chat_log (in /gazo error path, last 5 entries): {new_log[-5:]}")
        new_hist = format_history_for_gradio_wrapper(new_log[-(config_manager.HISTORY_LIMIT * 2):])

    return new_hist, gr.update(value=""), gr.update(value=None), error_message.strip()

# --- Custom Wrapper for format_history_for_gradio ---
FILE_CONTENT_HEADER_PATTERN = r"--- 添付ファイル「(.*?)」の内容 ---.*"
ATTACHED_IMAGE_PATTERN = r"\[ファイル添付: (.*?);(.*?);(image/(?:png|jpeg|gif|webp))\]"
GENERATED_IMAGE_PATTERN = r"\[Generated Image: (.*?(?:png|jpeg|gif|webp))\]"
TH_PAT_LOCAL = re.compile(r"【Thoughts】.*?【/Thoughts】\s*", re.DOTALL | re.IGNORECASE)
HTML_TH_PAT_LOCAL = re.compile(r"<div class='thoughts'>\s*<pre>\s*<code>.*?</code>\s*</pre>\s*</div>\s*", re.DOTALL | re.IGNORECASE)

def _sanitize_alt_text(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub(r'[\`*_{}\[\]()#+-.!]', '', text)

def _replace_path_for_gradio(path: Optional[str]) -> str:
    if not path:
        return ""
    return f"/file={urllib.parse.quote(path, safe=' /')}"

def format_history_for_gradio_wrapper(chat_log_from_utils: List[Dict[str, str]]) -> List[List[Optional[str]]]:
    formatted_history_input = original_format_history_for_gradio(chat_log_from_utils)
    if not formatted_history_input:
        print("DEBUG_FORMAT_WRAPPER: Starting. Input is empty.")
        return []
    print(f"DEBUG_FORMAT_WRAPPER: Starting. Input (last 3 pairs): {formatted_history_input[-3:]}")

    processed_history_output = []
    for i, message_pair in enumerate(formatted_history_input):
        if not (isinstance(message_pair, (list, tuple)) and len(message_pair) == 2):
            print(f"DEBUG_FORMAT_WRAPPER: Entry {i} is not a valid pair, skipping: {message_pair}")
            processed_history_output.append(message_pair)
            continue

        user_message, assistant_message_initial = message_pair

        final_user_message = user_message
        if isinstance(user_message, str):
            current_processing_segment = user_message
            modified_segment_step1_user = re.sub(FILE_CONTENT_HEADER_PATTERN, r"添付ファイル: \1", current_processing_segment, flags=re.DOTALL)
            current_processing_segment = modified_segment_step1_user
            modified_segment_step2_user = re.sub(ATTACHED_IMAGE_PATTERN, lambda m: f"![\{_sanitize_alt_text(m.group(2))}]({_replace_path_for_gradio(m.group(1))})", current_processing_segment)
            current_processing_segment = modified_segment_step2_user
            modified_segment_step3_user = re.sub(GENERATED_IMAGE_PATTERN, lambda m: f"![generated_image]({_replace_path_for_gradio(m.group(1))})", current_processing_segment)
            final_user_message = modified_segment_step3_user

        final_assistant_message = assistant_message_initial
        if isinstance(assistant_message_initial, str) and assistant_message_initial.strip():
            print(f"DEBUG_FORMAT_WRAPPER: Entry {i} - Initial assistant_message: '{assistant_message_initial[:200]}...'")
            current_processing_for_assistant = assistant_message_initial

            had_thought_log = bool(TH_PAT_LOCAL.search(assistant_message_initial) or HTML_TH_PAT_LOCAL.search(assistant_message_initial))
            print(f"DEBUG_FORMAT_WRAPPER: Entry {i} - Had thought log pattern matched: {had_thought_log}")

            temp_message_after_th = TH_PAT_LOCAL.sub("", current_processing_for_assistant).strip()
            # print(f"DEBUG_FORMAT_WRAPPER: Entry {i} - After TH_PAT_LOCAL removal: '{temp_message_after_th[:200]}...'")
            current_processing_for_assistant = temp_message_after_th

            message_after_all_thought_removal = HTML_TH_PAT_LOCAL.sub("", current_processing_for_assistant).strip()
            print(f"DEBUG_FORMAT_WRAPPER: Entry {i} - After ALL thought_log removal (HTML_TH_PAT_LOCAL on result of TH_PAT_LOCAL): '{message_after_all_thought_removal[:200]}...'")

            if had_thought_log and not message_after_all_thought_removal:
                final_assistant_message = "（思考ログのみで、応答本文はありませんでした）"
                print(f"DEBUG_FORMAT_WRAPPER: Entry {i} - Assistant message was only thought logs. Replaced with placeholder: '{final_assistant_message}'")
            else:
                current_processing_segment = message_after_all_thought_removal
                print(f"DEBUG_FORMAT_WRAPPER: Entry {i} (Assistant) - Segment initial for common processing: '{current_processing_segment[:200]}...' (This is after thought log removal, or original if no thoughts)")

                original_segment_for_warning_check = current_processing_segment

                modified_segment_step1_assistant = re.sub(FILE_CONTENT_HEADER_PATTERN, r"添付ファイル: \1", current_processing_segment, flags=re.DOTALL)
                if current_processing_segment != modified_segment_step1_assistant: print(f"DEBUG_FORMAT_WRAPPER: Entry {i} (Assistant) - After FILE_CONTENT_HEADER_PATTERN: '{modified_segment_step1_assistant[:200]}...'")
                if original_segment_for_warning_check.strip() and not modified_segment_step1_assistant.strip() and "--- 添付ファイル「" in original_segment_for_warning_check : print(f"DEBUG_FORMAT_WRAPPER: WARNING! Entry {i} (Assistant) - Segment became EMPTY after FILE_CONTENT_HEADER_PATTERN.")
                current_processing_segment = modified_segment_step1_assistant

                modified_segment_step2_assistant = re.sub(ATTACHED_IMAGE_PATTERN, lambda m: f"![\{_sanitize_alt_text(m.group(2))}]({_replace_path_for_gradio(m.group(1))})", current_processing_segment)
                if current_processing_segment != modified_segment_step2_assistant: print(f"DEBUG_FORMAT_WRAPPER: Entry {i} (Assistant) - After ATTACHED_IMAGE_PATTERN: '{modified_segment_step2_assistant[:200]}...'")
                if current_processing_segment.strip() and not modified_segment_step2_assistant.strip() and "[ファイル添付:" in current_processing_segment : print(f"DEBUG_FORMAT_WRAPPER: WARNING! Entry {i} (Assistant) - Segment became EMPTY after ATTACHED_IMAGE_PATTERN.")
                current_processing_segment = modified_segment_step2_assistant

                modified_segment_step3_assistant = re.sub(GENERATED_IMAGE_PATTERN, lambda m: f"![generated_image]({_replace_path_for_gradio(m.group(1))})", current_processing_segment)
                if current_processing_segment != modified_segment_step3_assistant: print(f"DEBUG_FORMAT_WRAPPER: Entry {i} (Assistant) - After GENERATED_IMAGE_PATTERN: '{modified_segment_step3_assistant[:200]}...'")
                if current_processing_segment.strip() and not modified_segment_step3_assistant.strip() and "[Generated Image:" in current_processing_segment: print(f"DEBUG_FORMAT_WRAPPER: WARNING! Entry {i} (Assistant) - Segment became EMPTY after GENERATED_IMAGE_PATTERN.")
                final_assistant_message = modified_segment_step3_assistant # Corrected assignment

                print(f"DEBUG_FORMAT_WRAPPER: Entry {i} (Assistant) - Final value for segment after common processing: '{final_assistant_message[:200]}...'")

        elif assistant_message_initial is None:
            print(f"DEBUG_FORMAT_WRAPPER: Entry {i} - Initial assistant_message was None.")
            final_assistant_message = None
        else:
            print(f"DEBUG_FORMAT_WRAPPER: Entry {i} - Initial assistant_message was empty or whitespace: '{assistant_message_initial}' Type: {type(assistant_message_initial)}")
            final_assistant_message = assistant_message_initial

        processed_history_output.append([final_user_message, final_assistant_message])

    if not processed_history_output:
        print("DEBUG_FORMAT_WRAPPER: Output is empty.")
        return []
    print(f"DEBUG_FORMAT_WRAPPER: Final processed_history_output (last 3 pairs): {processed_history_output[-3:]}")
    return processed_history_output

def update_ui_on_character_change(
    character_name: Optional[str]
) -> Tuple[Optional[str], Any, Any, Any, Any, Optional[str]]:
    if not character_name:
        gr.Info("キャラクターが選択されていません。")
        return (
            None, gr.update(value=[]), gr.update(value=""),
            gr.update(value=None), gr.update(value="{}"), gr.update(value=None)
        )

    print(f"UI更新: キャラクター変更 -> '{character_name}'")
    config_manager.save_config("last_character", character_name)
    log_f, _, img_p, mem_p = get_character_files_paths(character_name)

    chat_history_display = []
    if log_f and os.path.exists(log_f):
        chat_history_for_gradio = format_history_for_gradio_wrapper(
            load_chat_log(log_f, character_name)[-(config_manager.HISTORY_LIMIT * 2):]
        )
        chat_history_display = chat_history_for_gradio
    else:
        gr.Warning(f"キャラクター '{character_name}' のログファイルが見つかりません: {log_f}")

    memory_data = load_memory_data_safe(mem_p)
    memory_display_str = json.dumps(memory_data, indent=2, ensure_ascii=False) \
                         if isinstance(memory_data, dict) else \
                         json.dumps({"error": "記憶データの読み込みまたは解析に失敗しました。"}, indent=2)

    return (
        character_name, gr.update(value=chat_history_display), gr.update(value=""),
        gr.update(value=img_p if img_p and os.path.exists(img_p) else None),
        gr.update(value=memory_display_str), gr.update(value=character_name)
    )

def update_model_state(selected_model: Optional[str]) -> Union[Optional[str], Any]:
    if selected_model is None: return gr.update()
    print(f"設定更新: モデル変更 -> '{selected_model}'")
    config_manager.save_config("last_model", selected_model)
    return selected_model

def update_api_key_state(selected_api_key_name: Optional[str]) -> Union[Optional[str], Any]:
    if not selected_api_key_name: return gr.update()
    print(f"設定更新: APIキー変更 -> '{selected_api_key_name}'")
    ok, msg = configure_google_api(selected_api_key_name)
    config_manager.save_config("last_api_key_name", selected_api_key_name)
    if hasattr(config_manager, 'initial_api_key_name_global'):
         config_manager.initial_api_key_name_global = selected_api_key_name
    else:
        print("警告: config_manager.initial_api_key_name_global が見つかりません。")
    if ok: gr.Info(f"APIキー '{selected_api_key_name}' の設定に成功しました。")
    else: gr.Error(f"APIキー '{selected_api_key_name}' の設定に失敗しました: {msg}")
    return selected_api_key_name

def update_timestamp_state(add_timestamp_checked: bool) -> None:
    if isinstance(add_timestamp_checked, bool):
        print(f"設定更新: タイムスタンプ付加設定 -> {add_timestamp_checked}")
        config_manager.save_config("add_timestamp", add_timestamp_checked)
    else:
        gr.Warning(f"タイムスタンプ設定の更新に失敗しました。無効な値: {add_timestamp_checked}")
    return None

def update_send_thoughts_state(send_thoughts_checked: bool) -> Union[bool, Any]:
    if not isinstance(send_thoughts_checked, bool):
        gr.Warning(f"「思考過程を送信」設定の更新に失敗しました。無効な値: {send_thoughts_checked}")
        return gr.update()
    print(f"設定更新: 思考過程API送信設定 -> {send_thoughts_checked}")
    config_manager.save_config("last_send_thoughts_to_api", send_thoughts_checked)
    return send_thoughts_checked

def update_api_history_limit_state(selected_limit_option_ui_value: Optional[str]) -> Union[str, Any]:
    if not selected_limit_option_ui_value:
        gr.Warning("API履歴制限が選択されていません。")
        return gr.update()
    internal_key = next(
        (k for k, v in config_manager.API_HISTORY_LIMIT_OPTIONS.items() if v == selected_limit_option_ui_value), None
    )
    if internal_key:
        print(f"設定更新: API履歴制限 -> '{internal_key}' (UI表示: '{selected_limit_option_ui_value}')")
        config_manager.save_config("last_api_history_limit_option", internal_key)
        return internal_key
    else:
        gr.Error(f"無効なAPI履歴制限オプションが選択されました: '{selected_limit_option_ui_value}'")
        return gr.update()

def reload_chat_log(character_name: Optional[str]) -> List[List[Optional[str]]]:
    if not character_name:
        gr.Info("ログ再読み込み: キャラクターが選択されていません。")
        return []
    log_file_path, _, _, _ = get_character_files_paths(character_name)
    if not log_file_path or not os.path.exists(log_file_path):
        gr.Warning(f"ログ再読み込み: キャラクター '{character_name}' のログファイルが見つかりません ({log_file_path})。")
        return []
    print(f"UI操作: '{character_name}' のチャットログを再読み込みします。")
    chat_log_for_display = format_history_for_gradio_wrapper(
        load_chat_log(log_file_path, character_name)[-(config_manager.HISTORY_LIMIT * 2):]
    )
    gr.Info(f"'{character_name}' のチャットログを再読み込みしました。")
    return chat_log_for_display

def handle_timer_submission(
    timer_type: str, duration: Optional[float],
    work_duration: Optional[float], break_duration: Optional[float], cycles: Optional[int],
    current_character_name: Optional[str],
    work_theme: Optional[str], break_theme: Optional[str],
    api_key_name: Optional[str], webhook_url: Optional[str], normal_timer_theme: Optional[str]
) -> None:
    if not current_character_name:
        gr.Error("キャラクターが選択されていません。タイマーを設定するにはキャラクターを選択してください。")
        return
    if not api_key_name:
        gr.Error("APIキーが選択されていません。タイマー通知のためにAPIキーを選択してください。")
        return
    if timer_type == "通常タイマー":
        if duration is None or duration <= 0:
            gr.Error("通常タイマーの時間を正しく入力してください（0より大きい値）。")
            return
    elif timer_type == "ポモドーロタイマー":
        if not (work_duration and work_duration > 0 and break_duration and break_duration > 0 and cycles and cycles > 0):
            gr.Error("ポモドーロタイマーの作業時間、休憩時間、サイクル数を正しく入力してください（全て0より大きい値）。")
            return
    else:
        gr.Error(f"不明なタイマータイプです: {timer_type}")
        return

    print(f"タイマー設定実行: タイプ='{timer_type}', キャラクター='{current_character_name}', 作業テーマ='{work_theme}', 休憩テーマ='{break_theme}', 通常テーマ='{normal_timer_theme}'")
    try:
        unified_timer = UnifiedTimer(
            timer_type=timer_type,
            duration=duration if duration is not None else 0,
            work_duration=work_duration if work_duration is not None else 0,
            break_duration=break_duration if break_duration is not None else 0,
            cycles=cycles if cycles is not None else 0,
            character_name=current_character_name,
            work_theme=work_theme or "作業終了です！",
            break_theme=break_theme or "休憩終了！作業を再開しましょう。",
            api_key_name=api_key_name,
            webhook_url=webhook_url,
            normal_timer_theme=normal_timer_theme or "時間になりました！"
        )
        unified_timer.start()
        gr.Info(f"{timer_type}を開始しました。")
    except Exception as e:
        gr.Error(f"タイマーの開始中にエラーが発生しました: {str(e)}")
        traceback.print_exc()
