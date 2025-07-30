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

# (他の関数 ... 変更なし)
_model_token_limits_cache: Dict[str, Dict[str, int]] = {}
LOCK_FILE_PATH = Path.home() / ".nexus_ark.global.lock"
def acquire_lock() -> bool:
    print("--- グローバル・ロックの取得を試みます ---")
    try:
        if not LOCK_FILE_PATH.exists(): _create_lock_file(); print("--- ロックを取得しました (新規作成) ---"); return True
        with open(LOCK_FILE_PATH, "r", encoding="utf-8") as f: lock_info = json.load(f)
        pid = lock_info.get('pid')
        if pid and psutil.pid_exists(pid): print("\n" + "="*60); print("!!! エラー: Nexus Arkの別プロセスが既に実行中です。"); print(f"    - 実行中のPID: {pid}"); print(f"    - パス: {lock_info.get('path', '不明')}"); print("    多重起動はできません。既存のプロセスを終了するか、"); print("    タスクマネージャーからプロセスを強制終了してください。"); print("="*60 + "\n"); return False
        else: print("\n" + "!"*60); print("警告: 古いロックファイルを検出しました。"); print(f"  - 記録されていたPID: {pid or '不明'} (このプロセスは現在実行されていません)"); print("  古いロックファイルを自動的に削除して、処理を続行します。"); print("!"*60 + "\n"); LOCK_FILE_PATH.unlink(); time.sleep(0.5); _create_lock_file(); print("--- ロックを取得しました (自動クリーンアップ後) ---"); return True
    except (json.JSONDecodeError, IOError) as e:
        print(f"警告: ロックファイル '{LOCK_FILE_PATH}' が破損しているようです。エラー: {e}"); print("破損したロックファイルを削除して、処理を続行します。")
        try: LOCK_FILE_PATH.unlink(); time.sleep(0.5); _create_lock_file(); print("--- ロックを取得しました (破損ファイル削除後) ---"); return True
        except Exception as delete_e: print(f"!!! エラー: 破損したロックファイルの削除に失敗しました: {delete_e}"); return False
    except Exception as e: print(f"!!! エラー: ロック処理中に予期せぬ問題が発生しました: {e}"); traceback.print_exc(); return False
def _create_lock_file():
    with open(LOCK_FILE_PATH, "w", encoding="utf-8") as f: json.dump({"pid": os.getpid(), "path": os.path.abspath(os.path.dirname(__file__))}, f)
def release_lock():
    try:
        if not LOCK_FILE_PATH.exists(): return
        with open(LOCK_FILE_PATH, "r", encoding="utf-8") as f: lock_info = json.load(f)
        if lock_info.get('pid') == os.getpid(): LOCK_FILE_PATH.unlink(); print("\n--- グローバル・ロックを解放しました ---")
        else: print(f"\n警告: 自分のものではないロックファイル (PID: {lock_info.get('pid')}) を解放しようとしましたが、スキップしました。")
    except Exception as e: print(f"\n警告: ロックファイルの解放中にエラーが発生しました: {e}")
def load_chat_log(file_path: str, character_name: str) -> List[Dict[str, str]]:
    messages: List[Dict[str, str]] = [];
    if not character_name or not file_path or not os.path.exists(file_path): return messages
    ai_header = f"## {character_name}:"; alarm_header = "## システム(アラーム):"
    try:
        with open(file_path, "r", encoding="utf-8") as f: content = f.read()
    except Exception as e: print(f"エラー: ログファイル '{file_path}' 読込エラー: {e}"); return messages
    log_parts = re.split(r'^(## .*?:)$', content, flags=re.MULTILINE); header = None
    for part in log_parts:
        part = part.strip()
        if not part: continue
        if part.startswith("## ") and part.endswith(":"): header = part
        elif header: role = "model" if header == ai_header else "user"; messages.append({"role": role, "content": part}); header = None
    return messages

