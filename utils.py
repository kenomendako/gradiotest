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
    """
    ログデータをGradioのChatbotが解釈できる形式に変換する。
    画像タグが含まれる場合、テキストと画像のターンを分割する。
    """
    if not messages:
        return []

    gradio_history = []

    # 画像タグを検出するための正規表現
    image_tag_pattern = re.compile(r"\[Generated Image: (.*?)\]")

    for i, msg in enumerate(messages):
        role = "assistant" if msg.get("role") == "model" else "user"
        content = msg.get("content", "").strip()
        if not content:
            continue

        # --- ★★★ ここからが新しいロジック ★★★ ---
        # 1. メッセージに画像タグが含まれているかチェック
        image_matches = list(image_tag_pattern.finditer(content))

        if not image_matches:
            # 1-a. 画像なし：従来通りテキストとして処理
            # 思考ログやボタンは、テキストメッセージにのみ付与する
            processed_html = _format_text_content_for_gradio(content, character_name, i, len(messages))
            gradio_history.append({"role": role, "content": processed_html})
        else:
            # 1-b. 画像あり：テキストと画像に分割して、複数のターンとして追加
            last_index = 0
            # 最初のテキスト部分を処理
            first_text_chunk = content[:image_matches[0].start()].strip()
            if first_text_chunk:
                processed_html = _format_text_content_for_gradio(first_text_chunk, character_name, i, len(messages))
                gradio_history.append({"role": role, "content": processed_html})

            # 画像と、その後のテキストを処理
            for match_idx, match in enumerate(image_matches):
                # 画像をタプル形式で追加
                filepath = match.group(1).strip()
                filename = os.path.basename(filepath)
                # Gradioが最も安定して解釈できるタプル形式
                image_tuple = (filepath, filename)
                gradio_history.append({"role": "assistant", "content": image_tuple})

                # 画像の後のテキスト部分を処理
                start_of_next_chunk = match.end()
                end_of_this_chunk = image_matches[match_idx + 1].start() if match_idx + 1 < len(image_matches) else len(content)
                text_chunk = content[start_of_next_chunk:end_of_this_chunk].strip()
                if text_chunk:
                    processed_html = _format_text_content_for_gradio(text_chunk, character_name, i, len(messages))
                    # 2つ目以降の要素は、必ずAIの発言として追加
                    gradio_history.append({"role": "assistant", "content": processed_html})

    return gradio_history

def _format_text_content_for_gradio(content: str, character_name: str, msg_index: int, total_msgs: int) -> str:
    """
    テキストコンテンツをHTMLにフォーマットする補助関数。
    思考ログの処理、改行の反映、ナビゲーションボタンの追加を行う。
    """
    # アンカーIDを生成
    # NOTE: この方法は複数ターン分割時に同じIDが振られる可能性があるが、
    # 連続したメッセージなので実用上の問題は少ない
    anchor_id = f"msg-anchor-{uuid.uuid4().hex[:8]}-{msg_index}"

    # ナビゲーションボタン
    up_button = f"<a href='#{anchor_id}' class='message-nav-link' title='この発言の先頭へ' style='padding: 1px 6px; font-size: 1.2em; text-decoration: none; color: #AAA;'>▲</a>"
    down_button = ""
    if msg_index < total_msgs - 1:
        # 次のメッセージのアンカーを指すようにする（簡易的な方法）
        next_anchor_id = f"msg-anchor-{uuid.uuid4().hex[:8]}-{msg_index+1}"
        down_button = f"<a href='#{next_anchor_id}' class='message-nav-link' title='次の発言へ' style='padding: 1px 6px; font-size: 1.2em; text-decoration: none; color: #AAA;'>▼</a>"
    delete_icon = "<span title='この発言を削除するには、メッセージ本文をクリックして選択してください' style='padding: 1px 6px; font-size: 1.0em; color: #555; cursor: pointer;'>🗑️</span>"
    button_container = f"<div style='text-align: right; margin-top: 8px;'>{up_button} {down_button} <span style='margin: 0 4px;'></span> {delete_icon}</div>"

    # 思考ログの処理
    thoughts_pattern = re.compile(r"【Thoughts】(.*?)【/Thoughts】", re.DOTALL | re.IGNORECASE)
    thought_match = thoughts_pattern.search(content)

    final_parts = [f"<span id='{anchor_id}'></span>"]

    if thought_match:
        thoughts_content = thought_match.group(1).strip()
        escaped_thoughts = html.escape(thoughts_content)
        thoughts_with_breaks = escaped_thoughts.replace('\n', '<br>')
        final_parts.append(f"<div class='thoughts'>{thoughts_with_breaks}</div>")

    # メインテキストの処理
    main_text = thoughts_pattern.sub("", content).strip()
    escaped_text = html.escape(main_text)
    text_with_breaks = escaped_text.replace('\n', '<br>')
    final_parts.append(f"<div>{text_with_breaks}</div>")

    # ボタンを追加
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

