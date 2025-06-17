# utils.py (最終・完全・確定版)
import os
import re
import traceback
import html
from typing import List, Dict, Optional, Tuple, Union
# import gradio as gr # Not strictly needed in this file based on the functions provided

def load_chat_log(file_path: str, character_name: str) -> List[Dict[str, str]]:
    messages: List[Dict[str, str]] = []
    if not character_name: # Added check for character_name as good practice
        print("エラー: load_chat_log - character_name が指定されていません。")
        return messages # Return empty if no character name
    if not file_path or not os.path.exists(file_path):
        # print(f"情報: ログファイル '{file_path}' が見つかりません。空の履歴を返します。") # Less alarming
        return messages

    # Construct headers based on the provided character_name
    ai_header = f"## {character_name}:"
    user_header_default = "## ユーザー:" # Default if no specific user header found
    alarm_header = "## システム(アラーム):" # As defined by user

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        print(f"エラー: ログファイル '{file_path}' の読み込み中にエラー: {e}")
        traceback.print_exc()
        return messages

    current_role: Optional[str] = None
    current_text_lines: List[str] = []

    for line in lines:
        stripped_line = line.strip()

        if stripped_line.startswith("## ") and stripped_line.endswith(":"):
            # Save previous message block
            if current_role and current_text_lines:
                messages.append({"role": current_role, "content": "\n".join(current_text_lines).strip()})
            current_text_lines = [] # Reset for new block

            # Determine role
            if stripped_line == ai_header:
                current_role = "model"
            elif stripped_line == alarm_header: # System (alarm) messages treated as user for display
                current_role = "user"
            else: # Any other "## Header:" is considered user
                current_role = "user"
        elif current_role: # Only append if we are currently inside a role block
            current_text_lines.append(line.rstrip('\n'))

    # Add the last message block if any
    if current_role and current_text_lines:
        messages.append({"role": current_role, "content": "\n".join(current_text_lines).strip()})

    return messages

def format_response_for_display(response_text: Optional[str]) -> str:
    if not response_text: return ""
    # Using re.IGNORECASE for 【Thoughts】 as well, and making it non-greedy
    thoughts_pattern = re.compile(r"【Thoughts】(.*?)【/Thoughts】", re.DOTALL | re.IGNORECASE)
    match = thoughts_pattern.search(response_text)
    if match:
        thoughts_content = match.group(1).strip()
        # Escape HTML special characters in thoughts content
        escaped_content = html.escape(thoughts_content)
        # Convert newlines to <br> for HTML display
        content_with_breaks = escaped_content.replace('\n', '<br>').replace('\r\n', '<br>') # Handle literal \r\n and actual newlines
        thought_html_block = f"<details class='thoughts_details'><summary>思考</summary><div class='thoughts_content'>{content_with_breaks}</div></details>"

        main_response_text = thoughts_pattern.sub("", response_text).strip()
        # Return only the main response if thoughts were just for logging/internal
        # Or, if they are meant to be displayed:
        return f"{thought_html_block}\n\n{main_response_text}" if main_response_text else thought_html_block
    else:
        return response_text.strip() # Return stripped original if no thoughts

def format_history_for_gradio(messages: List[Dict[str, str]]) -> List[Dict[str, Union[str, tuple, None]]]:
    """チャットログをGradio Chatbotの `messages` 形式に変換する（ファイル表示エラー修正版）。"""
    if not messages: return []
    gradio_history = []
    image_tag_pattern = re.compile(r"\[Generated Image: (.*?)\]")
    user_file_attach_pattern = re.compile(r"\[ファイル添付: (.*?)\]")

    for msg in messages:
        role = "assistant" if msg.get("role") == "model" else "user"
        content = msg.get("content", "").strip()
        if not content: continue

        if role == "user":
            file_matches = list(user_file_attach_pattern.finditer(content))
            text_part = user_file_attach_pattern.sub("", content).strip()
            if text_part: # Only add if there's actual text
                gradio_history.append({"role": role, "content": text_part})

            if file_matches:
                for match in file_matches: # Iterate in case multiple files mentioned this way
                    file_path_in_log = match.group(1).strip()
                    file_name = os.path.basename(file_path_in_log)
                    file_info_text = f"📎 **添付ファイル:** {file_name}"
                    gradio_history.append({"role": role, "content": file_info_text})
            continue

        if role == "assistant":
            formatted_content = format_response_for_display(content) # Apply thought formatting
            image_match = image_tag_pattern.search(formatted_content)
            if image_match:
                text_before_image = formatted_content[:image_match.start()].strip()
                image_path_in_log = image_match.group(1).strip()
                image_filename = os.path.basename(image_path_in_log)
                text_after_image = formatted_content[image_match.end():].strip()

                if text_before_image:
                    gradio_history.append({"role": role, "content": text_before_image})

                if os.path.exists(image_path_in_log):
                    gradio_history.append({"role": role, "content": (image_path_in_log, image_filename)})
                else:
                    gradio_history.append({"role": role, "content": f"*[表示エラー: 画像 '{image_filename}' が見つかりません (パス: {image_path_in_log})]*"})

                if text_after_image: # Append text after image if it exists
                     gradio_history.append({"role": role, "content": text_after_image})
            else:
                gradio_history.append({"role": role, "content": formatted_content})
            continue

    return gradio_history

def save_message_to_log(log_file_path: str, header: str, text_content: str) -> None:
    if not log_file_path or not header: # Allow empty text_content for just headers? User code implies not.
        # If text_content can be empty, the check `not text_content or not text_content.strip()` is important.
        # For now, assuming text_content must be non-empty and non-whitespace.
        # print(f"Debug: save_message_to_log called with log_file_path='{log_file_path}', header='{header}', text_content is empty/whitespace.")
        if not text_content or not text_content.strip():
             return

    try:
        needs_newline = False
        if os.path.exists(log_file_path) and os.path.getsize(log_file_path) > 0:
            try: # Nested try for file operations
                with open(log_file_path, "rb") as f:
                    f.seek(-1, os.SEEK_END) # Go to the second last byte.
                    if f.read(1) != b'\n':
                        needs_newline = True
            except OSError: # Handle cases like empty file where seek might fail
                 pass # No newline needed if file is empty or seek fails

        with open(log_file_path, "a", encoding="utf-8") as f:
            if needs_newline:
                f.write("\n")
            f.write(f"{header}\n\n{text_content.strip()}\n\n")
    except Exception as e:
        print(f"エラー: ログファイル '{log_file_path}' への書き込み中にエラー: {e}")
        traceback.print_exc()

def _get_user_header_from_log(log_file_path: str, ai_character_name: str) -> str:
    default_user_header = "## ユーザー:"
    if not ai_character_name: # Should not happen if called correctly
        return default_user_header

    ai_response_header = f"## {ai_character_name}:"
    system_alarm_header = "## システム(アラーム):" # As defined by user for alarm messages

    if not log_file_path or not os.path.exists(log_file_path):
        return default_user_header

    last_user_header = default_user_header # Initialize with default
    try:
        with open(log_file_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                # Check if it's a header, and not AI's or System's header
                if stripped.startswith("## ") and stripped.endswith(":") and \
                   stripped != ai_response_header and stripped != system_alarm_header:
                    last_user_header = stripped
        return last_user_header
    except Exception as e:
        print(f"エラー: ユーザーヘッダー取得のためログファイル読込中にエラー: {e}")
        traceback.print_exc()
        return default_user_header
