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

def format_history_for_gradio(messages: List[Dict[str, str]]) -> List[List[Union[str, Tuple[str, str], None]]]:
    """
    ログデータをGradio Chatbotが期待する「ペアのリスト」形式に変換する、最終FIX版。
    思考ログはプレーンテキストとして本文に含め、画像は正しくターンを分割する。
    カスタムHTMLは一切使用しない。
    """
    if not messages:
        return []

    gradio_pairs = []
    user_message_buffer = None

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "").strip()
        if not content:
            continue

        if role == "user":
            if user_message_buffer:
                gradio_pairs.append([user_message_buffer, None])
            user_message_buffer = content

        elif role == "model":
            image_tag_pattern = re.compile(r"\[Generated Image: (.*?)\]")
            image_matches = list(image_tag_pattern.finditer(content))

            if not image_matches:
                gradio_pairs.append([user_message_buffer, content])
            else:
                last_end = 0
                first_text = content[:image_matches[0].start()].strip()
                if first_text:
                    gradio_pairs.append([user_message_buffer, first_text])
                    user_message_buffer = None

                for i, match in enumerate(image_matches):
                    filepath = match.group(1).strip()
                    filename = os.path.basename(filepath)
                    image_tuple = (filepath, filename)
                    gradio_pairs.append([user_message_buffer if i == 0 and not first_text else None, image_tuple])

                    text_after = content[match.end():].strip()
                    # 複数の画像に対応するため、次の画像までのテキストを切り出す
                    next_match_start = image_matches[i+1].start() if i + 1 < len(image_matches) else len(content)
                    text_chunk = content[match.end():next_match_start].strip()
                    if text_chunk:
                         gradio_pairs.append([None, text_chunk])

            user_message_buffer = None

    if user_message_buffer:
        gradio_pairs.append([user_message_buffer, None])

    return gradio_pairs

def delete_message_from_log_by_content(log_file_path: str, content_to_find: str, character_name: str) -> bool:
    """内容（思考ログを除く）に基づいてログからメッセージを削除する。"""
    if not all([log_file_path, os.path.exists(log_file_path), content_to_find, character_name]):
        return False
    try:
        all_messages = load_chat_log(log_file_path, character_name)

        target_index = -1
        # 思考ログを除いた純粋なテキストで比較
        clean_content_to_find = remove_thoughts_from_text(content_to_find)

        for i, msg in enumerate(all_messages):
            clean_log_content = remove_thoughts_from_text(msg.get("content", ""))
            if clean_content_to_find == clean_log_content:
                target_index = i
                break

        if target_index != -1:
            # ユーザーの発言がクリックされた場合は、後続のAIの発言も削除する
            indices_to_delete = [target_index]
            if all_messages[target_index]['role'] == 'user' and (target_index + 1) < len(all_messages) and all_messages[target_index + 1]['role'] == 'model':
                indices_to_delete.append(target_index + 1)

            # 後ろから削除
            for index in sorted(indices_to_delete, reverse=True):
                delete_message_from_log_by_index(log_file_path, index)
            return True
        return False
    except Exception as e:
        print(f"内容によるログ削除エラー: {e}")
        return False

def delete_message_from_log_by_index(log_file_path: str, index_to_delete: int) -> bool:
    """指定されたインデックスのメッセージをログファイルから削除する。"""
    if not log_file_path or not os.path.exists(log_file_path) or index_to_delete < 0:
        return False
    try:
        character_name = os.path.basename(os.path.dirname(log_file_path))
        all_messages = load_chat_log(log_file_path, character_name)
        if 0 <= index_to_delete < len(all_messages):
            all_messages.pop(index_to_delete)
            # (ログファイル再構築ロジックは変更なし)
            log_content_parts = []
            user_header = _get_user_header_from_log(log_file_path, character_name)
            ai_header = f"## {character_name}:"
            for msg in all_messages:
                header = ai_header if msg['role'] == 'model' else user_header
                log_content_parts.append(f"{header}\n{msg['content'].strip()}")
            new_log_content = "\n\n".join(log_content_parts)
            with open(log_file_path, "w", encoding="utf-8") as f:
                f.write(new_log_content)
            if new_log_content:
                with open(log_file_path, "a", encoding="utf-8") as f: f.write("\n\n")
            return True
        return False
    except Exception as e:
        print(f"インデックスによるログ削除エラー: {e}")
        return False
