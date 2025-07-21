# utils.py の完全な復元・修正版

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

# --- モデル情報キャッシュ ---
_model_token_limits_cache: Dict[str, Dict[str, int]] = {}

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

    # Split by headers, keeping the headers
    # The pattern looks for '## anything:' at the beginning of a line
    log_parts = re.split(r'^(## .*?:)$', content, flags=re.MULTILINE)

    header = None
    for part in log_parts:
        part = part.strip()
        if not part:
            continue

        if part.startswith("## ") and part.endswith(":"):
            header = part
        elif header:
            role = "model" if header == ai_header else "user"
            messages.append({"role": role, "content": part})
            header = None # Reset header after processing content

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

# ★★★ ここからが修正箇所 ★★★
def format_history_for_gradio(messages: List[Dict[str, str]]) -> List[Dict[str, Union[str, tuple, None]]]:
    """
    チャットログをGradio Chatbotの `messages` 形式に変換する（re.splitを使用した堅牢版）。
    """
    if not messages:
        return []

    gradio_history = []
    # ファイルタグと画像タグを両方捉えるための正規表現パターン
    tag_pattern = re.compile(r"(\[Generated Image: .*?\]|\[ファイル添付: .*?\])")

    for msg in messages:
        role = "assistant" if msg.get("role") == "model" else "user"
        content = msg.get("content", "").strip()

        if not content:
            continue

        # コンテンツをタグとテキスト部分に分割
        parts = tag_pattern.split(content)

        for part in parts:
            part = part.strip()
            if not part:
                continue

            # タグかどうかを判定
            is_image_tag = part.startswith("[Generated Image:") and part.endswith("]")
            is_file_tag = part.startswith("[ファイル添付:") and part.endswith("]")

            if is_image_tag:
                # 画像タグの処理
                image_path = part[len("[Generated Image:"): -1].strip()
                absolute_image_path = os.path.abspath(image_path)
                if os.path.exists(absolute_image_path):
                    gradio_history.append({"role": role, "content": (absolute_image_path, os.path.basename(image_path))})
                else:
                    gradio_history.append({"role": role, "content": f"*[表示エラー: 画像 '{os.path.basename(image_path)}' が見つかりません]*"})

            elif is_file_tag:
                # ファイルタグの処理
                filepath = part[len("[ファイル添付:"): -1].strip()
                original_filename = os.path.basename(filepath)
                absolute_filepath = os.path.abspath(filepath)
                if os.path.exists(absolute_filepath):
                    gradio_history.append({"role": role, "content": (absolute_filepath, original_filename)})
                else:
                    gradio_history.append({"role": role, "content": f"*[表示エラー: ファイル '{original_filename}' が見つかりません]*"})

            else:
                # 通常のテキスト部分の処理（タイムスタンプもここに含まれる）
                formatted_text = format_response_for_display(part) if role == "assistant" else part
                if formatted_text:
                    gradio_history.append({"role": role, "content": formatted_text})

    return gradio_history
# ★★★ 修正ここまで ★★★

def save_message_to_log(log_file_path: str, header: str, text_content: str) -> None:
    if not log_file_path or not header or not text_content or not text_content.strip():
        return

    try:
        # ログファイルの末尾が改行2つでない場合に、改行を追加するロジック
        needs_leading_newline = False
        if os.path.exists(log_file_path) and os.path.getsize(log_file_path) > 0:
            with open(log_file_path, "rb") as f:
                f.seek(-2, os.SEEK_END)
                if f.read(2) != b'\n\n':
                    needs_leading_newline = True

        # ファイルの先頭が空の場合は改行不要
        if os.path.exists(log_file_path) and os.path.getsize(log_file_path) == 0:
             needs_leading_newline = False

        with open(log_file_path, "a", encoding="utf-8") as f:
            if needs_leading_newline:
                f.write("\n\n")
            f.write(f"{header}\n{text_content.strip()}")

    except Exception as e:
        print(f"エラー: ログファイル '{log_file_path}' 書き込みエラー: {e}")
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
        print(f"エラー: ユーザーヘッダー取得エラー: {e}")
        traceback.print_exc()
        return default_user_header

def save_log_file(character_name: str, content: str) -> None:
    if not character_name:
        print("エラー: save_log_file - character_name が指定されていません。")
        return
    try:
        log_file_path, _, _, _, _ = character_manager.get_character_files_paths(character_name)
        if not log_file_path:
            print(f"エラー: save_log_file - キャラクター '{character_name}' のログファイルパスを取得できませんでした。")
            return
        with open(log_file_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"エラー: ログファイル書き込みエラー (キャラクター: {character_name}): {e}")
        traceback.print_exc()

# --- グローバル・ロック管理 ---
LOCK_FILE_PATH = Path.home() / ".nexus_ark.global.lock"

def acquire_lock() -> bool:
    if not LOCK_FILE_PATH.exists():
        try:
            with open(LOCK_FILE_PATH, "w", encoding="utf-8") as f:
                json.dump({"pid": os.getpid(), "path": os.path.abspath(os.path.dirname(__file__))}, f)
            return True
        except Exception as e:
            print(f"エラー: ロックファイル作成失敗: {e}")
            return False

    try:
        with open(LOCK_FILE_PATH, "r", encoding="utf-8") as f:
            lock_info = json.load(f)
        pid = lock_info.get('pid')

        if pid is None or not psutil.pid_exists(pid):
            print(f"警告: 古いロックファイルを発見 (PID: {pid or '不明'})。")
            if _prompt_to_delete_lock(): return acquire_lock()
            return False
        else:
            print("エラー: Nexus Arkの別プロセスが実行中です。")
            print(f"  - PID: {pid}, Path: {lock_info.get('path', '不明')}")
            return False
    except (json.JSONDecodeError, IOError) as e:
        print(f"警告: ロックファイル '{LOCK_FILE_PATH}' 読込エラー: {e}")
        if _prompt_to_delete_lock(): return acquire_lock()
        return False
    except Exception as e:
        print(f"エラー: ロック処理中の予期せぬ問題: {e}")
        traceback.print_exc()
        return False

def _prompt_to_delete_lock() -> bool:
    try:
        user_input = input("-> このロックファイルを削除して続行しますか？ (y/n): ").lower()
        if user_input == 'y':
            LOCK_FILE_PATH.unlink()
            print("-> ロックファイルを削除しました。")
            return True
    except Exception as e:
        print(f"-> ロックファイル削除失敗: {e}")
    print("-> 処理を中止しました。")
    return False

def release_lock():
    if LOCK_FILE_PATH.exists():
        try:
            with open(LOCK_FILE_PATH, "r", encoding="utf-8") as f:
                if json.load(f).get('pid') == os.getpid():
                    LOCK_FILE_PATH.unlink()
                    print("\nグローバル・ロックを解放しました。")
        except Exception as e:
             print(f"\n警告: ロックファイル解放エラー: {e}")
