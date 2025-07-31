# utils.py を、この最終確定版コードで完全に置き換えてください

import os
import re
import traceback
import html
from typing import List, Dict, Optional, Tuple, Union
import gradio as gr
import character_manager
import sys
import psutil
from pathlib import Path
import json
import time
import uuid

_model_token_limits_cache: Dict[str, Dict[str, int]] = {}
LOCK_FILE_PATH = Path.home() / ".nexus_ark.global.lock"

def acquire_lock() -> bool:
    print("--- グローバル・ロックの取得を試みます ---")
    try:
        if not LOCK_FILE_PATH.exists():
            _create_lock_file()
            print("--- ロックを取得しました (新規作成) ---")
            return True
        with open(LOCK_FILE_PATH, "r", encoding="utf-8") as f:
            lock_info = json.load(f)
        pid = lock_info.get('pid')
        if pid and psutil.pid_exists(pid):
            print("\n" + "="*60)
            print("!!! エラー: Nexus Arkの別プロセスが既に実行中です。")
            print(f"    - 実行中のPID: {pid}")
            print(f"    - パス: {lock_info.get('path', '不明')}")
            print("    多重起動はできません。既存のプロセスを終了するか、")
            print("    タスクマネージャーからプロセスを強制終了してください。")
            print("="*60 + "\n")
            return False
        else:
            print("\n" + "!"*60)
            print("警告: 古いロックファイルを検出しました。")
            print(f"  - 記録されていたPID: {pid or '不明'} (このプロセスは現在実行されていません)")
            print("  古いロックファイルを自動的に削除して、処理を続行します。")
            print("!"*60 + "\n")
            LOCK_FILE_PATH.unlink()
            time.sleep(0.5)
            _create_lock_file()
            print("--- ロックを取得しました (自動クリーンアップ後) ---")
            return True
    except (json.JSONDecodeError, IOError) as e:
        print(f"警告: ロックファイル '{LOCK_FILE_PATH}' が破損しているようです。エラー: {e}")
        print("破損したロックファイルを削除して、処理を続行します。")
        try:
            LOCK_FILE_PATH.unlink()
            time.sleep(0.5)
            _create_lock_file()
            print("--- ロックを取得しました (破損ファイル削除後) ---")
            return True
        except Exception as delete_e:
            print(f"!!! エラー: 破損したロックファイルの削除に失敗しました: {delete_e}")
            return False
    except Exception as e:
        print(f"!!! エラー: ロック処理中に予期せぬ問題が発生しました: {e}")
        traceback.print_exc()
        return False

def _create_lock_file():
    with open(LOCK_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump({"pid": os.getpid(), "path": os.path.abspath(os.path.dirname(__file__))}, f)

def release_lock():
    try:
        if not LOCK_FILE_PATH.exists():
            return
        with open(LOCK_FILE_PATH, "r", encoding="utf-8") as f:
            lock_info = json.load(f)
        if lock_info.get('pid') == os.getpid():
            LOCK_FILE_PATH.unlink()
            print("\n--- グローバル・ロックを解放しました ---")
        else:
            print(f"\n警告: 自分のものではないロックファイル (PID: {lock_info.get('pid')}) を解放しようとしましたが、スキップしました。")
    except Exception as e:
        print(f"\n警告: ロックファイルの解放中にエラーが発生しました: {e}")

def is_image_file(filepath: str) -> bool:
    """Check if the file is an image based on its extension."""
    if not filepath:
        return False
    image_extensions = ['.png', '.jpg', '.jpeg', '.webp', '.heic', '.heif', '.gif']
    return any(filepath.lower().endswith(ext) for ext in image_extensions)

def load_chat_log(file_path: str, character_name: str) -> List[Dict[str, str]]:
    messages: List[Dict[str, str]] = []
    if not character_name or not file_path or not os.path.exists(file_path):
        return messages

    ai_header = f"## {character_name}:"
    alarm_header = "## システム(アラーム):"

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"エラー: ログファイル '{file_path}' 読込エラー: {e}")
        return messages

    log_parts = re.split(r'^(## .*?:)$', content, flags=re.MULTILINE)

    header = None
    for part in log_parts:
        part = part.strip()
        if not part:
            continue

        if part.startswith("## ") and part.endswith(":"):
            header = part
        elif header:
            # ユーザーの役割を判定
            is_ai_message = header == ai_header
            is_system_message = header == alarm_header

            # AIでもシステムでもないヘッダーはユーザーとみなす
            role = "model" if is_ai_message or is_system_message else "user"

            messages.append({"role": role, "content": part})
            header = None

    return messages

