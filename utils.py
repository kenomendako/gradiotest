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

# --- モデル情報キャッシュ ---
_model_token_limits_cache: Dict[str, Dict[str, int]] = {}

# --- グローバル・ロック管理 (v2: 自動クリーンアップ機能付き) ---
LOCK_FILE_PATH = Path.home() / ".nexus_ark.global.lock"

def acquire_lock() -> bool:
    """
    グローバルロックを取得する。古いロックファイルは自動でクリーンアップを試みる。
    戻り値:
        - True: ロック取得成功
        - False: ロック取得失敗 (他のプロセスが実行中)
    """
    print("--- グローバル・ロックの取得を試みます ---")
    try:
        if not LOCK_FILE_PATH.exists():
            # ケース1: ロックファイルが存在しない -> 新規作成
            _create_lock_file()
            print("--- ロックを取得しました (新規作成) ---")
            return True

        # ケース2: ロックファイルが存在する -> 内容を確認
        with open(LOCK_FILE_PATH, "r", encoding="utf-8") as f:
            lock_info = json.load(f)
        
        pid = lock_info.get('pid')
        if pid and psutil.pid_exists(pid):
            # ケース2a: PIDが存在し、プロセスも実行中 -> ロック失敗
            print("\n" + "="*60)
            print("!!! エラー: Nexus Arkの別プロセスが既に実行中です。")
            print(f"    - 実行中のPID: {pid}")
            print(f"    - パス: {lock_info.get('path', '不明')}")
            print("    多重起動はできません。既存のプロセスを終了するか、")
            print("    タスクマネージャーからプロセスを強制終了してください。")
            print("="*60 + "\n")
            return False
        else:
            # ケース2b: PIDがない、またはプロセスが存在しない -> 古いロックファイル
            print("\n" + "!"*60)
            print("警告: 古いロックファイルを検出しました。")
            print(f"  - 記録されていたPID: {pid or '不明'} (このプロセスは現在実行されていません)")
            print("  古いロックファイルを自動的に削除して、処理を続行します。")
            print("!"*60 + "\n")
            LOCK_FILE_PATH.unlink()
            time.sleep(0.5) # 削除がファイルシステムに反映されるのを少し待つ
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
    """現在のプロセス情報でロックファイルを作成する。"""
    with open(LOCK_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump({"pid": os.getpid(), "path": os.path.abspath(os.path.dirname(__file__))}, f)

def release_lock():
    """
    自身が取得したロックを解放する。
    """
    try:
        if not LOCK_FILE_PATH.exists():
            return
        
        with open(LOCK_FILE_PATH, "r", encoding="utf-8") as f:
            lock_info = json.load(f)
        
        if lock_info.get('pid') == os.getpid():
            LOCK_FILE_PATH.unlink()
            print("\n--- グローバル・ロックを解放しました ---")
        else:
            # 自分のものではないロックファイルは消さない
            print(f"\n警告: 自分のものではないロックファイル (PID: {lock_info.get('pid')}) を解放しようとしましたが、スキップしました。")

    except Exception as e:
        print(f"\n警告: ロックファイルの解放中にエラーが発生しました: {e}")


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
    if not response_text:
        return ""

    # 1. 各応答の「目印」となるユニークなIDを生成
    anchor_id = f"msg-anchor-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"

    # 2. 「この応答の先頭へ」ボタンのHTMLを生成 (href属性を使用)
    scroll_button_html = (
        f"<a href='#{anchor_id}' "
        f"style='display: inline-block; padding: 2px 8px; margin-top: 12px; font-size: 0.8em; background-color: #f0f0f0; color: #333; border-radius: 12px; text-decoration: none;'>"
        "▲ この応答の先頭へ"
        "</a>"
    )

    # 3. 思考ログを処理 (既存ロジック)
    thoughts_pattern = re.compile(r"【Thoughts】(.*?)【/Thoughts】", re.DOTALL | re.IGNORECASE)
    thought_match = thoughts_pattern.search(response_text)
    thought_html_block = ""
    if thought_match:
        thoughts_content = thought_match.group(1).strip()
        escaped_content = html.escape(thoughts_content)
        content_with_breaks = escaped_content.replace('\n', '<br>')
        thought_html_block = f"<div class='thoughts'>{content_with_breaks}</div>"
        main_response_text = thoughts_pattern.sub("", response_text).strip()
    else:
        main_response_text = response_text.strip()

    # 4. 最終的なHTMLを組み立てる
    final_html_parts = [
        # スクロール先の「目印」となる空のspanを先頭に配置
        f"<span id='{anchor_id}'></span>",
    ]

    # 思考ログと本文を追加
    if thought_html_block:
        final_html_parts.append(thought_html_block)

    if main_response_text:
        if thought_html_block:
             final_html_parts.append("<br>") # 思考ログと本文の間にスペース
        # GradioがMarkdownとして解釈し<p>タグなどを自動挿入するのを防ぐため、
        # 本文をdivで囲んでおくのが安全策
        final_html_parts.append(f"<div>{main_response_text}</div>")


    # 応答内容がある場合のみ、末尾にスクロールボタンを追加
    if thought_html_block or main_response_text:
        final_html_parts.append(scroll_button_html)


    # 全体を1つのdivで囲むことで、Gradio内でのレンダリング単位を保証
    return f"<div>{''.join(final_html_parts)}</div>"

def format_history_for_gradio(messages: List[Dict[str, str]]) -> List[Dict[str, Union[str, tuple, None]]]:
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
                if is_image_tag: filepath = part[len("[Generated Image:"): -1].strip()
                else: filepath = part[len("[ファイル添付:"): -1].strip()

                absolute_filepath = os.path.abspath(filepath)
                filename = os.path.basename(filepath)

                if os.path.exists(absolute_filepath):
                    safe_filepath = absolute_filepath.replace("\\", "/")
                    if is_image_tag:
                        current_message_parts.append(f"![{filename}](/file={safe_filepath})")
                    else:
                        current_message_parts.append(f"[{filename}](/file={safe_filepath})")
                else:
                    current_message_parts.append(f"*[表示エラー: ファイル '{filename}' が見つかりません]*")
            else:
                formatted_text = format_response_for_display(part) if role == "assistant" else part
                if formatted_text:
                    current_message_parts.append(formatted_text)

        if current_message_parts:
            final_content = "\n\n".join(current_message_parts)
            gradio_history.append({"role": role, "content": final_content})

    return gradio_history

def save_message_to_log(log_file_path: str, header: str, text_content: str) -> None:
    if not log_file_path or not header or not text_content or not text_content.strip():
        return
    try:
        # 書き込み前にファイル終端が改行2つで終わっているか確認
        needs_leading_newline = False
        if os.path.exists(log_file_path):
            if os.path.getsize(log_file_path) > 0:
                 with open(log_file_path, "rb") as f:
                    try:
                        f.seek(-2, os.SEEK_END)
                        if f.read(2) != b'\n\n':
                            needs_leading_newline = True
                    except OSError: # ファイルが2バイト未満の場合
                        f.seek(0)
                        if f.read() != b'':
                             needs_leading_newline = True

        with open(log_file_path, "a", encoding="utf-8") as f:
            if needs_leading_newline:
                f.write("\n\n")
            f.write(f"{header}\n{text_content.strip()}")

    except Exception as e:
        print(f"エラー: ログファイル '{log_file_path}' 書き込みエラー: {e}")
        traceback.print_exc()


def delete_message_from_log(log_file_path: str, message_to_delete: Dict[str, str]) -> bool:
    if not log_file_path or not os.path.exists(log_file_path) or not message_to_delete: return False
    content_from_ui = message_to_delete.get("content", "");
    if not content_from_ui: return False

    try:
        with open(log_file_path, "r", encoding="utf-8") as f: original_log_content = f.read()
        
        log_entries = re.split(r'(^## .*?:$)', original_log_content, flags=re.MULTILINE)
        new_log_entries = []
        found_and_deleted = False

        search_targets = []; md_link_pattern = re.compile(r"!*\[.*?\]\(/file=(.*?)\)")
        md_matches = md_link_pattern.findall(content_from_ui)
        if md_matches:
            for filepath in md_matches:
                normalized_path = os.path.normpath(filepath)
                search_targets.append(f"[Generated Image: {normalized_path}]")
                search_targets.append(f"[ファイル添付: {normalized_path}]")
        else:
            cleaned_text = re.sub(r"<div class='thoughts'>.*?</div>\n\n", "", content_from_ui, flags=re.DOTALL)
            search_targets.append(cleaned_text.strip())

        i = 1 if log_entries and log_entries[0] == '' else 0
        while i < len(log_entries):
            header = log_entries[i]; content_from_log = log_entries[i+1].strip()
            is_match = any(target in content_from_log for target in search_targets)
            if is_match and not found_and_deleted:
                found_and_deleted = True
                print(f"--- ログからメッセージを削除: {content_from_log[:50]}... ---")
            else:
                new_log_entries.append(header); new_log_entries.append(log_entries[i+1])
            i += 2

        if not found_and_deleted:
            print(f"警告: ログファイル内に削除対象のメッセージが見つかりませんでした。UI Content: {content_from_ui[:50]}...")
            return False

        new_log_content = "".join(new_log_entries).strip()
        with open(log_file_path, "w", encoding="utf-8") as f: f.write(new_log_content)
        if new_log_content:
            with open(log_file_path, "a", encoding="utf-8") as f: f.write("\n\n")

        return True
    except Exception as e:
        print(f"エラー: ログからのメッセージ削除中にエラーが発生: {e}"); traceback.print_exc(); return False


def _get_user_header_from_log(log_file_path: str, ai_character_name: str) -> str:
    default_user_header = "## ユーザー:"
    if not log_file_path or not os.path.exists(log_file_path): return default_user_header
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
        print(f"エラー: ユーザーヘッダー取得エラー: {e}"); return default_user_header


def remove_thoughts_from_text(text: str) -> str:
    if not text: return ""
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
