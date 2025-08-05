# utils.py (循環参照解決版)

# 1. ファイル先頭のインポートを修正
import os
import re
import traceback
import html
from typing import List, Dict, Optional, Tuple, Union
import gradio as gr
# import character_manager # <<< この行を完全に削除
import sys
import psutil
from pathlib import Path
import json
import time
import uuid
from bs4 import BeautifulSoup
import yaml # これは外部ライブラリなのでOK
import datetime # 標準ライブラリなのでOK

_model_token_limits_cache: Dict[str, Dict[str, int]] = {}
LOCK_FILE_PATH = Path.home() / ".nexus_ark.global.lock"

# 2. acquire_lock, _create_lock_file, release_lock は変更なし
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

# 4. format_history_for_gradio 関数は変更なし
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

# 5. _format_text_content_for_gradio 関数は変更なし
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

# 6. save_message_to_log 関数は変更なし
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

# 9. remove_thoughts_from_text 関数は変更なし
def remove_thoughts_from_text(text: str) -> str:
    if not text:
        return ""
    thoughts_pattern = re.compile(r"【Thoughts】.*?【/Thoughts】\s*", re.DOTALL | re.IGNORECASE)
    return thoughts_pattern.sub("", text).strip()

# 11. extract_raw_text_from_html 関数は変更なし
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

# 14. parse_world_markdown 関数は変更なし
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
    # 結果は ['(空)', '## area1', 'area1の中身', '## area2', 'area2の中身', ...] というリストになる
    sections = re.split(r'(^## .*)', content, flags=re.MULTILINE)

    # 最初の要素はヘッダー部分なので無視し、2つずつペアで処理する
    for i in range(1, len(sections), 2):
        area_key = sections[i][3:].strip()
        area_content = sections[i+1]

        world_data[area_key] = {}

        # ### でさらに部屋ごとに分割
        sub_sections = re.split(r'(^### .*)', area_content, flags=re.MULTILINE)

        # ### の前にあるエリア直下のプロパティを解析
        area_props_content = sub_sections[0].strip()
        if area_props_content:
            try:
                area_props = yaml.safe_load(area_props_content)
                if isinstance(area_props, dict):
                    world_data[area_key].update(area_props)
            except yaml.YAMLError as e:
                print(f"警告: エリア '{area_key}' のプロパティ解析中にエラー: {e}")

        # 各部屋のセクションを解析
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