# ★★★ 最終版のフォーマット関数 ★★★
def format_history_for_gradio(messages: List[Dict[str, str]]) -> List[Dict[str, Union[str, tuple, None]]]:
    if not messages: return []
    anchor_ids = [f"msg-anchor-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}-{i}" for i, _ in enumerate(messages)]
    gradio_history = []
    tag_pattern = re.compile(r"(\[Generated Image: .*?\]|\[ファイル添付: .*?\])")
    for i, msg in enumerate(messages):
        role = "assistant" if msg.get("role") == "model" else "user"
        content = msg.get("content", "").strip()
        if not content: continue
        current_anchor_id = anchor_ids[i]

        # ★★★ ボタンのHTMLをシンプル化 ★★★
        # スクロールは純粋なhref、削除アイコンはクリックイベントを発火させないようにstyleで調整
        up_button = f"<a href='#{current_anchor_id}' title='この発言の先頭へ' style='padding: 1px 6px; font-size: 1.2em; text-decoration: none; color: #555;'>▲</a>"
        down_button = ""
        if i < len(messages) - 1:
            next_anchor_id = anchor_ids[i+1]
            down_button = f"<a href='#{next_anchor_id}' title='次の発言へ' style='padding: 1px 6px; font-size: 1.2em; text-decoration: none; color: #555;'>▼</a>"

        # 削除アイコンは、クリックイベントを発火させるためのものではなく、単なる視覚的な目印
        delete_icon = "<span title='この発言を削除するには、メッセージをクリックして選択してください' style='padding: 1px 6px; font-size: 1.0em; color: #555; cursor: pointer;'>🗑️</span>"

        button_container = f"<div style='text-align: right; margin-top: 8px;'>{up_button} {down_button} <span style='margin: 0 4px;'></span> {delete_icon}</div>"

        # --- 本文の処理 ---
        thoughts_pattern = re.compile(r"【Thoughts】(.*?)【/Thoughts】", re.DOTALL | re.IGNORECASE)
        parts = tag_pattern.split(content)
        final_content_parts = [f"<span id='{current_anchor_id}'></span>"]
        has_content = False
        for part in parts:
            part = part.strip()
            if not part: continue
            thought_match = thoughts_pattern.search(part)
            is_image_tag = part.startswith("[Generated Image:") and part.endswith("]")
            is_file_tag = part.startswith("[ファイル添付:") and part.endswith("]")
            if thought_match:
                thoughts_content = thought_match.group(1).strip(); escaped_content = html.escape(thoughts_content); content_with_breaks = escaped_content.replace('\n', '<br>')
                final_content_parts.append(f"<div class='thoughts'>{content_with_breaks}</div>")
                main_response_text = thoughts_pattern.sub("", part).strip()
                if main_response_text: final_content_parts.append(f"<div>{main_response_text}</div>")
                has_content = True
            elif is_image_tag or is_file_tag:
                filepath = part[len("[Generated Image:"):-1].strip() if is_image_tag else part[len("[ファイル添付:"):-1].strip()
                absolute_filepath = os.path.abspath(filepath); filename = os.path.basename(filepath)
                if os.path.exists(absolute_filepath): safe_filepath = absolute_filepath.replace("\\", "/"); final_content_parts.append(f"![{filename}](/file={safe_filepath})" if is_image_tag else f"[{filename}](/file={safe_filepath})")
                else: final_content_parts.append(f"*[表示エラー: ファイル '{filename}' が見つかりません]*")
                has_content = True
            elif part: final_content_parts.append(f"<div>{part}</div>"); has_content = True

        if has_content: final_content_parts.append(button_container)
        final_html = f"<div>{''.join(final_content_parts)}</div>"
        gradio_history.append({"role": role, "content": final_html})
    return gradio_history

def save_message_to_log(log_file_path: str, header: str, text_content: str) -> None:
    if not all([log_file_path, header, text_content, text_content.strip()]): return
    try:
        # ファイルの末尾に追記する内容を準備
        # ファイルが存在しないか、空の場合は、先頭の改行は不要
        if not os.path.exists(log_file_path) or os.path.getsize(log_file_path) == 0:
            content_to_append = f"{header}\n{text_content.strip()}"
        else:
            content_to_append = f"\n\n{header}\n{text_content.strip()}"

        # ファイルに追記
        with open(log_file_path, "a", encoding="utf-8") as f:
            f.write(content_to_append)
    except Exception as e: print(f"エラー: ログファイル '{log_file_path}' 書き込みエラー: {e}"); traceback.print_exc()
