# utils.py の完全な復元版

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

def format_history_for_gradio(messages: List[Dict[str, str]]) -> List[Dict[str, Union[str, tuple, None]]]:
    """
    チャットログをGradio Chatbotの `messages` 形式に変換します。
    【Thought】タグ、AI生成画像、ユーザー添付ファイル（複数対応）を適切に処理します。
    """
    if not messages:
        return []

    gradio_history = []
    # 正規表現パターンを関数の先頭でコンパイル
    ai_image_tag_pattern = re.compile(r"\[Generated Image: (.*?)\]")
    user_file_attach_pattern = re.compile(r"\[ファイル添付: (.*?)\]")

    for msg in messages:
        role = "assistant" if msg.get("role") == "model" else "user"
        content = msg.get("content", "").strip()

        if not content:
            continue

        # メッセージを行ごとに分割し、テキストとタグを分離・保持する
        parts = []
        current_text = ""
        for line in content.splitlines():
            file_match = user_file_attach_pattern.fullmatch(line.strip())
            image_match = ai_image_tag_pattern.fullmatch(line.strip())

            if file_match:
                if current_text:
                    parts.append({"type": "text", "value": current_text})
                    current_text = ""
                parts.append({"type": "file", "value": file_match.group(1).strip()})
            elif image_match:
                if current_text:
                    parts.append({"type": "text", "value": current_text})
                    current_text = ""
                parts.append({"type": "image", "value": image_match.group(1).strip()})
            else:
                current_text += line + "\n"

        if current_text:
            parts.append({"type": "text", "value": current_text.strip()})

        # 分離したパーツをGradioの形式に変換して追加
        for part in parts:
            if part["type"] == "text":
                formatted_text = format_response_for_display(part["value"]) if role == "assistant" else part["value"]
                if formatted_text:
                     gradio_history.append({"role": role, "content": formatted_text})
            elif part["type"] == "file":
                filepath = part["value"]
                original_filename = os.path.basename(filepath)
                absolute_filepath = os.path.abspath(filepath)
                if os.path.exists(absolute_filepath):
                    gradio_history.append({"role": role, "content": (absolute_filepath, original_filename)})
                else:
                    gradio_history.append({"role": role, "content": f"*[表示エラー: ファイル '{original_filename}' が見つかりません]*"})
            elif part["type"] == "image":
                image_path = part["value"]
                absolute_image_path = os.path.abspath(image_path)
                if os.path.exists(absolute_image_path):
                    gradio_history.append({"role": role, "content": (absolute_image_path, os.path.basename(image_path))})
                else:
                    gradio_history.append({"role": role, "content": f"*[表示エラー: 画像 '{os.path.basename(image_path)}' が見つかりません]*"})

    return gradio_history

def save_message_to_log(log_file_path: str, header: str, text_content: str) -> None:
    if not log_file_path or not header or not text_content or not text_content.strip():
        return

    try:
        needs_leading_newline = False
        if os.path.exists(log_file_path) and os.path.getsize(log_file_path) > 0:
            try:
                with open(log_file_path, "rb") as f:
                    f.seek(-2, os.SEEK_END)
                    if f.read(2) != b'\n\n':
                        needs_leading_newline = True
            except IOError:
                needs_leading_newline = True

        with open(log_file_path, "a", encoding="utf-8") as f:
            if needs_leading_newline:
                f.write("\n\n")
            f.write(f"{header}\n{text_content.strip()}\n") # ヘッダーと本文の間の空行を1つに

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

def save_log_file(character_name: str, content: str) -> None:
    if not character_name:
        print("エラー: save_log_file - character_name が指定されていません。")
        return
    try:
        log_file_path, _, _, _, _ = character_manager.get_character_files_paths(character_name) # 戻り値の数を5に変更
        if not log_file_path:
            print(f"エラー: save_log_file - キャラクター '{character_name}' のログファイルパスを取得できませんでした。")
            return
        with open(log_file_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"エラー: ログファイル書き込み中に予期せぬエラーが発生しました (キャラクター: {character_name}): {e}")
        traceback.print_exc()

# --- グローバル・ロック管理 ---
LOCK_FILE_PATH = Path.home() / ".nexus_ark.global.lock"

def acquire_lock() -> bool:
    """
    グローバル・ロックを取得する。
    """
    if not LOCK_FILE_PATH.exists():
        try:
            with open(LOCK_FILE_PATH, "w", encoding="utf-8") as f:
                lock_data = {"pid": os.getpid(), "path": os.path.abspath(os.path.dirname(__file__))}
                json.dump(lock_data, f)
            return True
        except Exception as e:
            print(f"エラー: ロックファイルの作成に失敗しました: {e}")
            return False

    try:
        with open(LOCK_FILE_PATH, "r", encoding="utf-8") as f:
            lock_info = json.load(f)
        pid = lock_info.get('pid')

        if pid is None:
            print(f"警告: PID情報のないロックファイルが見つかりました: {LOCK_FILE_PATH}")
            if _prompt_to_delete_lock(): return acquire_lock()
            else: return False

        if psutil.pid_exists(pid):
            path = lock_info.get('path', '不明')
            print("エラー: Nexus Arkの別のプロセス（またはバッチ処理）がすでに実行中です。")
            print(f"  - 実行中のプロセスID: {pid}")
            print(f"  - 実行中のフォルダパス: {path}")
            return False
        else:
            print(f"警告: 古いロックファイルが見つかりました (プロセスID: {pid} は実行されていません)。")
            if _prompt_to_delete_lock(): return acquire_lock()
            else: return False

    except (json.JSONDecodeError, IOError) as e:
        print(f"警告: ロックファイル '{LOCK_FILE_PATH}' の読み込み中にエラー: {e}")
        if _prompt_to_delete_lock(): return acquire_lock()
        else: return False
    except Exception as e:
        print(f"エラー: ロックファイルの処理中に予期せぬ問題が発生しました: {e}")
        traceback.print_exc()
        return False

def _prompt_to_delete_lock() -> bool:
    """ユーザーにロックファイル削除の確認を求める内部関数"""
    try:
        user_input = input("-> このロックファイルを削除して続行しますか？ (y/n): ").lower()
        if user_input == 'y':
            try:
                LOCK_FILE_PATH.unlink()
                print("-> ロックファイルを削除しました。")
                return True
            except Exception as e_unlink:
                print(f"-> ロックファイルの削除に失敗しました: {e_unlink}")
                return False
        else:
            print("-> 処理を中止しました。")
            return False
    except (EOFError, KeyboardInterrupt):
        print("\n-> 処理を中断しました。")
        return False

def release_lock():
    """
    現在のプロセスが所有するグローバル・ロックを解放する。
    """
    if LOCK_FILE_PATH.exists():
        try:
            with open(LOCK_FILE_PATH, "r", encoding="utf-8") as f:
                lock_info = json.load(f)
            if lock_info.get('pid') == os.getpid():
                LOCK_FILE_PATH.unlink()
                print("\nグローバル・ロックを解放しました。")
        except (IOError, json.JSONDecodeError) as e:
             print(f"\n警告: ロックファイルの読み取り/解析中にエラーが発生したため、解放できませんでした: {e}")
        except Exception as e:
            print(f"\n警告: ロックファイルの解放中に予期せぬエラーが発生しました: {e}")
