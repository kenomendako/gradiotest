# utils.py の修正版コード

import os
import re
import traceback
import html
from typing import List, Dict, Optional, Tuple, Union
import gradio as gr

def load_chat_log(file_path: str, character_name: str) -> List[Dict[str, str]]:
    messages: List[Dict[str, str]] = []
    if not character_name:
        print("エラー: load_chat_log - character_name が指定されていません。")
        return messages
    if not file_path:
        print("エラー: load_chat_log - file_path が指定されていません。")
        return messages
    if not os.path.exists(file_path):
        return messages

    ai_header = f"## {character_name}:"
    alarm_header = "## システム(アラーム):"

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        print(f"エラー: ログファイル '{file_path}' の読み込み中に予期せぬエラーが発生しました: {e}")
        traceback.print_exc()
        return messages

    current_role: Optional[str] = None
    current_text_lines: List[str] = []

    for line in lines:
        stripped_line = line.strip()
        if stripped_line.startswith("## ") and stripped_line.endswith(":"):
            if current_role and current_text_lines:
                messages.append({"role": current_role, "content": "\n".join(current_text_lines).strip()})
            current_text_lines = []
            if stripped_line == ai_header:
                current_role = "model"
            elif stripped_line == alarm_header:
                current_role = "user"
            else:
                current_role = "user"
        elif current_role:
            current_text_lines.append(line.rstrip('\n'))

    if current_role and current_text_lines:
        messages.append({"role": current_role, "content": "\n".join(current_text_lines).strip()})

    return messages

def format_response_for_display(response_text: Optional[str]) -> str:
    if not response_text: return ""
    thoughts_pattern = re.compile(r"【Thoughts】(.*?)【/Thoughts】", re.DOTALL | re.IGNORECASE)
    match = thoughts_pattern.search(response_text)
    if match:
        thoughts_content = match.group(1).strip()
        escaped_content = html.escape(thoughts_content)
        content_with_breaks = escaped_content.replace('\n', '<br>')
        thought_html_block = f"<div class='thoughts'>{content_with_breaks}</div>"
        main_response_text = thoughts_pattern.sub("", response_text).strip()
        return f"{thought_html_block}\n\n{main_response_text}" if main_response_text else thought_html_block
    else:
        return response_text.strip()

    # utils.py
    # (Ensure os and re are imported)
    import os
    import re
    from typing import List, Dict, Union # Keep existing typing imports

    # Assume format_response_for_display is defined elsewhere in utils.py or imported
    # For context, here's a placeholder if it's simple:
    # def format_response_for_display(text: str) -> str:
    #     # This is just an example; use the actual function if it exists
    #     return text.replace("【Thoughts】", "<details><summary>思考</summary><p>") \
    #                .replace("【/Thoughts】", "</p></details>")

    def format_history_for_gradio(messages: List[Dict[str, str]]) -> List[Dict[str, Union[str, tuple, None]]]:
        """チャットログをGradio Chatbotの `messages` 形式に変換する（ファイル表示エラー修正版）。"""
        if not messages: return []
        gradio_history = []
        # Corrected regex to be more robust for paths that might contain spaces or special chars
        # This regex assumes the path is the last part of the tag.
        image_tag_pattern = re.compile(r"\[Generated Image: (.*?)\]")
        user_file_attach_pattern = re.compile(r"\[ファイル添付: (.*?)\]")

        for msg in messages:
            role = "assistant" if msg.get("role") == "model" else "user"
            content = msg.get("content", "").strip()
            if not content: continue

            if role == "user":
                # Process all file attachments first
                file_matches = list(user_file_attach_pattern.finditer(content))
                text_part = user_file_attach_pattern.sub("", content).strip() # Remove all file tags

                # Append text part first if it exists
                if text_part:
                    gradio_history.append({"role": role, "content": text_part})

                # Then append file attachment info as separate text messages
                if file_matches:
                    for match in file_matches:
                        # Strip potential leading/trailing whitespace from the matched path
                        file_path_in_log = match.group(1).strip()
                        file_name = os.path.basename(file_path_in_log)
                        file_info_text = f"📎 **添付ファイル:** {file_name}"
                        # Add as a new user message to ensure it appears on a new line
                        gradio_history.append({"role": role, "content": file_info_text})
                continue # Finished processing user message

            if role == "assistant":
                # Use the existing format_response_for_display function
                formatted_content = format_response_for_display(content)

                # Handle potential image tag
                image_match = image_tag_pattern.search(formatted_content)
                if image_match:
                    text_before_image = formatted_content[:image_match.start()].strip()

                    # Strip potential leading/trailing whitespace from the matched path
                    image_path_in_log = image_match.group(1).strip()
                    image_filename = os.path.basename(image_path_in_log) # Get just the filename

                    text_after_image = formatted_content[image_match.end():].strip()

                    if text_before_image:
                        gradio_history.append({"role": role, "content": text_before_image})

                    # Check if the image file actually exists at the path specified in the log
                    if os.path.exists(image_path_in_log):
                        # Gradio expects (filepath, alt_text) for images
                        gradio_history.append({"role": role, "content": (image_path_in_log, image_filename)})
                    else:
                        # Display an error message if the image path from the log is not found
                        gradio_history.append({"role": role, "content": f"*[表示エラー: 画像 '{image_filename}' が見つかりません (パス: {image_path_in_log})]*"})

                    if text_after_image:
                         gradio_history.append({"role": role, "content": text_after_image})
                else:
                    # No image tag, just add the formatted text content
                    gradio_history.append({"role": role, "content": formatted_content})
                continue # Finished processing assistant message

        return gradio_history

def save_message_to_log(log_file_path: str, header: str, text_content: str) -> None:
    if not log_file_path:
        print("エラー: save_message_to_log - log_file_path が指定されていません。")
        return
    if not header:
        print("エラー: save_message_to_log - header が指定されていません。")
        return
    if not text_content or not text_content.strip():
        return

    try:
        needs_leading_newline = False
        if os.path.exists(log_file_path) and os.path.getsize(log_file_path) > 0:
            try:
                with open(log_file_path, "rb") as f:
                    f.seek(-1, os.SEEK_END)
                    if f.read(1) != b'\n':
                        needs_leading_newline = True
            except IOError:
                print(f"警告: ログファイル '{log_file_path}' の最終バイト確認中にエラー。")
                needs_leading_newline = True

        with open(log_file_path, "a", encoding="utf-8") as f:
            if needs_leading_newline:
                f.write("\n")
            f.write(f"{header}\n\n{text_content.strip()}\n\n")

    except Exception as e:
        print(f"エラー: ログファイル '{log_file_path}' への書き込み中に予期せぬエラーが発生しました: {e}")
        traceback.print_exc()

def _get_user_header_from_log(log_file_path: str, ai_character_name: str) -> str:
    default_user_header = "## ユーザー:"
    ai_response_header = f"## {ai_character_name}:"
    system_alarm_header = "## システム(アラーム):"

    if not log_file_path or not os.path.exists(log_file_path):
        return default_user_header

    last_identified_user_header = default_user_header
    try:
        with open(log_file_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped_line = line.strip()
                if stripped_line.startswith("## ") and stripped_line.endswith(":"):
                    if stripped_line != ai_response_header and stripped_line != system_alarm_header:
                        last_identified_user_header = stripped_line
        return last_identified_user_header
    except Exception as e:
        print(f"エラー: ユーザーヘッダー取得のためログファイル '{log_file_path}' 読み込み中に予期せぬエラー: {e}")
        traceback.print_exc()
        return default_user_header

