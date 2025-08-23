# [batch_importer.py を、この内容で完全に置き換える]
import os
import sys
import json
import argparse
import time
import re
from typing import List, Dict
import logging
import logging.config
from pathlib import Path
from sys import stdout
from datetime import datetime
import traceback

# --- [ロギング設定] ---
LOGS_DIR = Path(os.getenv("MEMOS_BASE_PATH", Path.cwd())) / ".memos" / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE_PATH = LOGS_DIR / "importer.log" # ログファイル名を importer.log に変更

LOGGING_CONFIG = {
    "version": 1, "disable_existing_loggers": False,
    "formatters": { "standard": { "format": "%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(funcName)s - %(message)s" } },
    "handlers": {
        "console": { "level": "INFO", "class": "logging.StreamHandler", "stream": stdout, "formatter": "standard" },
        "file": {
            "level": "DEBUG", "class": "concurrent_log_handler.ConcurrentRotatingFileHandler",
            "filename": LOG_FILE_PATH, "maxBytes": 1024 * 1024 * 10, "backupCount": 5,
            "formatter": "standard", "use_gzip": True,
        },
    },
    "root": { "level": "DEBUG", "handlers": ["console", "file"] },
    "loggers": {
        "memos": { "level": "WARNING", "propagate": True },
        "gradio": { "level": "WARNING", "propagate": True },
        "httpx": { "level": "WARNING", "propagate": True },
        "neo4j": { "level": "WARNING", "propagate": True },
    },
}
logging.config.dictConfig(LOGGING_CONFIG)
logging.config.dictConfig = lambda *args, **kwargs: None
print("--- [Nexus Ark Importer] ロギング設定を完全に掌握しました (ログファイル: importer.log) ---")


# --- [インポート文] ---
import config_manager
import memos_manager
import room_manager

# --- [定数とヘルパー関数] ---
PROGRESS_FILE = "importer_progress.json"
ERROR_LOG_FILE = "importer_errors.log"
STOP_SIGNAL_FILE = "stop_importer.signal"

def load_archived_log(log_content: str, all_room_list: List[str]) -> List[Dict[str, str]]:
    messages = []
    log_parts = re.split(r'^(## .*?:)$', log_content, flags=re.MULTILINE)
    header = None
    for part in log_parts:
        part_strip = part.strip()
        if not part_strip: continue
        if part_strip.startswith("## ") and part_strip.endswith(":"): header = part_strip
        elif header:
            content = part_strip
            if content:
                match = re.match(r"^## (.*?):$", header)
                if match:
                    speaker = match.group(1).strip()
                    # speakerがall_room_listに含まれているか、または"システム"で始まる場合はassistantロール
                    role = "assistant" if speaker in all_room_list or speaker.startswith("システム") else "user"
                    messages.append({"role": role, "content": content})
            header = None
    return messages

def group_messages_into_pairs(messages: List[Dict[str, str]]) -> List[List[Dict[str, str]]]:
    pairs = []
    i = 0
    while i < len(messages):
        if messages[i]["role"] == "user" and messages[i].get("content"):
            if i + 1 < len(messages) and messages[i+1]["role"] == "assistant" and messages[i+1].get("content"):
                pairs.append([messages[i], messages[i+1]])
                i += 2
                continue
        i += 1
    return pairs

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except (json.JSONDecodeError, IOError): return {}
    return {}

def save_progress(progress_data):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress_data, f, indent=2, ensure_ascii=False)

def log_error(filename: str, pair_index: int, pair: List[Dict[str,str]], error: Exception):
    """失敗したペアの情報をエラーログに記録する"""
    with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"--- ERROR at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        f.write(f"File: {filename}\n")
        f.write(f"Pair Index: {pair_index}\n")
        f.write("Pair Content:\n")
        json.dump(pair, f, indent=2, ensure_ascii=False)
        f.write("\nError Details:\n")
        f.write(str(error) + "\n")
        f.write("-" * 20 + "\n\n")