def delete_message_from_log(log_file_path: str, message_to_delete: Dict[str, str]) -> bool:
    if not log_file_path or not os.path.exists(log_file_path) or not message_to_delete: return False
    content_to_find = message_to_delete.get("content", "").strip()
    if not content_to_find: return False
    try:
        with open(log_file_path, "r", encoding="utf-8") as f: original_log_content = f.read()
        log_entries = re.split(r'(^## .*?:$)', original_log_content, flags=re.MULTILINE)
        new_log_entries = []
        found_and_deleted = False
        i = 1 if log_entries and log_entries[0] == '' else 0
        while i < len(log_entries):
            header = log_entries[i]; content_from_log = log_entries[i+1].strip()
            if content_from_log == content_to_find and not found_and_deleted:
                found_and_deleted = True; print(f"--- ログからメッセージを削除: {content_from_log[:50]}... ---")
            else: new_log_entries.append(header); new_log_entries.append(log_entries[i+1])
            i += 2
        if not found_and_deleted: print(f"警告: ログファイル内に削除対象のメッセージが見つかりませんでした。Content: {content_to_find[:50]}..."); return False
        new_log_content = "".join(new_log_entries).strip()
        with open(log_file_path, "w", encoding="utf-8") as f: f.write(new_log_content)
        if new_log_content:
            with open(log_file_path, "a", encoding="utf-8") as f: f.write("\n\n")
        return True
    except Exception as e: print(f"エラー: ログからのメッセージ削除中にエラーが発生しました: {e}"); traceback.print_exc(); return False
def _get_user_header_from_log(log_file_path: str, ai_character_name: str) -> str:
    default_user_header = "## ユーザー:";
    if not log_file_path or not os.path.exists(log_file_path): return default_user_header
    last_identified_user_header = default_user_header
    try:
        with open(log_file_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped_line = line.strip()
                if stripped_line.startswith("## ") and stripped_line.endswith(":"):
                    if not stripped_line.startswith(f"## {ai_character_name}:") and not stripped_line.startswith("## システム("): last_identified_user_header = stripped_line
        return last_identified_user_header
    except Exception as e: print(f"エラー: ユーザーヘッダー取得エラー: {e}"); return default_user_header
def remove_thoughts_from_text(text: str) -> str:
    if not text: return ""
    thoughts_pattern = re.compile(r"【Thoughts】.*?【/Thoughts】\s*", re.DOTALL | re.IGNORECASE)
    return thoughts_pattern.sub("", text).strip()
def get_current_location(character_name: str) -> Optional[str]:
    try:
        location_file_path = os.path.join("characters", character_name, "current_location.txt")
        if os.path.exists(location_file_path):
            with open(location_file_path, 'r', encoding='utf-8') as f: return f.read().strip()
    except Exception as e: print(f"警告: 現在地ファイルの読み込みに失敗しました: {e}")
    return None

def extract_raw_text_from_html(html_content: str) -> str:
    """
    GradioのChatbotに表示されるHTMLから、元の生テキスト（思考ログやボタンを除く）を抽出する。
    """
    if not html_content:
        return ""
    # ボタンコンテナを削除
    html_content = re.sub(r"<div style='text-align: right;.*?'>.*?</div>", "", html_content, flags=re.DOTALL)
    # 思考ログを削除
    html_content = re.sub(r"<div class='thoughts'>.*?</div>", "", html_content, flags=re.DOTALL)
    # アンカーを削除
    html_content = re.sub(r"<span id='msg-anchor-.*?'></span>", "", html_content, flags=re.DOTALL)
    # 残ったHTMLタグをすべて削除
    raw_text = re.sub('<[^<]+?>', '', html_content).strip()
    return raw_text
