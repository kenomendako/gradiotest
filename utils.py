# utils.py (完全最終版)

import datetime
import os
import re
import traceback
import html
from typing import List, Dict, Optional, Tuple, Union
import gradio as gr
import yaml
import character_manager
import constants
import sys
import psutil
from pathlib import Path
import json
import time
import uuid
from bs4 import BeautifulSoup

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
    up_button = f"<a href='#{prev_anchor_id or current_anchor_id}' class='message-nav-link' title='前の発言へ' style='padding: 1px 6px; font-size: 1.2em; text-decoration: none; color: #AAA;'>▲</a>"
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
    if not character_name:
        return {}
    # ファイル名を last_scenery.json から scenery_cache.json に変更
    cache_path = os.path.join(constants.CHARACTERS_DIR, character_name, "scenery_cache.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                content = f.read()
                if not content.strip(): return {}
                data = json.loads(content)
                return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, IOError):
            return {}
    return {}

def save_scenery_cache(character_name: str, cache_key: str, location_name: str, scenery_text: str):
    """指定されたキャラクターの情景キャッシュファイルに、新しいキーでデータを保存する。"""
    if not character_name or not cache_key:
        return
    # ファイル名を last_scenery.json から scenery_cache.json に変更
    cache_path = os.path.join(constants.CHARACTERS_DIR, character_name, "scenery_cache.json")
    try:
        # 既存のキャッシュを読み込み、新しいデータを追加/更新する
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
    指定された場所・季節・時間帯に最適な情景画像を、動的な部分一致検索で見つけ出す。
    最も一致度の高いファイルパスを返す。
    """
    if not character_name or not location_id:
        return None

    image_dir = os.path.join(constants.CHARACTERS_DIR, character_name, "spaces", "images")
    if not os.path.isdir(image_dir):
        return None

    now = datetime.datetime.now()
    current_season = get_season(now.month)
    current_time_of_day = get_time_of_day(now.hour)

    # ▼▼▼ 新しい検索ロジック ▼▼▼
    candidates = []
    try:
        # 1. ディレクトリ内の全ファイルをスキャンし、場所IDで始まる候補をリストアップ
        for filename in os.listdir(image_dir):
            if filename.startswith(f"{location_id}_") and filename.lower().endswith('.png'):
                candidates.append(filename)
            elif filename == f"{location_id}.png": # 部屋名のみのファイルも候補に含める
                candidates.append(filename)

    except FileNotFoundError:
        return None # ディレクトリが存在しない場合は終了

    if not candidates:
        print(f"  - 適切な情景画像が見つかりませんでした (候補0件)。")
        return None

    best_match = None
    highest_score = -1

    # 2. 候補の中から、最もスコアが高いものを探す
    for filename in candidates:
        score = 0

        # ファイル名を分解して要素を取得
        parts = filename.replace('.png', '').split('_')

        # スコア計算
        if len(parts) >= 3 and parts[1] == current_season and parts[2] == current_time_of_day:
            score = 3 # 完全一致
        elif len(parts) >= 2 and parts[1] == current_season:
            score = 2 # 季節まで一致
        elif len(parts) == 1 and parts[0] == location_id:
            score = 1 # 部屋名のみ一致
        else:
            score = 0 # その他（部屋名で始まっているが命名規則が異なるもの）

        if score > highest_score:
            highest_score = score
            best_match = filename

    if best_match:
        found_path = os.path.join(image_dir, best_match)
        print(f"  - 最適な情景画像を発見 (Score: {highest_score}): {found_path}")
        return found_path
    else:
        print(f"  - 適切な情景画像が見つかりませんでした (一致スコア0)。")
        return None
    # ▲▲▲ 新しい検索ロジックここまで ▲▲▲

def parse_world_markdown(file_path: str) -> dict:
    """
    世界設定が記述されたMarkdownファイルを解析し、ネストされた辞書構造に変換する。
    見出し(##, ###)でセクションを分割し、各セクションをYAMLとして解析する堅牢な方式。
    """
    if not os.path.exists(file_path):
        return {}

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    world_data = {}

    # re.splitのキャプチャグループ `()` を使い、見出し(デリミタ)を保持したまま分割する
    sections = re.split(r'(^## .*)', content, flags=re.MULTILINE)

    for i in range(1, len(sections), 2):
        area_key = sections[i][3:].strip()
        area_content = sections[i+1]

        world_data[area_key] = {}

        sub_sections = re.split(r'(^### .*)', area_content, flags=re.MULTILINE)

        area_props_content = sub_sections[0].strip()
        if area_props_content:
            try:
                area_props = yaml.safe_load(area_props_content)
                if isinstance(area_props, dict):
                    world_data[area_key].update(area_props)
            except yaml.YAMLError as e:
                print(f"警告: エリア '{area_key}' のプロパティ解析中にエラー: {e}")

        for j in range(1, len(sub_sections), 2):
            room_key = sub_sections[j][4:].strip()
            room_content = sub_sections[j+1].strip()
            if room_content:
                try:
                    room_props = yaml.safe_load(room_content)
                    if isinstance(room_props, dict):
                        world_data[area_key][room_key] = room_props
                except yaml.YAMLError as e:
                    print(f"警告: 部屋 '{room_key}' の解析中にエラー: {e}")

    return world_data