def format_history_for_gradio(messages: List[Dict[str, str]], character_name: str) -> List[Dict[str, Union[str, tuple, None]]]:
    if not messages:
        return []

    # --- Stage 1: Create Intermediate Representation ---
    intermediate_list = []
    image_tag_pattern = re.compile(r"\[Generated Image: (.*?)\]")

    for msg in messages:
        role = "assistant" if msg.get("role") == "model" else "user"
        content = msg.get("content", "").strip()
        if not content:
            continue

        matches = list(image_tag_pattern.finditer(content))
        if not matches:
            intermediate_list.append({
                "type": "text",
                "content": content,
                "role": role,
                "anchor_id": f"msg-anchor-{uuid.uuid4().hex[:8]}"
            })
        else:
            last_index = 0
            for i, match in enumerate(matches):
                # Add text part before the image
                text_chunk = content[last_index:match.start()].strip()
                if text_chunk:
                    intermediate_list.append({
                        "type": "text",
                        "content": text_chunk,
                        "role": role,
                        "anchor_id": f"msg-anchor-{uuid.uuid4().hex[:8]}"
                    })

                # Add image part
                filepath = match.group(1).strip()
                intermediate_list.append({
                    "type": "image",
                    "content": filepath,
                    "role": "assistant", # Images are always from the assistant
                    "anchor_id": f"msg-anchor-{uuid.uuid4().hex[:8]}"
                })
                last_index = match.end()

            # Add any remaining text part after the last image
            remaining_text = content[last_index:].strip()
            if remaining_text:
                intermediate_list.append({
                    "type": "text",
                    "content": remaining_text,
                    "role": role,
                    "anchor_id": f"msg-anchor-{uuid.uuid4().hex[:8]}"
                })

    # --- Stage 2: Generate Gradio History from Intermediate List ---
    gradio_history = []
    for i, item in enumerate(intermediate_list):
        if item["type"] == "image":
            filepath = item["content"]
            filename = os.path.basename(filepath)
            gradio_history.append({"role": item["role"], "content": (filepath, filename)})

        elif item["type"] == "text":
            current_anchor = item["anchor_id"]
            # Find previous and next text anchors for navigation
            prev_anchor = next((intermediate_list[j]["anchor_id"] for j in range(i - 1, -1, -1) if intermediate_list[j]["type"] == "text"), None)
            next_anchor = next((intermediate_list[j]["anchor_id"] for j in range(i + 1, len(intermediate_list)) if intermediate_list[j]["type"] == "text"), None)

            processed_html = _format_text_content_for_gradio(
                content=item["content"],
                current_anchor_id=current_anchor,
                prev_anchor_id=prev_anchor,
                next_anchor_id=next_anchor
            )
            gradio_history.append({"role": item["role"], "content": processed_html})

    return gradio_history

