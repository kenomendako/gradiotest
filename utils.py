# utils.py (完全最終版)

import datetime
import os
import re
import traceback
import html
from typing import List, Dict, Optional, Tuple, Union
import gradio as gr
import character_manager
import config_manager # config_managerをインポート
import constants
import sys
import psutil
from pathlib import Path
import json
import time
import uuid
from bs4 import BeautifulSoup
import io                 # <--- この行を追加
import contextlib         # <--- この行を追加

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
            if header == ai_header:
                role = 'model'
            else:
                role = 'user'
            messages.append({"role": role, "content": part})
            header = None
    return messages

def format_history_for_gradio(raw_history: List[Dict[str, str]], character_name: str) -> Tuple[List[Tuple[Union[str, Tuple, None], Union[str, Tuple, None]]], List[int]]:
    if not raw_history:
        return [], []

    gradio_history = []
    mapping_list = []
    image_tag_pattern = re.compile(r"\[Generated Image: (.*?)\]")

    intermediate_list = []
    # ▼▼▼ 修正の核心 ▼▼▼
    # enumerateは渡されたraw_history(既にスライスされている)に対するインデックス(0, 1, 2...)を返すため、
    # original_indexは常に「表示されているログの中での」正しい座標になる。
    for i, msg in enumerate(raw_history):
    # ▲▲▲ 修正ここまで ▲▲▲
        content = msg.get("content", "").strip()
        if not content: continue

        last_end = 0
        for match in image_tag_pattern.finditer(content):
            if match.start() > last_end:
                intermediate_list.append({"type": "text", "role": msg["role"], "content": content[last_end:match.start()].strip(), "original_index": i})
            intermediate_list.append({"type": "image", "role": "model", "content": match.group(1).strip(), "original_index": i})
            last_end = match.end()
        if last_end < len(content):
            intermediate_list.append({"type": "text", "role": msg["role"], "content": content[last_end:].strip(), "original_index": i})

    text_parts_with_anchors = []
    for item in intermediate_list:
        if item["type"] == "text" and item["content"]:
            item["anchor_id"] = f"msg-anchor-{uuid.uuid4().hex[:8]}"
            text_parts_with_anchors.append(item)

    text_part_index = 0
    for item in intermediate_list:
        if not item["content"]: continue

        if item["type"] == "text":
            prev_anchor = text_parts_with_anchors[text_part_index - 1]["anchor_id"] if text_part_index > 0 else None
            next_anchor = text_parts_with_anchors[text_part_index + 1]["anchor_id"] if text_part_index < len(text_parts_with_anchors) - 1 else None

            html_content = _format_text_content_for_gradio(item["content"], item["anchor_id"], prev_anchor, next_anchor)

            if item["role"] == "user":
                gradio_history.append((html_content, None))
            else:
                gradio_history.append((None, html_content))

            mapping_list.append(item["original_index"])
            text_part_index += 1

        elif item["type"] == "image":
            filepath = item["content"]
            filename = os.path.basename(filepath)
            gradio_history.append((None, (filepath, filename)))
            mapping_list.append(item["original_index"])

    return gradio_history, mapping_list

def _format_text_content_for_gradio(content: str, current_anchor_id: str, prev_anchor_id: Optional[str], next_anchor_id: Optional[str]) -> str:
    # ▼▼▼ この行を修正 ▼▼▼
    up_button = f"<a href='#{current_anchor_id}' class='message-nav-link' title='この発言の先頭へ' style='padding: 1px 6px; font-size: 1.2em; text-decoration: none; color: #AAA;'>▲</a>"
    down_button = f"<a href='#{next_anchor_id}' class='message-nav-link' title='次の発言へ' style='padding: 1px 6px; font-size: 1.2em; text-decoration: none; color: #AAA;'>▼</a>" if next_anchor_id else ""
    delete_icon = "<span title='この発言を削除するには、メッセージ本文をクリックして選択してください' style='padding: 1px 6px; font-size: 1.0em; color: #555; cursor: pointer;'>🗑️</span>"

    button_container = f"<div style='text-align: right; margin-top: 8px;'>{up_button} {down_button} <span style='margin: 0 4px;'></span> {delete_icon}</div>"

    thoughts_pattern = re.compile(r"【Thoughts】(.*?)【/Thoughts】", re.DOTALL | re.IGNORECASE)
    thought_match = thoughts_pattern.search(content)

    final_parts = [f"<span id='{current_anchor_id}'></span>"]

    if thought_match:
        thoughts_content = thought_match.group(1).strip()
        escaped_thoughts = html.escape(thoughts_content).replace('\n', '<br>')
        final_parts.append(f"<div class='thoughts'>{escaped_thoughts}</div>")

    main_text = thoughts_pattern.sub("", content).strip()
    escaped_text = html.escape(main_text).replace('\n', '<br>')
    final_parts.append(f"<div>{escaped_text}</div>")

    final_parts.append(button_container)

    return "".join(final_parts)

