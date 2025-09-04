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
import asyncio

# --- [ロギング設定] ---
LOGS_DIR = Path(os.getenv("MEMOS_BASE_PATH", Path.cwd())) / ".memos" / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE_PATH = LOGS_DIR / "importer.log"

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
import cognee_manager # cogneeの環境変数を設定
import cognee
import utils
import room_manager
import constants

# --- [定数とヘルパー関数] ---
PROGRESS_FILE = "importer_progress.json"
ERROR_LOG_FILE = "importer_errors.log"
STOP_SIGNAL_FILE = "stop_importer.signal"

def group_messages_into_pairs(messages: List[Dict[str, str]]) -> List[List[Dict[str, str]]]:
    pairs = []
    i = 0
    while i < len(messages):
        if messages[i]["role"] == "USER" and messages[i].get("content"):
            if i + 1 < len(messages) and messages[i+1]["role"] == "AGENT" and messages[i+1].get("content"):
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
    with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"--- ERROR at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        f.write(f"File: {filename}\n")
        f.write(f"Pair Index: {pair_index}\n")
        f.write("Pair Content:\n")
        json.dump(pair, f, indent=2, ensure_ascii=False)
        f.write("\nError Details:\n")
        f.write(str(error) + "\n")
        f.write("-" * 20 + "\n\n")

async def main():
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

    if os.path.exists(STOP_SIGNAL_FILE):
        os.remove(STOP_SIGNAL_FILE)

    parser = argparse.ArgumentParser(description="Nexus Arkの過去ログをCognee記憶システムに一括インポートするツール")
    parser.add_argument("--character", required=True, help="対象のルーム名（フォルダ名）")
    args = parser.parse_args()
    character_name = args.character

    character_path = Path(constants.ROOMS_DIR) / character_name
    import_source_path = character_path / "log_import_source"

    if not import_source_path.exists():
        print(f"エラー: インポート元のディレクトリが見つかりません: {import_source_path}")
        sys.exit(1)

    log_files = sorted([f for f in import_source_path.iterdir() if f.is_file() and f.suffix == '.txt'])
    if not log_files:
        print(f"情報: {import_source_path} に処理対象のログファイル (.txt) がありません。")
        sys.exit(0)

    print(f"--- Cognee記憶インポーターを開始します (対象ルーム: {character_name}) ---")

    progress_data = load_progress()
    character_progress = progress_data.get(character_name, {
        "last_processed_file": None,
        "last_processed_pair_index": -1,
        "total_success_count": 0,
    })

    try:
        print("--- Cogneeエンジンを初期化しました ---")

        for file_path in log_files:
            filename = file_path.name
            if character_progress["last_processed_file"] and filename < character_progress["last_processed_file"]:
                print(f"スキップ: {filename} (既に処理済み)")
                continue

            print(f"\n--- ファイル処理開始: {filename} ---")
            raw_messages = utils.load_chat_log(str(file_path))
            conversation_pairs = group_messages_into_pairs(raw_messages)

            start_index = 0
            if filename == character_progress["last_processed_file"]:
                start_index = character_progress["last_processed_pair_index"] + 1

            for i in range(start_index, len(conversation_pairs)):
                if os.path.exists(STOP_SIGNAL_FILE):
                    print("\n*** 中断シグナルを検知しました。現在のファイル処理を完了後、安全に停止します。 ***")
                    final_cleanup(progress_data, character_name, character_progress)
                    return

                pair = conversation_pairs[i]
                try:
                    # Cogneeに会話を追加
                    # 形式は [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
                    await cognee.add(
                        dialogue = pair,
                        dialogue_metadata = {
                            "source_file": filename,
                            "pair_index": i,
                            "character": character_name,
                        }
                    )
                    character_progress["total_success_count"] += 1
                    print(f"  - ペア {i+1}/{len(conversation_pairs)} を記憶に追加しました。", end="\r")

                except Exception as e:
                    print(f"\nエラー: ペア {i+1} の処理中にエラーが発生しました。詳細は {ERROR_LOG_FILE} を確認してください。")
                    log_error(filename, i, pair, e)

                character_progress["last_processed_pair_index"] = i
                save_progress({**progress_data, character_name: character_progress})

            character_progress["last_processed_file"] = filename
            character_progress["last_processed_pair_index"] = -1 # ファイルが完了したらリセット
            print(f"\n--- ファイル処理完了: {filename} ---")

        print("\n--- 全てのファイルのインポートが完了しました。 ---")
        # 最終的な認知処理を実行
        print("--- 記憶の最終的な構造化を開始します (cognify)... ---")
        await cognee.cognify()
        print("--- 記憶の構造化が完了しました。 ---")

    except Exception as e:
        print(f"\n!!! [致命的エラー] インポート処理中に予期せぬエラーが発生しました !!!")
        traceback.print_exc()
    finally:
        final_cleanup(progress_data, character_name, character_progress)

if __name__ == "__main__":
    asyncio.run(main())