def _format_text_content_for_gradio(content: str, current_anchor_id: str, prev_anchor_id: Optional[str], next_anchor_id: Optional[str]) -> str:
    """
    Formats text content into HTML with stable navigation links.
    """
    # Up button
    up_button = ""
    if prev_anchor_id:
        up_button = f"<a href='#{prev_anchor_id}' class='message-nav-link' title='前の発言へ' style='padding: 1px 6px; font-size: 1.2em; text-decoration: none; color: #AAA;'>▲</a>"
    else:
        up_button = f"<a href='#{current_anchor_id}' class='message-nav-link' title='この発言の先頭へ' style='padding: 1px 6px; font-size: 1.2em; text-decoration: none; color: #AAA;'>▲</a>"

    # Down button
    down_button = ""
    if next_anchor_id:
        down_button = f"<a href='#{next_anchor_id}' class='message-nav-link' title='次の発言へ' style='padding: 1px 6px; font-size: 1.2em; text-decoration: none; color: #AAA;'>▼</a>"

    delete_icon = "<span title='この発言を削除するには、メッセージ本文をクリックして選択してください' style='padding: 1px 6px; font-size: 1.0em; color: #555; cursor: pointer;'>🗑️</span>"
    button_container = f"<div style='text-align: right; margin-top: 8px;'>{up_button} {down_button} <span style='margin: 0 4px;'></span> {delete_icon}</div>"

    # Process thoughts
    thoughts_pattern = re.compile(r"【Thoughts】(.*?)【/Thoughts】", re.DOTALL | re.IGNORECASE)
    thought_match = thoughts_pattern.search(content)

    final_parts = [f"<span id='{current_anchor_id}'></span>"]

    if thought_match:
        thoughts_content = thought_match.group(1).strip()
        escaped_thoughts = html.escape(thoughts_content)
        thoughts_with_breaks = escaped_thoughts.replace('\n', '<br>')
        final_parts.append(f"<div class='thoughts'>{thoughts_with_breaks}</div>")

    # Process main text
    main_text = thoughts_pattern.sub("", content).strip()
    escaped_text = html.escape(main_text)
    text_with_breaks = escaped_text.replace('\n', '<br>')
    final_parts.append(f"<div>{text_with_breaks}</div>")

    final_parts.append(button_container)

    return "".join(final_parts)


def save_message_to_log(log_file_path: str, header: str, text_content: str) -> None:
    if not all([log_file_path, header, text_content, text_content.strip()]):
        return
    try:
        if not os.path.exists(log_file_path) or os.path.getsize(log_file_path) == 0:
            content_to_append = f"{header}\n{text_content.strip()}"
        else:
            content_to_append = f"\n\n{header}\n{text_content.strip()}"

        with open(log_file_path, "a", encoding="utf-8") as f:
            f.write(content_to_append)
    except Exception as e:
        print(f"エラー: ログファイル '{log_file_path}' 書き込みエラー: {e}")
        traceback.print_exc()

def delete_message_from_log(log_file_path: str, message_key: Dict[str, str], character_name: str) -> bool:
    """
    Deletes a message from the log file based on its raw text content and role.
    """
    if not all([log_file_path, os.path.exists(log_file_path), message_key]):
        return False

    target_raw_text = message_key.get("raw_text", "").strip()
    target_role = message_key.get("role") # 'user' or 'assistant'
    if not target_raw_text or not target_role:
        return False

    # The role in the log file is 'user' or 'model'
    target_log_role = "model" if target_role == "assistant" else "user"

    def get_raw_text_from_log_content(log_content: str) -> str:
        """A simplified raw text extractor for log content."""
        # Remove image tags
        text = re.sub(r"\[Generated Image: .*?\]", "", log_content)
        # Remove thoughts
        text = remove_thoughts_from_text(text)
        # Remove timestamps
        text = re.sub(r"\n\n\d{4}-\d{2}-\d{2} \(...\) \d{2}:\d{2}:\d{2}", "", text)
        return text.strip()

    try:
        all_messages = load_chat_log(log_file_path, character_name)

        message_to_remove_index = -1
        for i, msg in enumerate(all_messages):
            log_role = msg.get("role")
            log_content = msg.get("content", "")

            log_raw_text = get_raw_text_from_log_content(log_content)

            if log_role == target_log_role and log_raw_text == target_raw_text:
                message_to_remove_index = i
                break

        if message_to_remove_index == -1:
            print("Warning: Could not find the message to delete in the log file.")
            # For debugging, let's see what was compared
            print(f"  - Target Role: '{target_log_role}'")
            print(f"  - Target Text: '{target_raw_text}'")
            return False

        # Remove the found message
        all_messages.pop(message_to_remove_index)

        # Rebuild the entire log file from the modified message list
        log_content_parts = []
        user_header = _get_user_header_from_log(log_file_path, character_name)
        ai_header = f"## {character_name}:"

        for msg in all_messages:
            header = ai_header if msg['role'] == 'model' else user_header
            content = msg['content'].strip()
            log_content_parts.append(f"{header}\n{content}")

        new_log_content = "\n\n".join(log_content_parts)
        with open(log_file_path, "w", encoding="utf-8") as f:
            f.write(new_log_content)

        if new_log_content:
            with open(log_file_path, "a", encoding="utf-8") as f:
                f.write("\n\n")

        print("--- Successfully deleted message from log ---")
        return True

    except Exception as e:
        print(f"Error during message deletion from log: {e}")
        traceback.print_exc()
        return False

