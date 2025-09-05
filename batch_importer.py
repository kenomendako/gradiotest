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
import asyncio # ★★★ この行を新しく追加 ★★★

from google.api_core import exceptions as google_exceptions
from langchain_core.documents import Document
import utils
import constants
import config_manager
import cognee_manager

# ▼▼▼【ここからが修正の核心】▼▼▼
# Cogneeの、我々が発見した「真の」APIをインポートする
try:
    from cognee.api.v1.add import add as cognee_add
except ImportError:
    print("!!! [致命的エラー] 'cognee-python'ライブラリから'add'関数をインポートできません。")
    print("    'pip install -r requirements.txt' を実行して、正しいパッケージがインストールされているか確認してください。")
    sys.exit(1)
# ▲▲▲【修正ここまで】▲▲▲

# --- [ロギング設定とヘルパー関数は、以前のままで変更なし] ---
LOGS_DIR = Path(os.getenv("MEMOS_BASE_PATH", Path.cwd())) / ".memos" / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE_PATH = LOGS_DIR / "importer.log"
LOGGING_CONFIG = { "version": 1, "disable_existing_loggers": False, "formatters": { "standard": { "format": "%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(funcName)s - %(message)s" } }, "handlers": { "console": { "level": "INFO", "class": "logging.StreamHandler", "stream": stdout, "formatter": "standard" }, "file": { "level": "DEBUG", "class": "concurrent_log_handler.ConcurrentRotatingFileHandler", "filename": LOG_FILE_PATH, "maxBytes": 1024 * 1024 * 10, "backupCount": 5, "formatter": "standard", "use_gzip": True, }, }, "root": { "level": "DEBUG", "handlers": ["console", "file"] }, "loggers": { "memos": { "level": "WARNING", "propagate": True }, "gradio": { "level": "WARNING", "propagate": True }, "httpx": { "level": "WARNING", "propagate": True }, "neo4j": { "level": "WARNING", "propagate": True }, }, }
try:
    logging.config.dictConfig(LOGGING_CONFIG)
    logging.config.dictConfig = lambda *args, **kwargs: None
    print("--- [Nexus Ark Importer] ロギング設定を完全に掌握しました (ログファイル: importer.log) ---")
except ValueError as e:
    print(f"!!! ロギング設定エラー: {e}")
    print("   'concurrent-log-handler'がインストールされているか確認してください: pip install concurrent-log-handler")
    sys.exit(1)

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

def log_error(filename: str, pair_index: int, pair: List[Dict[str,str]], error: Exception, attempt: int):
    with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"--- ERROR at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (Attempt: {attempt}) ---\n")
        f.write(f"File: {filename}\n")
        f.write(f"Pair Index: {pair_index}\n")
        f.write("Pair Content:\n")
        json.dump(pair, f, indent=2, ensure_ascii=False)
        f.write("\nError Details:\n")
        f.write(traceback.format_exc() + "\n")
        f.write("-" * 20 + "\n\n")

