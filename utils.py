# -*- coding: utf-8 -*-
import os
import re
import traceback
from typing import List, Dict, Optional, Tuple, Union
import json # Added json import as it's used in load_chat_log

# It's good practice to avoid direct imports of other major app modules like character_manager
# in a low-level module like utils.py if possible, to prevent circular dependencies.
# If character_manager.get_character_files_paths is needed by save_log_file,
# it should ideally be passed as an argument or character_name itself is enough.
# For now, I will keep it as Kiseki's ui_handlers.py implied its usage.
import character_manager


def load_chat_log(log_file_path: str, character_name: Optional[str] = "Unknown Character") -> List[Dict[str, str]]:
    """チャットログファイルを読み込み、roleとcontentの辞書のリストとして返します。"""
    messages = []
    if not os.path.exists(log_file_path):
        return messages
    try:
        with open(log_file_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                return messages

            if content.startswith('[') and content.endswith(']'):
                try:
                    json_messages = json.loads(content)
                    if isinstance(json_messages, list) and all(isinstance(m, dict) and 'role' in m and 'content' in m for m in json_messages):
                        for msg_item in json_messages:
                            role = msg_item['role']
                            if role not in ["user", "model"]:
                                role = "model"
                            messages.append({"role": role, "content": msg_item['content']})
                        return messages
                except json.JSONDecodeError:
                    pass

            line_pattern = re.compile(r"^(User|##.+?):([\s\S]*?)(?=(^User:|^##.+?:|\Z))", re.MULTILINE)
            current_log_content = ""
            with open(log_file_path, 'r', encoding='utf-8') as f_log: # Re-open to read fresh
                current_log_content = f_log.read()

            for match in line_pattern.finditer(current_log_content):
                role_tag = match.group(1).strip()
                content_match = match.group(2).strip()
                role = "user" if role_tag == "User" else "model"
                messages.append({"role": role, "content": content_match})

        return messages
    except Exception as e:
        print(f"チャットログの読み込み中にエラーが発生しました ({log_file_path}): {e}\n{traceback.format_exc()}")
        return []


def save_message_to_log(log_file_path: str, role_or_header: str, message: str):
    """メッセージをログファイルに追記します。"""
    try:
        os.makedirs(os.path.dirname(log_file_path), exist_ok=True) # Ensure directory exists
        with open(log_file_path, 'a', encoding='utf-8') as f:
            f.write(f"{role_or_header} {message}\n\n")
    except Exception as e:
        print(f"ログへのメッセージ保存中にエラーが発生しました ({log_file_path}): {e}\n{traceback.format_exc()}")

def _get_user_header_from_log(log_file_path: str, default_user_name: str = "User") -> str:
    """ログファイルからユーザーヘッダーを特定します。なければデフォルトを使用します。"""
    try:
        if os.path.exists(log_file_path):
            with open(log_file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith("User:") or line.startswith(default_user_name + ":"):
                        return line.split(":")[0].strip() + ":"
    except Exception as e:
        print(f"ユーザーヘッダーの取得中にエラー: {e}")
    return default_user_name + ":"

def save_log_file(character_name: str, log_content: str):
    """チャットログ全体を保存します。"""
    # This function directly uses character_manager. It's a dependency.
    log_file_path, _, _, _ = character_manager.get_character_files_paths(character_name)
    if not log_file_path:
        raise ValueError(f"キャラクター '{character_name}' のログファイルパスが見つかりません。")
    try:
        os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
        with open(log_file_path, 'w', encoding='utf-8') as f:
            f.write(log_content)
    except Exception as e:
        raise IOError(f"ログファイル '{log_file_path}' の保存中にエラー: {e}")


def format_history_for_gradio(messages: List[Dict[str, str]]) -> List[Dict[str, Union[str, tuple, None]]]:
    """
    チャットログをGradio Chatbotの新しい `messages` 形式に変換します。
    戻り値: [{'role': 'user'/'assistant', 'content': str | tuple | None}, ...]
    """
    if not messages:
        return []

    gradio_history = []
    for msg in messages:
        role = "assistant" if msg.get("role") == "model" else "user"
        content = msg.get("content", "")

        image_tag_pattern = re.compile(r"\[Generated Image: (.*?)\]")

        parts = []
        last_end = 0
        contains_image = False

        for match in image_tag_pattern.finditer(content):
            contains_image = True
            text_before_image = content[last_end:match.start()].strip()
            if text_before_image:
                parts.append({"type": "text", "text": text_before_image})

            image_path = match.group(1).strip()
            if os.path.exists(image_path): # Check if image path is valid
                parts.append({"type": "image", "path": image_path, "alt": "Generated Image"})
            else: # Image path is invalid
                parts.append({"type": "text", "text": f"*[表示エラー: 画像 '{image_path}' が見つかりません]*"})
            last_end = match.end()

        remaining_text = content[last_end:].strip()
        if remaining_text:
            parts.append({"type": "text", "text": remaining_text})

        if not contains_image and content: # If no images, and content exists, it's all text
            parts.append({"type": "text", "text": content})

        if not parts and not content: # Handle truly empty messages (e.g. if a user sends only an image that fails to process)
             gradio_history.append({"role": role, "content": None})
             continue

        for part_data in parts:
            if part_data["type"] == "text":
                gradio_history.append({"role": role, "content": part_data["text"]})
            elif part_data["type"] == "image":
                # Gradio Chatbot `messages` format expects image content as a tuple: (filepath, alt_text)
                gradio_history.append({"role": role, "content": (part_data["path"], part_data["alt"])})

    return gradio_history
