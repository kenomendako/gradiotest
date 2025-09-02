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
import utils
import room_manager

# --- [定数とヘルパー関数] ---
PROGRESS_FILE = "importer_progress.json"
ERROR_LOG_FILE = "importer_errors.log"
STOP_SIGNAL_FILE = "stop_importer.signal"

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

    # ▼▼▼【ここから下のブロックをまるごと置き換え】▼▼▼
    print("\n" + "="*60)
    print("!!! [重要なお知らせ] !!!")
    print("Nexus Arkの記憶システムは、現在新しい『Cognee』システムへの移行作業中です。")
    print("そのため、このバッチインポータースクリプトは一時的に無効化されています。")
    print("開発ロードマップのフェーズ2で、Cogneeに対応した新しいバージョンが提供される予定です。")
    print("="*60 + "\n")
    # ▲▲▲【置き換えここまで】▲▲▲

if __name__ == "__main__":
    main()
