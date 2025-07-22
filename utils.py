# utils.py の内容を、以下のコードで完全に置き換えてください

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
            header = None

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
    チャットログをGradio Chatbotの `messages` 形式に変換する（Markdown文字列出力版）。
    タプルは一切返さず、画像やファイルはMarkdown形式の文字列としてフォーマットする。
    """
    if not messages:
        return []

    gradio_history = []
    tag_pattern = re.compile(r"(\[Generated Image: .*?\]|\[ファイル添付: .*?\])")

    for msg in messages:
        role = "assistant" if msg.get("role") == "model" else "user"
        content = msg.get("content", "").strip()
        if not content:
            continue

        parts = tag_pattern.split(content)
        current_message_parts = []

        for part in parts:
            part = part.strip()
            if not part:
                continue

            is_image_tag = part.startswith("[Generated Image:") and part.endswith("]")
            is_file_tag = part.startswith("[ファイル添付:") and part.endswith("]")

            if is_image_tag or is_file_tag:
                # タグからパスとファイル名を抽出
                if is_image_tag:
                    filepath = part[len("[Generated Image:"): -1].strip()
                else: # is_file_tag
                    filepath = part[len("[ファイル添付:"): -1].strip()

                absolute_filepath = os.path.abspath(filepath)
                filename = os.path.basename(filepath)

                if os.path.exists(absolute_filepath):
                    # パス内のバックスラッシュをスラッシュに置換
                    safe_filepath = absolute_filepath.replace("\\", "/")
                    if is_image_tag:
                        # Markdown画像形式
                        current_message_parts.append(f"![{filename}](/file={safe_filepath})")
                    else:
                        # Markdownリンク形式
                        current_message_parts.append(f"[{filename}](/file={safe_filepath})")
                else:
                    error_msg = f"*[表示エラー: ファイル '{filename}' が見つかりません]*"
                    current_message_parts.append(error_msg)
            else:
                # 通常のテキスト部分の処理
                formatted_text = format_response_for_display(part) if role == "assistant" else part
                if formatted_text:
                    current_message_parts.append(formatted_text)

        # 1つのメッセージ（1つのcontent）を結合して履歴に追加
        if current_message_parts:
            final_content = "\n\n".join(current_message_parts)
            gradio_history.append({"role": role, "content": final_content})

    return gradio_history

def save_message_to_log(log_file_path: str, header: str, text_content: str) -> None:
    if not log_file_path or not header or not text_content or not text_content.strip():
        return
    try:
        needs_leading_newline = False
        if os.path.exists(log_file_path) and os.path.getsize(log_file_path) > 0:
            with open(log_file_path, "rb") as f:
                f.seek(-2, os.SEEK_END)
                if f.read(2) != b'\n\n':
                    needs_leading_newline = True
        if os.path.exists(log_file_path) and os.path.getsize(log_file_path) == 0:
             needs_leading_newline = False
        with open(log_file_path, "a", encoding="utf-8") as f:
            if needs_leading_newline:
                f.write("\n\n")
            f.write(f"{header}\n{text_content.strip()}")
    except Exception as e:
        print(f"エラー: ログファイル '{log_file_path}' 書き込みエラー: {e}")
        traceback.print_exc()

def delete_message_from_log(log_file_path: str, message_to_delete: Dict[str, str]) -> bool:
    """
    UIから渡されたメッセージオブジェクトを元に、ログファイルから対応するエントリを削除する堅牢版。
    """
    if not log_file_path or not os.path.exists(log_file_path) or not message_to_delete:
        return False

    content_from_ui = message_to_delete.get("content", "")
    if not content_from_ui:
        return False

    try:
        with open(log_file_path, "r", encoding="utf-8") as f:
            original_log_content = f.read()

        # ログをヘッダーとコンテンツのペアに分割
        log_entries = re.split(r'(^## .*?:$)', original_log_content, flags=re.MULTILINE)

        new_log_entries = []
        found_and_deleted = False

        # UIのcontentから検索対象の文字列（ログ形式）を再構築
        search_targets = []
        # 1. Markdownリンクを解析
        md_link_pattern = re.compile(r"!*\[.*?\]\(/file=(.*?)\)")
        md_matches = md_link_pattern.findall(content_from_ui)
        if md_matches:
            for filepath in md_matches:
                # Gradioはパスを正規化している可能性があるので、こちらも正規化して比較
                normalized_path = os.path.normpath(filepath)
                search_targets.append(f"[Generated Image: {normalized_path}]")
                search_targets.append(f"[ファイル添付: {normalized_path}]")
        else:
            # 2. 通常のテキストとして扱う
            # UIで表示されるテキストは、format_response_for_displayを通っている可能性があるので、元に戻す試み
            # 簡単なケースとして、思考ログのHTMLタグを除去する
            cleaned_text = re.sub(r"<div class='thoughts'>.*?</div>\n\n", "", content_from_ui, flags=re.DOTALL)
            search_targets.append(cleaned_text.strip())

        # ログエントリを走査して削除対象を特定
        i = 1 if log_entries and log_entries[0] == '' else 0
        while i < len(log_entries):
            header = log_entries[i]
            content_from_log = log_entries[i+1].strip()

            is_match = False
            for target in search_targets:
                if target in content_from_log:
                    is_match = True
                    break

            if is_match and not found_and_deleted:
                # 削除対象が見つかったら、新しいリストには追加しない
                found_and_deleted = True
                print(f"--- ログからメッセージを削除: {content_from_log[:50]}... ---")
            else:
                # 削除対象でない場合は、新しいリストに追加
                new_log_entries.append(header)
                new_log_entries.append(log_entries[i+1])
            i += 2

        if not found_and_deleted:
            print(f"警告: ログファイル内に削除対象のメッセージが見つかりませんでした。UI Content: {content_from_ui[:50]}...")
            return False

        # 新しいログファイルの内容を結合
        new_log_content = "".join(new_log_entries).strip()

        with open(log_file_path, "w", encoding="utf-8") as f:
            f.write(new_log_content)
        # ログ末尾に改行を追加して、次の書き込みに備える
        with open(log_file_path, "a", encoding="utf-8") as f:
            f.write("\n\n")


        return True

    except Exception as e:
        print(f"エラー: ログからのメッセージ削除中にエラーが発生: {e}")
        traceback.print_exc()
        return False


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
        return default_user_header

def save_log_file(character_name: str, content: str) -> None:
    if not character_name: return
    try:
        log_file_path, _, _, _, _ = character_manager.get_character_files_paths(character_name)
        if not log_file_path: return
        with open(log_file_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"エラー: ログファイル書き込みエラー: {e}")

# --- グローバル・ロック管理 ---
LOCK_FILE_PATH = Path.home() / ".nexus_ark.global.lock"

def acquire_lock() -> bool:
    if not LOCK_FILE_PATH.exists():
        try:
            with open(LOCK_FILE_PATH, "w", encoding="utf-8") as f:
                json.dump({"pid": os.getpid(), "path": os.path.abspath(os.path.dirname(__file__))}, f)
            return True
        except Exception as e:
            print(f"エラー: ロックファイル作成失敗: {e}"); return False
    try:
        with open(LOCK_FILE_PATH, "r", encoding="utf-8") as f: lock_info = json.load(f)
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
        print(f"エラー: ロック処理中の予期せぬ問題: {e}"); return False

def _prompt_to_delete_lock() -> bool:
    try:
        user_input = input("-> このロックファイルを削除して続行しますか？ (y/n): ").lower()
        if user_input == 'y':
            LOCK_FILE_PATH.unlink(); print("-> ロックファイルを削除しました。"); return True
    except Exception as e: print(f"-> ロックファイル削除失敗: {e}")
    print("-> 処理を中止しました。"); return False

def release_lock():
    if LOCK_FILE_PATH.exists():
        try:
            with open(LOCK_FILE_PATH, "r", encoding="utf-8") as f:
                if json.load(f).get('pid') == os.getpid():
                    LOCK_FILE_PATH.unlink(); print("\nグローバル・ロックを解放しました。")
        except Exception as e: print(f"\n警告: ロックファイル解放エラー: {e}")