def _get_user_header_from_log(log_file_path: str, ai_character_name: str) -> str:
    default_user_header = "## ユーザー:"
    if not log_file_path or not os.path.exists(log_file_path):
        return default_user_header

    last_identified_user_header = default_user_header
    try:
        with open(log_file_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped_line = line.strip()
                if stripped_line.startswith("## ") and stripped_line.endswith(":"):
                    if not stripped_line.startswith(f"## {ai_character_name}:") and not stripped_line.startswith("## システム("):
                        last_identified_user_header = stripped_line
        return last_identified_user_header
    except Exception as e:
        print(f"エラー: ユーザーヘッダー取得エラー: {e}")
        return default_user_header

def remove_thoughts_from_text(text: str) -> str:
    if not text:
        return ""
    thoughts_pattern = re.compile(r"【Thoughts】.*?【/Thoughts】\s*", re.DOTALL | re.IGNORECASE)
    return thoughts_pattern.sub("", text).strip()

def get_current_location(character_name: str) -> Optional[str]:
    try:
        location_file_path = os.path.join("characters", character_name, "current_location.txt")
        if os.path.exists(location_file_path):
            with open(location_file_path, 'r', encoding='utf-8') as f:
                return f.read().strip()
    except Exception as e:
        print(f"警告: 現在地ファイルの読み込みに失敗しました: {e}")
    return None

def extract_raw_text_from_html(html_content: str) -> str:
    if not html_content:
        return ""

    # 1. ボタンコンテナを削除
    html_content = re.sub(r"<div style='text-align: right;.*?'>.*?</div>", "", html_content, flags=re.DOTALL)

    # 2. 思考ログを削除
    html_content = re.sub(r"<div class='thoughts'>.*?</div>", "", html_content, flags=re.DOTALL)

    # 3. アンカーを削除
    html_content = re.sub(r"<span id='msg-anchor-.*?'></span>", "", html_content)

    # 4. 画像やファイルのMarkdownリンクを元のタグ形式に戻す
    # ![filename](/file=...) -> [Generated Image: filepath]
    # [filename](/file=...) -> [ファイル添付: filepath]
    def restore_tags(match):
        text = match.group(1)
        path = match.group(2)
        if match.group(0).startswith('!'):
            return f"[Generated Image: {path}]"
        else:
            return f"[ファイル添付: {path}]"

    html_content = re.sub(r'!?\[(.*?)\]\(\/file=(.*?)\)', restore_tags, html_content)

    # 5. 残ったHTMLタグ (<div>など) を削除
    raw_text = re.sub('<[^<]+?>', '', html_content)

    # 6. HTMLエンティティをデコード（例: &lt; -> <）
    raw_text = html.unescape(raw_text)

    return raw_text.strip()
