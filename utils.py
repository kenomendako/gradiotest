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


def format_history_for_gradio(messages: List[Dict[str, str]]) -> List[Dict[str, Union[str, tuple, None]]]:
    if not messages:
        return []

    # 1. 全メッセージのアンカーIDを事前に一括生成
    anchor_ids = [f"msg-anchor-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}-{i}" for i, _ in enumerate(messages)]
    gradio_history = []

    # 正規表現パターンの準備 (ファイル・画像タグ用)
    tag_pattern = re.compile(r"(\[Generated Image: .*?\]|\[ファイル添付: .*?\])")

    # 2. 全メッセージをループしてHTMLを構築
    for i, msg in enumerate(messages):
        role = "assistant" if msg.get("role") == "model" else "user"
        content = msg.get("content", "").strip()
        if not content:
            continue

        current_anchor_id = anchor_ids[i]

        # 3. ボタンHTMLの生成
        # ▲ 上へボタン (常に表示)
        up_button = (
            f"<a href='#{current_anchor_id}' title='この発言の先頭へ' "
            f"style='padding: 1px 6px; font-size: 1.2em; text-decoration: none; color: #555;'>▲</a>"
        )
        # ▼ 下へボタン (最後のメッセージ以外で表示)
        down_button = ""
        if i < len(messages) - 1:
            next_anchor_id = anchor_ids[i+1]
            down_button = (
                f"<a href='#{next_anchor_id}' title='次の発言へ' "
                f"style='padding: 1px 6px; font-size: 1.2em; text-decoration: none; color: #555;'>▼</a>"
            )

        # ボタンをまとめるコンテナ
        button_container = (
            f"<div style='text-align: right; margin-top: 8px;'>"
            f"{up_button} {down_button}"
            "</div>"
        )

        # 4. メッセージ本文の処理
        #    思考ログやファイル表示のロジックはここに集約
        thoughts_pattern = re.compile(r"【Thoughts】(.*?)【/Thoughts】", re.DOTALL | re.IGNORECASE)
        parts = tag_pattern.split(content)

        final_content_parts = []
        has_content = False

        # 本文の先頭に目印を設置
        final_content_parts.append(f"<span id='{current_anchor_id}'></span>")

        for part in parts:
            part = part.strip()
            if not part: continue

            # 思考ログの処理
            thought_match = thoughts_pattern.search(part)
            if thought_match:
                thoughts_content = thought_match.group(1).strip()
                escaped_content = html.escape(thoughts_content)
                content_with_breaks = escaped_content.replace('\n', '<br>')
                final_content_parts.append(f"<div class='thoughts'>{content_with_breaks}</div>")
                # 思考ログ部分を本文から削除
                main_response_text = thoughts_pattern.sub("", part).strip()
                if main_response_text:
                    final_content_parts.append(f"<div>{main_response_text}</div>")
                has_content = True
                continue

            # 画像・ファイルタグの処理
            is_image_tag = part.startswith("[Generated Image:") and part.endswith("]")
            is_file_tag = part.startswith("[ファイル添付:") and part.endswith("]")

            if is_image_tag or is_file_tag:
                filepath = part[len("[Generated Image:"):-1].strip() if is_image_tag else part[len("[ファイル添付:"):-1].strip()
                absolute_filepath = os.path.abspath(filepath)
                filename = os.path.basename(filepath)
                if os.path.exists(absolute_filepath):
                    safe_filepath = absolute_filepath.replace("\\", "/")
                    final_content_parts.append(f"![{filename}](/file={safe_filepath})" if is_image_tag else f"[{filename}](/file={safe_filepath})")
                else:
                    final_content_parts.append(f"*[表示エラー: ファイル '{filename}' が見つかりません]*")
                has_content = True
            elif part:
                # 通常のテキスト
                final_content_parts.append(f"<div>{part}</div>")
                has_content = True

        # 応答内容がある場合のみ、末尾にボタンを追加
        if has_content:
            final_content_parts.append(button_container)

        # 全体を1つのdivで囲む
        final_html = f"<div>{''.join(final_content_parts)}</div>"
        gradio_history.append({"role": role, "content": final_html})

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