def main():
    # --- 正常終了時も異常終了時も、必ず最後に実行される後処理 ---
    def final_cleanup(progress_data, character_name, character_progress):
        if character_progress:
            print(f"最終結果: {character_progress.get('total_success_count', 0)}件の会話を記憶しました。")
            progress_data[character_name] = character_progress
            save_progress(progress_data)
            print("\n--- 最終的な進捗を importer_progress.json に保存しました。 ---")

        if os.path.exists(ERROR_LOG_FILE):
            print(f"★★★ いくつかのエラーが発生しました。詳細は {ERROR_LOG_FILE} を確認してください。 ★★★")

        if os.path.exists(STOP_SIGNAL_FILE):
            os.remove(STOP_SIGNAL_FILE)

        print("インポーターを終了します。")

    # --- main関数の本体 ---
    if os.path.exists(STOP_SIGNAL_FILE):
        os.remove(STOP_SIGNAL_FILE)

    config_manager.load_config()
    parser = argparse.ArgumentParser(description="Nexus Arkの過去ログをMemOSに一括インポートするツール")
    parser.add_argument("--character", required=True, help="対象のルーム名（フォルダ名）")
    parser.add_argument("--logs-dir", required=True, help="過去ログファイル（.txt）が格納されているディレクトリのパス")
    args = parser.parse_args()

    progress_data = load_progress()
    character_progress = progress_data.get(args.character, {"progress": {}, "total_success_count": 0})

    try:
        processing_should_be_stopped = False
        all_rooms = room_manager.get_room_list()
        print(f"--- 認識している有効なルーム一覧: {all_rooms} ---")
        mos_instance = memos_manager.get_mos_instance(args.character)
        log_files = sorted([f for f in os.listdir(args.logs_dir) if f.endswith(".txt") and not f.endswith("_summary.txt")])
        print(f"--- {len(log_files)}個のログファイルを検出しました。インポート処理を開始します。 ---")

        for i, filename in enumerate(log_files):
            print(f"\n[{i+1}/{len(log_files)}] ファイル処理開始: {filename}")

            if os.path.exists(STOP_SIGNAL_FILE):
                print("--- 中断要求を検知しました。処理を安全に終了します。 ---")
                processing_should_be_stopped = True
                break

            processed_pairs_count = character_progress["progress"].get(filename, 0)

            filepath = os.path.join(args.logs_dir, filename)
            with open(filepath, "r", encoding="utf-8", errors='ignore') as f: content = f.read()
            all_messages = load_archived_log(content, all_rooms)
            conversation_pairs = group_messages_into_pairs(all_messages)
            total_pairs_in_file = len(conversation_pairs)

            if processed_pairs_count >= total_pairs_in_file:
                print(f"  - ファイルは完全に処理済みです。スキップします。")
                continue

            print(f"  - {total_pairs_in_file} 件の会話ペアを検出。{processed_pairs_count + 1}件目から処理を開始します...")

            pair_idx = processed_pairs_count
            while pair_idx < total_pairs_in_file:
                if os.path.exists(STOP_SIGNAL_FILE):
                    print("--- 中断要求を検知しました。現在のファイルの進捗を保存して終了します。 ---")
                    processing_should_be_stopped = True
                    break

                pair = conversation_pairs[pair_idx]

                # ▼▼▼【ここからが修正の核心】▼▼▼
                try:
                    # 1ペアの処理を試みる
                    mos_instance.add(messages=pair)
                    # 成功した場合のみ、進捗を更新する
                    character_progress["total_success_count"] += 1
                    character_progress["progress"][filename] = pair_idx + 1
                    print(f"\r    - 進捗: {pair_idx + 1}/{total_pairs_in_file}", end="")
                    sys.stdout.flush()
                    progress_data[args.character] = character_progress
                    save_progress(progress_data)

                except Exception as e:
                    # 例外が発生した場合、進捗は更新せず、エラーを記録してループを抜ける
                    error_str = str(e)
                    print(f"\n\n" + "="*60)
                    print(f"!!! [回復不能なエラー] ファイル '{filename}' の会話ペア {pair_idx + 1} の記憶中に問題が発生しました。")
                    print(f"    詳細: {error_str}")
                    log_error(filename, pair_idx + 1, pair, e)
                    print("\n    処理を安全に中断しました。進捗はエラー発生前の状態で保存されています。")
                    print("    このペアをスキップするには、importer_progress.json を手動で編集し、")
                    print(f"    '{filename}' の値を {pair_idx + 1} に変更してから再開してください。")
                    print("="*60 + "\n")
                    processing_should_be_stopped = True
                    break # ペア処理ループを抜ける
                # ▲▲▲【修正ここまで】▲▲▲

                pair_idx += 1
                time.sleep(1.1)

            if processing_should_be_stopped:
                break

        if not processing_should_be_stopped:
            print("\n--- 全てのログファイルのインポートが完了しました。 ---")

    except Exception as e:
        error_message = str(e).encode(sys.stdout.encoding, errors='replace').decode(sys.stdout.encoding)
        print(f"\n[致命的エラー] 予期せぬエラーが発生しました: {e}")
        traceback.print_exc()
    finally:
        final_cleanup(progress_data, args.character, character_progress)

if __name__ == "__main__":
    main()