def _perform_log_archiving(log_file_path: str, character_name: str) -> Optional[str]:
    """ログファイルのサイズをチェックし、必要であればアーカイブを実行する"""
    try:
        # configから閾値を取得
        # ▼▼▼ 以下の2行を修正 ▼▼▼
        threshold_bytes = config_manager.CONFIG_GLOBAL.get("log_archive_threshold_mb", 10) * 1024 * 1024
        keep_bytes = config_manager.CONFIG_GLOBAL.get("log_keep_size_mb", 5) * 1024 * 1024
        # ▲▲▲ 修正ここまで ▲▲▲

        if os.path.getsize(log_file_path) <= threshold_bytes:
            return None # 閾値以下なので何もしない

        print(f"--- [ログアーカイブ開始] {log_file_path} が {threshold_bytes / 1024 / 1024:.1f}MB を超えました ---")

        with open(log_file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 正規表現でメッセージのペアを分割
        log_parts = re.split(r'^(## .*?:)$', content, flags=re.MULTILINE)

        messages = []
        header = None
        for part in log_parts:
            part_strip = part.strip()
            if not part_strip: continue
            if part_strip.startswith("## ") and part_strip.endswith(":"):
                header = part
            elif header:
                messages.append(header + part)
                header = None

        # 末尾から保持サイズ分のメッセージを探す
        current_size = 0
        split_index = len(messages)
        for i in range(len(messages) - 1, -1, -1):
            current_size += len(messages[i].encode('utf-8'))
            if current_size >= keep_bytes:
                # ユーザー入力から始まるように、AI応答の次で分割する
                if messages[i].strip().startswith(f"## {character_name}:"):
                    split_index = i + 1
                else:
                    split_index = i
                break

        if split_index >= len(messages) or split_index == 0:
            print("--- [ログアーカイブ] 適切な分割点が見つからなかったため、処理を中断しました ---")
            return None

        content_to_archive = "".join(messages[:split_index])
        content_to_keep = "".join(messages[split_index:])

        # アーカイブファイルに書き出す
        archive_dir = os.path.join(os.path.dirname(log_file_path), "log_archives")
        os.makedirs(archive_dir, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_path = os.path.join(archive_dir, f"log_archive_{timestamp}.txt")

        with open(archive_path, "w", encoding="utf-8") as f:
            f.write(content_to_archive.strip())

        # 元のログファイルに上書きする
        with open(log_file_path, "w", encoding="utf-8") as f:
            f.write(content_to_keep.strip() + "\n\n")

        archive_size_mb = os.path.getsize(archive_path) / 1024 / 1024
        message = f"古いログをアーカイブしました ({archive_size_mb:.2f}MB)"
        print(f"--- [ログアーカイブ完了] {message} -> {archive_path} ---")
        return message

    except Exception as e:
        print(f"!!! [ログアーカイブエラー] {e}")
        traceback.print_exc()
        return None


# ▼▼▼ save_message_to_log 関数を、この新しいバージョンに置き換えてください ▼▼▼
def save_message_to_log(log_file_path: str, header: str, text_content: str) -> Optional[str]:
    """メッセージをログに保存し、その後アーカイブ処理を呼び出す。アーカイブが発生した場合はメッセージを返す。"""
    if not all([log_file_path, header, text_content, text_content.strip()]):
        return None
    try:
        # 書き込みロジックをよりシンプルで確実に
        content_to_append = f"{header.strip()}\n{text_content.strip()}\n\n"

        # ファイルが空の場合、先頭の空行を防ぐ
        if not os.path.exists(log_file_path) or os.path.getsize(log_file_path) == 0:
             content_to_append = content_to_append.lstrip()

        with open(log_file_path, "a", encoding="utf-8") as f:
            f.write(content_to_append)

        # 書き込み後にアーカイブ処理を呼び出す
        character_name = os.path.basename(os.path.dirname(log_file_path))
        return _perform_log_archiving(log_file_path, character_name)

    except Exception as e:
        print(f"エラー: ログファイル '{log_file_path}' 書き込みエラー: {e}")
        traceback.print_exc()
        return None

def delete_message_from_log(log_file_path: str, message_to_delete: Dict[str, str], character_name: str) -> bool:
    if not log_file_path or not os.path.exists(log_file_path) or not message_to_delete:
        return False

    try:
        all_messages = load_chat_log(log_file_path, character_name)

        try:
            all_messages.remove(message_to_delete)
        except ValueError:
            print(f"警告: ログファイル内に削除対象のメッセージが見つかりませんでした。")
            print(f"  - 検索対象: {message_to_delete}")
            return False

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
        print(f"エラー: ログからのメッセージ削除中に予期せぬエラー: {e}")
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

def extract_raw_text_from_html(html_content: Union[str, tuple, None]) -> str:
    if not html_content or not isinstance(html_content, str):
        return ""

    soup = BeautifulSoup(html_content, 'html.parser')

    thoughts_text = ""
    thoughts_div = soup.find('div', class_='thoughts')
    if thoughts_div:
        for br in thoughts_div.find_all("br"): br.replace_with("\n")
        thoughts_content = thoughts_div.get_text()
        if thoughts_content: thoughts_text = f"【Thoughts】\n{thoughts_content.strip()}\n【/Thoughts】\n\n"
        thoughts_div.decompose()

    for nav_div in soup.find_all('div', style=lambda v: v and 'text-align: right' in v): nav_div.decompose()
    for anchor_span in soup.find_all('span', id=lambda v: v and v.startswith('msg-anchor-')): anchor_span.decompose()

    for br in soup.find_all("br"): br.replace_with("\n")
    main_text = soup.get_text()

    return (thoughts_text + main_text).strip()


# ▼▼▼ ここからが追加箇所（ファイルの一番下） ▼▼▼
def load_scenery_cache(character_name: str) -> dict:
    """指定されたキャラクターの情景キャッシュファイルを安全に読み込む。"""
    if not character_name: return {}
    cache_path = os.path.join(constants.CHARACTERS_DIR, character_name, "cache", "scenery.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                content = f.read()
                if not content.strip(): return {}
                data = json.loads(content)
                return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, IOError): return {}
    return {}

def save_scenery_cache(character_name: str, cache_key: str, location_name: str, scenery_text: str):
    """指定されたキャラクターの情景キャッシュファイルに、新しいキーでデータを保存する。"""
    if not character_name or not cache_key: return
    cache_path = os.path.join(constants.CHARACTERS_DIR, character_name, "cache", "scenery.json")
    try:
        existing_cache = load_scenery_cache(character_name)
        data_to_save = {
            "location_name": location_name,
            "scenery_text": scenery_text,
            "timestamp": datetime.datetime.now().isoformat()
        }
        existing_cache[cache_key] = data_to_save
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(existing_cache, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"!! エラー: 情景キャッシュの保存に失敗しました: {e}")
# ▲▲▲ 追加箇所ここまで ▲▲▲


def get_season(month: int) -> str:
    """月情報から季節を返す"""
    if month in [3, 4, 5]: return "spring"
    if month in [6, 7, 8]: return "summer"
    if month in [9, 10, 11]: return "autumn"
    return "winter"

def get_time_of_day(hour: int) -> str:
    """時間情報から時間帯を返す"""
    if 5 <= hour < 10: return "morning"
    if 10 <= hour < 17: return "daytime"
    if 17 <= hour < 21: return "evening"
    return "night"

def find_scenery_image(character_name: str, location_id: str) -> Optional[str]:
    """
    指定された場所・季節・時間帯に一致する情景画像を検索する。
    """
    if not character_name or not location_id:
        return None

    image_dir = os.path.join(constants.CHARACTERS_DIR, character_name, "spaces", "images")
    if not os.path.isdir(image_dir):
        return None

    now = datetime.datetime.now()
    current_season = get_season(now.month)
    current_time_of_day = get_time_of_day(now.hour)

    # 1. 完全に一致するファイル名を探す (場所_季節_時間帯.png)
    target_filename = f"{location_id}_{current_season}_{current_time_of_day}.png"
    target_path = os.path.join(image_dir, target_filename)
    if os.path.exists(target_path):
        print(f"--- 最適な情景画像を発見 (完全一致): {target_path} ---")
        return target_path

    # 2. 見つからなければ、時間帯を無視して探す (場所_季節_*.png)
    try:
        for filename in os.listdir(image_dir):
            if filename.startswith(f"{location_id}_{current_season}_") and filename.lower().endswith('.png'):
                found_path = os.path.join(image_dir, filename)
                print(f"--- 最適な情景画像を発見 (季節一致): {found_path} ---")
                return found_path
    except FileNotFoundError:
        pass

    # 3. それでも見つからなければ、場所名だけで探す (場所.png または 場所_*.png)
    try:
        # まず 場所.png を探す
        fallback_path = os.path.join(image_dir, f"{location_id}.png")
        if os.path.exists(fallback_path):
            print(f"--- 最適な情景画像を発見 (場所一致): {fallback_path} ---")
            return fallback_path
        # 次に 場所_*.png を探す
        for filename in os.listdir(image_dir):
            if filename.startswith(f"{location_id}_") and filename.lower().endswith('.png'):
                found_path = os.path.join(image_dir, filename)
                print(f"--- 最適な情景画像を発見 (場所一致): {found_path} ---")
                return found_path
    except FileNotFoundError:
        pass

    return None

def parse_world_file(file_path: str) -> dict:
    if not os.path.exists(file_path):
        return {}

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    world_data = {}
    current_area_key = None
    current_place_key = None

    lines = content.split('\n')

    for line in lines:
        line_strip = line.strip()
        if line_strip.startswith("## "):
            current_area_key = line_strip[3:].strip()
            if current_area_key not in world_data:
                world_data[current_area_key] = {}
            current_place_key = None # エリアが変わったら場所はリセット
        elif line_strip.startswith("### "):
            if current_area_key:
                current_place_key = line_strip[4:].strip()
                world_data[current_area_key][current_place_key] = ""
            else:
                print(f"警告: エリアが定義される前に場所 '{line_strip}' が見つかりました。")
        else:
            if current_area_key and current_place_key:
                # 既存の内容に追記する
                if world_data[current_area_key][current_place_key]:
                     world_data[current_area_key][current_place_key] += "\n" + line
                else:
                     world_data[current_area_key][current_place_key] = line

    # 最後に各テキストの余分な空白を掃除
    for area, places in world_data.items():
        for place, text in places.items():
            world_data[area][place] = text.strip()

    return world_data

def delete_and_get_previous_user_input(log_file_path: str, ai_message_to_delete: Dict[str, str], character_name: str) -> Optional[str]:
    """
    指定されたAIのメッセージと、その直前のユーザーのメッセージをログから削除し、
    そのユーザーメッセージの内容を返す。
    """
    if not all([log_file_path, os.path.exists(log_file_path), ai_message_to_delete, character_name]):
        return None

    try:
        all_messages = load_chat_log(log_file_path, character_name)

        # 削除対象のAIメッセージのインデックスを探す
        try:
            target_index = all_messages.index(ai_message_to_delete)
        except ValueError:
            print(f"警告: ログファイル内に削除対象のAIメッセージが見つかりませんでした。")
            return None

        # AIのメッセージがリストの先頭にある、またはその直前がユーザーメッセージでない場合はエラー
        if target_index == 0 or all_messages[target_index - 1].get("role") != "user":
            print(f"警告: 削除対象のAIメッセージの直前に、対応するユーザーメッセージが見つかりません。")
            # この場合、AIのメッセージだけを削除する
            all_messages.pop(target_index)
            restored_input = None # ユーザー入力は復元できない
        else:
            # AIのメッセージと、その直前のユーザーメッセージを両方削除
            user_message = all_messages.pop(target_index - 1)
            all_messages.pop(target_index - 1) # インデックスがずれるので再度同じインデックスを削除
            restored_input = user_message.get("content")

        # ログファイルを再構築して書き込む
        log_content_parts = []
        user_header = _get_user_header_from_log(log_file_path, character_name)
        ai_header = f"## {character_name}:"

        for msg in all_messages:
            header = ai_header if msg.get('role') in ['model', 'assistant'] else user_header
            content = msg.get('content', '').strip()
            if content:
                log_content_parts.append(f"{header}\n{content}")

        new_log_content = "\n\n".join(log_content_parts)
        with open(log_file_path, "w", encoding="utf-8") as f:
            f.write(new_log_content)

        # ファイルの末尾に空行を追加しておく
        if new_log_content:
            with open(log_file_path, "a", encoding="utf-8") as f:
                f.write("\n\n")

        print("--- Successfully deleted message pair for rerun ---")
        return restored_input

    except Exception as e:
        print(f"エラー: 再生成のためのログ削除中に予期せぬエラー: {e}")
        traceback.print_exc()
        return None

@contextlib.contextmanager
def capture_prints():
    """
    withブロック内のすべてのprint文（標準出力・標準エラー出力）を捕捉するコンテキストマネージャ。
    """
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    string_io = io.StringIO()
    sys.stdout = string_io
    sys.stderr = string_io
    try:
        yield string_io
    finally:
        sys.stdout = original_stdout
        sys.stderr = original_stderr
