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

def format_history_for_gradio(messages: List[Dict[str, str]], character_name: str) -> List[List[Union[str, Tuple[str, str], None]]]:
    """
    ログデータをGradio Chatbotが期待する「ペアのリスト」形式に変換する、最終FIX版。
    画像が含まれる場合はテキストと画像のターンを正しく分割し、テキストにはHTMLボタンを追加する。
    """
    if not messages:
        return []

    gradio_pairs = []
    user_message_buffer = None

    for i, msg in enumerate(messages):
        role = msg.get("role")
        content = msg.get("content", "").strip()
        if not content:
            continue

        if role == "user":
            if user_message_buffer:
                gradio_pairs.append([_format_user_content(user_message_buffer, i - 1, len(messages)), None])
            user_message_buffer = content

        elif role == "model":
            formatted_user_msg = _format_user_content(user_message_buffer, i - 1, len(messages)) if user_message_buffer else None

            image_tag_pattern = re.compile(r"\[Generated Image: (.*?)\]")
            image_matches = list(image_tag_pattern.finditer(content))

            if not image_matches:
                formatted_bot_msg = _format_bot_content(content, i, len(messages))
                gradio_pairs.append([formatted_user_msg, formatted_bot_msg])
            else:
                last_end = 0
                first_text = content[:image_matches[0].start()].strip()
                if first_text:
                    gradio_pairs.append([formatted_user_msg, _format_bot_content(first_text, i, len(messages))])
                    formatted_user_msg = None

                for match in image_matches:
                    filepath = match.group(1).strip()
                    filename = os.path.basename(filepath)
                    image_tuple = (filepath, filename)
                    gradio_pairs.append([formatted_user_msg, image_tuple])
                    formatted_user_msg = None

                    text_after_match = content[match.end():]
                    next_match = image_tag_pattern.search(text_after_match)
                    text_chunk = (text_after_match[:next_match.start()] if next_match else text_after_match).strip()
                    if text_chunk:
                         gradio_pairs.append([None, _format_bot_content(text_chunk, i, len(messages))])

            user_message_buffer = None

    if user_message_buffer:
        gradio_pairs.append([_format_user_content(user_message_buffer, len(messages) - 1, len(messages)), None])

    return gradio_pairs

def _format_user_content(content: str, msg_index: int, total_msgs: int) -> str:
    """ユーザーメッセージをHTML化し、ナビゲーションボタンを追加する。"""
    escaped_text = html.escape(content).replace('\n', '<br>')
    button_html = _create_button_container(msg_index, total_msgs)
    return f"<div>{escaped_text}{button_html}</div>"

def _format_bot_content(content: str, msg_index: int, total_msgs: int) -> str:
    """AIメッセージをHTML化し、思考ログやボタンを追加する。"""
    thoughts_pattern = re.compile(r"【Thoughts】(.*?)【/Thoughts】", re.DOTALL | re.IGNORECASE)

    thought_html = ""
    thought_match = thoughts_pattern.search(content)
    if thought_match:
        thoughts_text = thought_match.group(1).strip()
        escaped_thoughts = html.escape(thoughts_text).replace('\n', '<br>')
        thought_html = f"<div class='thoughts'>{escaped_thoughts}</div>"

    main_text = thoughts_pattern.sub("", content).strip()
    escaped_main = html.escape(main_text).replace('\n', '<br>')
    main_html = f"<div>{escaped_main}</div>"

    button_html = _create_button_container(msg_index, total_msgs)

    return f"{thought_html}{main_html}{button_html}"

def _create_button_container(msg_index: int, total_msgs: int) -> str:
    """ナビゲーションボタンと削除アイコンのHTMLを生成する。"""
    anchor_id = f"msg-anchor-{uuid.uuid4().hex[:8]}-{msg_index}"
    # ボタンのHTMLにはアンカーを含めず、JSでの制御に任せる
    up_button = f"<a href='#{anchor_id}' class='message-nav-link' title='この発言の先頭へ' style='padding: 1px 6px; font-size: 1.2em; text-decoration: none; color: #AAA;'>▲</a>"
    down_button = ""
    if msg_index < total_msgs - 1:
        next_anchor_id = f"msg-anchor-{uuid.uuid4().hex[:8]}-{msg_index+1}"
        down_button = f"<a href='#{next_anchor_id}' class='message-nav-link' title='次の発言へ' style='padding: 1px 6px; font-size: 1.2em; text-decoration: none; color: #AAA;'>▼</a>"
    delete_icon = "<span title='この発言を削除するには、メッセージ本文をクリックして選択してください' style='padding: 1px 6px; font-size: 1.0em; color: #555; cursor: pointer;'>🗑️</span>"
    # メッセージの先頭にアンカーを追加
    return f"<span id='{anchor_id}'></span><div style='text-align: right; margin-top: 8px;'>{up_button} {down_button} <span style='margin: 0 4px;'></span> {delete_icon}</div>"