def run_importer(character_name: str, api_key_name: str, is_from_ui: bool):
    """インポート処理の本体"""

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

    character_path = Path(constants.ROOMS_DIR) / character_name
    import_source_path = character_path / "log_import_source"

    if not import_source_path.exists():
        print(f"エラー: インポート元のディレクトリが見つかりません: {import_source_path}")
        sys.exit(1)
    log_files = sorted([f for f in import_source_path.iterdir() if f.is_file() and (f.suffix == '.txt' or f.suffix == '.md')])
    if not log_files:
        print(f"情報: {import_source_path} に処理対象のログファイル (.txt, .md) がありません。")
        sys.exit(0)

    print(f"--- Cognee記憶インポーターを開始します (対象ルーム: {character_name}) ---")

    progress_data = load_progress()
    character_progress = progress_data.get(character_name, { "last_processed_file": None, "last_processed_pair_index": -1, "total_success_count": 0, })

    try:
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

            i = start_index
            while i < len(conversation_pairs):
                if os.path.exists(STOP_SIGNAL_FILE):
                    print("\n*** 中断シグナルを検知しました。処理を終了します。 ***")
                    final_cleanup(progress_data, character_name, character_progress)
                    return

                pair = conversation_pairs[i]
                max_retries = 3
                attempt = 0
                success = False

                while attempt < max_retries and not success:
                    try:
                        user_name = pair[0].get("responder", "ユーザー")
                        agent_name = pair[1].get("responder", character_name)
                        content_string = f"{user_name}: {pair[0]['content']}\n{agent_name}: {pair[1]['content']}"

                        metadata = { "source_file": filename, "pair_index": i, "character": character_name }
                        document = Document(page_content=content_string, metadata=metadata)

                        # ▼▼▼【ここが修正の核心】▼▼▼
                        # CogneeのAPIを非同期で直接呼び出す
                        asyncio.run(cognee_add([document]))
                        # ▲▲▲【修正ここまで】▲▲▲

                        success = True
                        character_progress["total_success_count"] += 1
                        print(f"  - ペア {i+1}/{len(conversation_pairs)} を記憶に追加しました。", end="\r")

                    except google_exceptions.ResourceExhausted as e:
                        attempt += 1
                        print(f"\nAPIレート制限エラー: ペア {i+1} (試行 {attempt}/{max_retries})。")
                        log_error(filename, i, pair, e, attempt)
                        retry_after = 60
                        match = re.search(r'retry after (\d+)', str(e).lower())
                        if match:
                            retry_after = int(match.group(1)) + 1
                            print(f"  - APIからの指示に従い、{retry_after}秒待機します...")
                        else:
                            print(f"  - APIからの待機時間指定なし。デフォルトの{retry_after}秒待機します...")
                        if attempt < max_retries:
                            time.sleep(retry_after)

                    except Exception as e:
                        attempt += 1
                        print(f"\n一般エラー: ペア {i+1} の処理中 (試行 {attempt}/{max_retries})。")
                        print(f"  - 詳細: {e}")
                        log_error(filename, i, pair, e, attempt)
                        if attempt < max_retries:
                            print("  - 5秒待機して再試行します...")
                            time.sleep(5)

                if not success:
                    print(f"\n!!! 重大エラー: ペア {i+1} の処理に{max_retries}回失敗しました。")
                    if is_from_ui:
                        print("    UIからの実行のため、ここで処理を完全に中断します。")
                        log_error(filename, i, pair, Exception("UIからの実行中にリトライ上限に達したため処理を中断しました。"), attempt)
                        final_cleanup(progress_data, character_name, character_progress)
                        sys.exit(1)
                    else:
                        while True:
                            user_choice = input("どうしますか？ (s: スキップ, a: 中断, r: 再試行): ").lower()
                            if user_choice in ['s', 'a', 'r']: break
                            print("無効な入力です。s, a, r のいずれかを入力してください。")
                        if user_choice == 's': print("  - このペアをスキップします。"); i += 1; continue
                        elif user_choice == 'a': print("  - 処理を中断します。"); final_cleanup(progress_data, character_name, character_progress); return
                        elif user_choice == 'r': print("  - このペアを再試行します。"); continue

                character_progress["last_processed_pair_index"] = i
                save_progress({**progress_data, character_name: character_progress})
                i += 1

            character_progress["last_processed_file"] = filename
            character_progress["last_processed_pair_index"] = -1
            print(f"\n--- ファイル処理完了: {filename} ---")

        print("\n--- 全てのファイルのインポートが完了しました。 ---")
    except Exception as e:
        print(f"\n!!! [致命的エラー] インポート処理中に予期せず処理が中断されました !!!")
        traceback.print_exc()
    finally:
        final_cleanup(progress_data, character_name, character_progress)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Nexus Arkの過去ログをCognee記憶システムに一括インポートするツール")
    parser.add_argument("--character", required=True, help="対象のルーム名（フォルダ名）")
    parser.add_argument("--api-key-name", required=True, help="使用するGemini APIキーの名前 (config.jsonで設定したもの)")
    parser.add_argument("--is_running_from_ui", action="store_true", help="UIから実行されたことを示す内部フラグ")
    args = parser.parse_args()

    config_manager.load_config()
    api_key_value = config_manager.GEMINI_API_KEYS.get(args.api_key_name)

    if not api_key_value or api_key_value == "YOUR_API_KEY_HERE":
        print(f"!!! エラー: 指定されたAPIキー '{args.api_key_name}' がconfig.jsonで見つからないか、有効な値ではありません。")
        sys.exit(1)

    os.environ["COGNEE_LLM_PROVIDER"] = "google"
    os.environ["COGNEE_LLM_API_KEY"] = api_key_value
    print(f"--- APIキー '{args.api_key_name}' をCogneeの環境変数に設定しました (Provider: google) ---")

    run_importer(args.character, args.api_key_name, args.is_running_from_ui)