def delete_message_from_log(log_file_path: str, message_to_delete: Dict[str, str], character_name: str) -> bool:
    """
    ログファイルから指定されたメッセージ辞書と完全に一致するエントリを一つ削除する。
    より堅牢な再構築ベースのロジック。
    """
    if not log_file_path or not os.path.exists(log_file_path) or not message_to_delete:
        return False

    try:
        # 1. まず、現在のログを正しいキャラクター名で完全に解析する
        all_messages = load_chat_log(log_file_path, character_name)

        # 2. 削除対象のメッセージと完全に一致するものを探し、リストから削除する
        try:
            # message_to_delete は {'role': '...', 'content': '...'} という辞書
            all_messages.remove(message_to_delete)
        except ValueError:
            # リストに要素が見つからなかった場合
            print(f"警告: ログファイル内に削除対象のメッセージが見つかりませんでした。")
            traceback.print_exc() # デバッグ用に詳細を出力
            return False

        # 3. 変更後のメッセージリストから、ログファイル全体を再構築する
        log_content_parts = []
        user_header = _get_user_header_from_log(log_file_path, character_name)
        ai_header = f"## {character_name}:"

        for msg in all_messages:
            header = ai_header if msg['role'] == 'model' else user_header
            content = msg['content'].strip()
            log_content_parts.append(f"{header}\n{content}")

        # ログファイルに書き込む
        new_log_content = "\n\n".join(log_content_parts)
        with open(log_file_path, "w", encoding="utf-8") as f:
            f.write(new_log_content)

        # ファイルが空でなければ、次の追記のために末尾に改行を追加
        if new_log_content:
            with open(log_file_path, "a", encoding="utf-8") as f:
                f.write("\n\n")

        print(f"--- ログからメッセージを正常に削除しました ---")
        return True

    except Exception as e:
        print(f"エラー: ログからのメッセージ削除中に予期せぬエラーが発生しました: {e}")
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

def delete_message_from_log_by_content(log_file_path: str, content_to_find: str, character_name: str) -> bool:
    """指定された内容を含むメッセージをログから探し、最初に見つかったものを削除する。"""
    if not all([log_file_path, os.path.exists(log_file_path), content_to_find, character_name]):
        return False
    try:
        all_messages = load_chat_log(log_file_path, character_name)
        target_index = -1
        for i, msg in enumerate(all_messages):
            if content_to_find in msg.get("content", ""):
                target_index = i
                break

        if target_index != -1:
            # ユーザーの発言がクリックされた場合は、後続のAIの発言も削除する
            if all_messages[target_index]['role'] == 'user' and (target_index + 1) < len(all_messages):
                delete_message_from_log_by_index(log_file_path, target_index + 1)
            return delete_message_from_log_by_index(log_file_path, target_index)
        else:
            return False
    except Exception as e:
        print(f"内容によるログ削除でエラー: {e}")
        return False

def delete_message_from_log_by_index(log_file_path: str, index_to_delete: int) -> bool:
    """指定されたインデックスのメッセージをログファイルから削除する、安全な再構築版。"""
    if not log_file_path or not os.path.exists(log_file_path) or index_to_delete < 0:
        return False
    try:
        character_name = os.path.basename(os.path.dirname(log_file_path))
        all_messages = load_chat_log(log_file_path, character_name)

        if 0 <= index_to_delete < len(all_messages):
            all_messages.pop(index_to_delete)
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
            return True
        else:
            return False
    except Exception as e:
        print(f"インデックスによるログ削除でエラー: {e}")
        return False

# extract_raw_text_from_html は、念のためここに再掲します。
def extract_raw_text_from_html(html_content: str) -> str:
    if not html_content: return ""
    raw_text = re.sub('<[^<]+?>', '', html_content)
    return html.unescape(raw_text).strip()
