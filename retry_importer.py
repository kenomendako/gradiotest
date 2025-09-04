# retry_importer.py
import os
import sys
import json
import argparse
import time
import re
from typing import List, Dict

import cognee_manager # cogneeの環境変数を設定
from langchain_cognee import CogneeVectorStore
from langchain_core.documents import Document
import constants

# --- 定数 ---
ERROR_LOG_FILE = "importer_errors.log"
SUCCESS_LOG_FILE = "retry_success.log"

def parse_error_log() -> List[Dict]:
    """importer_errors.log を解析し、会話ペアとメタデータのリストを抽出する。"""
    if not os.path.exists(ERROR_LOG_FILE):
        print(f"エラー: {ERROR_LOG_FILE} が見つかりません。")
        return []

    with open(ERROR_LOG_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    error_blocks = content.split("--- ERROR at")[1:]

    tasks = []
    for block in error_blocks:
        try:
            filename_match = re.search(r"File: (.*?)\n", block)
            pair_index_match = re.search(r"Pair Index: (.*?)\n", block)
            json_match = re.search(r"Pair Content:\n(\[.*?\])", block, re.DOTALL)

            if filename_match and pair_index_match and json_match:
                filename = filename_match.group(1)
                pair_index = int(pair_index_match.group(1))
                pair_content = json.loads(json_match.group(1))

                if isinstance(pair_content, list) and len(pair_content) == 2:
                    tasks.append({
                        "filename": filename,
                        "pair_index": pair_index,
                        "pair": pair_content,
                    })
        except (json.JSONDecodeError, ValueError) as e:
            print(f"警告: ログブロックの解析に失敗しました: {e}")
            continue
    return tasks

def log_success(task: Dict):
    """正常にインポートできたペアを成功ログに記録する。"""
    with open(SUCCESS_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"--- SUCCESS at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        json.dump(task, f, indent=2, ensure_ascii=False)
        f.write("\n\n")

def main():
    parser = argparse.ArgumentParser(description="Nexus Arkのインポートエラーログから、失敗した会話ペアを対話的に再インポートするツール")
    parser.add_argument("--character", required=True, help="対象のルーム名（メタデータとして使用）")
    args = parser.parse_args()
    character_name = args.character

    error_tasks = parse_error_log()
    if not error_tasks:
        print("エラーログに処理対象が見つかりませんでした。")
        return

    print(f"--- {len(error_tasks)} 件のエラーを検知しました。再処理を開始します。 ---")

    try:
        print("--- Cogneeベクターストアを初期化します ---")
        vector_store = CogneeVectorStore()
        print("--- Cogneeベクターストアの初期化に成功しました ---")

        success_count = 0
        for i, task in enumerate(error_tasks):
            print(f"\n--- 処理中 {i+1}/{len(error_tasks)} ---")
            print(f"  - ファイル: {task['filename']}, ペアインデックス: {task['pair_index']}")
            print("  - ユーザー発言:", task['pair'][0]['content'][:100] + "...")

            user_input = input("このペアを再インポートしますか？ (y/n/q): ").lower()

            if user_input == 'q':
                print("処理を中断します。")
                break
            if user_input == 'n':
                print("スキップしました。")
                continue

            if user_input == 'y':
                try:
                    user_name = task['pair'][0].get("responder", "ユーザー")
                    agent_name = task['pair'][1].get("responder", character_name)
                    content_string = f"{user_name}: {task['pair'][0]['content']}\n{agent_name}: {task['pair'][1]['content']}"

                    metadata = {
                        "source_file": task['filename'],
                        "pair_index": task['pair_index'],
                        "character": character_name,
                        "retry_import": True,
                    }
                    document = Document(page_content=content_string, metadata=metadata)

                    vector_store.add_documents([document])

                    log_success(task)
                    success_count += 1
                    print("  -> 成功: 記憶に追加し、成功ログに記録しました。")
                except Exception as e:
                    print(f"  -> 失敗: 再インポート中にエラーが発生しました: {e}")
            else:
                print("無効な入力です。スキップします。")

        print(f"\n--- 再処理が完了しました。{success_count} 件のペアをインポートしました。 ---")

    except Exception as e:
        print(f"\n!!! [致命的エラー] 再インポート処理中に予期せぬエラーが発生しました !!!")
        traceback.print_exc()

if __name__ == "__main__":
    main()
