# [batch_importer.py を、この内容で完全に置き換える]
import os
import sys
import json
import argparse
import time
import re
from typing import List, Dict, Literal
import logging
import logging.config
from pathlib import Path
from sys import stdout

# --- [ロギング設定] ---
LOGS_DIR = Path(os.getenv("MEMOS_BASE_PATH", Path.cwd())) / ".memos" / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE_PATH = LOGS_DIR / "nexus_ark.log"
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
        "neo4j": { "level": "WARNING", "propagate": True },
        "httpx": { "level": "WARNING", "propagate": True },
        "google_genai": { "level": "WARNING", "propagate": True },
    },
}
logging.config.dictConfig(LOGGING_CONFIG)
logging.config.dictConfig = lambda *args, **kwargs: None
print("--- [Nexus Ark Importer] ロギング設定を完全に掌握しました ---")

import config_manager
import memos_manager
import character_manager

PROGRESS_FILE = "importer_progress.json"

# (load_archived_log, group_messages_into_pairs, load_progress, save_progress 関数は変更なし)
def load_archived_log(log_content: str, all_character_list: List[str]) -> List[Dict[str, str]]:
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
                    role = "assistant" if speaker in all_character_list else "user"
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


# ▼▼▼【ここからが修正の核心】▼▼▼
def process_pair_with_retries(mos_instance, pair: List[Dict[str,str]]) -> Literal["success", "failed_retry", "failed_critical"]:
    """1つの会話ペアを、自動リトライ機能付きで処理する。"""
    retry_count = 0
    max_retries = 3

    while retry_count < max_retries:
        try:
            mos_instance.add(messages=pair)
            return "success" # 成功
        except Exception as e:
            error_str = str(e)
            retry_count += 1

            if "RESOURCE_EXHAUSTED" in error_str or "429" in error_str:
                delay_match = re.search(r"'retryDelay': '(\d+)s'", error_str)
                wait_time = int(delay_match.group(1)) + 1 if delay_match else 20 * retry_count
                print(f"\n    - 警告: APIレートリミット。{wait_time}秒待機してリトライします... ({retry_count}/{max_retries})")
                time.sleep(wait_time)
            elif isinstance(e, AttributeError) and "'NoneType' object" in error_str:
                wait_time = 10 * retry_count
                print(f"\n    - 警告: APIからの応答が不完全 (AttributeError)。{wait_time}秒待機してリトライします... ({retry_count}/{max_retries})")
                time.sleep(wait_time)
            else:
                # 自動リトライ対象外のクリティカルなエラー
                print(f"\n    - エラー: 記憶中に、予期せぬクリティカルなエラーが発生しました。")
                print(f"      詳細: {error_str[:200]}...")
                return "failed_critical"

    # リトライ上限に達した場合
    print(f"\n    - エラー: 自動リトライ上限 ({max_retries}回) に達しました。")
    return "failed_retry"


def main():
    config_manager.load_config()
    parser = argparse.ArgumentParser(description="Nexus Arkの過去ログをMemOSに一括インポートするツール")
    parser.add_argument("--character", required=True, help="対象のキャラクター名")
    parser.add_argument("--logs-dir", required=True, help="過去ログファイル（.txt）が格納されているディレクトリのパス")

    args = parser.parse_args()

    try:
        all_characters = character_manager.get_character_list()
        print(f"--- 認識しているAIキャラクター名簿: {all_characters} ---")
        mos_instance = memos_manager.get_mos_instance(args.character)
        progress_data = load_progress()
        character_progress = progress_data.get(args.character, {"progress": {}, "total_success_count": 0})
        log_files = sorted([f for f in os.listdir(args.logs_dir) if f.endswith(".txt") and not f.endswith("_summary.txt")])

        print(f"--- {len(log_files)}個のログファイルを検出しました。インポート処理を開始します。 ---")

        for i, filename in enumerate(log_files):
            processed_pairs_count = character_progress["progress"].get(filename, 0)
            print(f"\n[{i+1}/{len(log_files)}] ファイル処理開始: {filename}")
            filepath = os.path.join(args.logs_dir, filename)

            with open(filepath, "r", encoding="utf-8", errors='ignore') as f: content = f.read()

            all_messages = load_archived_log(content, all_characters)
            conversation_pairs = group_messages_into_pairs(all_messages)
            total_pairs_in_file = len(conversation_pairs)

            if processed_pairs_count >= total_pairs_in_file:
                print(f"  - ファイルは完全に処理済みです。スキップします。")
                continue

            print(f"  - {total_pairs_in_file} 件の会話ペアを検出。{processed_pairs_count + 1}件目から処理を開始します...")

            pair_idx = processed_pairs_count
            while pair_idx < total_pairs_in_file:
                pair = conversation_pairs[pair_idx]

                result = process_pair_with_retries(mos_instance, pair)

                if result == "success":
                    character_progress["total_success_count"] += 1
                    character_progress["progress"][filename] = pair_idx + 1
                    print(f"\r    - 進捗: {pair_idx + 1}/{total_pairs_in_file}", end="")
                    sys.stdout.flush() # ★★★ バッファをフラッシュ ★★★
                    save_progress(progress_data)
                    pair_idx += 1
                    time.sleep(1.1)
                    continue

                # ▼▼▼【ここからが修正の核心】▼▼▼
                # result が "failed_retry" または "failed_critical" の場合
                while True:
                    # ユーザーに選択を促す前に、必ず出力をフラッシュする
                    print(f"\n      会話ペア {pair_idx + 1} の処理に失敗しました。どうしますか？ (r: このペアを再試行, s: このペアをスキップ, q: 終了): ", end="")
                    sys.stdout.flush() # ★★★ input()の前に必ずフラッシュ ★★★

                    user_choice = input().lower()

                    if user_choice == 'r':
                        break
                    elif user_choice == 's':
                        # スキップする場合、進捗ファイルに「このペアは処理した」と記録する
                        character_progress["progress"][filename] = pair_idx + 1
                        save_progress(progress_data)
                        pair_idx += 1
                        break
                    elif user_choice == 'q':
                        print("--- ユーザーの指示により、インポート処理を中断します。 ---")
                        save_progress(progress_data)
                        return
                    else:
                        print("      無効な入力です。'r', 's', 'q' のいずれかを入力してください。")

                if user_choice in ['s', 'q']:
                    if user_choice == 's': continue
                    else: break
                # ▲▲▲【修正ここまで】▲▲▲

            print("\n  - ファイルの処理が完了しました。")

        print("\n--- 全てのログファイルのインポートが完了しました。 ---")
        print(f"最終結果: {character_progress['total_success_count']}件の会話を記憶しました。")

    except Exception as e:
        error_message = str(e).encode(sys.stdout.encoding, errors='replace').decode(sys.stdout.encoding)
        print(f"\n[致命的エラー] 予期せぬエラーが発生しました: {error_message}")
    finally:
        print("インポーターを終了します。")

# (以降のコードは変更なし)

if __name__ == "__main__":
    main()
