# [retry_importer.py を、この内容で完全に置き換える]
import sys
import os

# プロジェクトのルートディレクトリをPythonの検索パスに追加
# これにより、'lib'フォルダ内のライブラリを直接インポートできるようになる
project_root = os.path.abspath(os.path.dirname(__file__))
lib_path = os.path.join(project_root, 'lib')
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)


import os
import sys
import json
import argparse
import time
import re
from typing import List, Dict

# ▼▼▼【ここからが修正の核心】▼▼▼
# config_managerと、cognee関連のインポートをここから削除する
import constants
# ▲▲▲【修正ここまで】▲▲▲


# --- 定数 ---
# ... (この部分は変更なし) ...
ERROR_LOG_FILE = "importer_errors.log"
SUCCESS_LOG_FILE = "retry_success.log"

# --- ヘルパー関数 ---
# ... (この部分も変更なし) ...
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

# ▼▼▼【ここからが修正の核心】▼▼▼
def run_retry_importer(character_name: str, api_key_name: str):
    """再インポート処理の本体"""
    from langchain_core.documents import Document
    from langchain_cognee import CogneeVectorStore

    error_tasks = parse_error_log()
    if not error_tasks:
        print("エラーログに処理対象が見つかりませんでした。")
        return

    print(f"--- {len(error_tasks)} 件のエラーを検知しました。再処理を開始します。 ---")

    try:
        print("--- Cogneeベクターストアを初期化します ---")
        vector_store = CogneeVectorStore()
        print("--- Cogneeベクターストアの初期化に成功しました ---")

        # ... (以降の処理は、以前のmain関数の中身と全く同じ) ...
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
    # 1. 最初に引数を解析
    parser = argparse.ArgumentParser(description="Nexus Arkのインポートエラーログから、失敗した会話ペアを対話的に再インポートするツール")
    parser.add_argument("--character", required=True, help="対象のルーム名（メタデータとして使用）")
    parser.add_argument("--api-key-name", required=True, help="使用するGemini APIキーの名前 (config.jsonで設定したもの)")
    args = parser.parse_args()

    # 2. 次に設定ファイルを読み込む
    import config_manager
    config_manager.load_config()
    api_key_value = config_manager.GEMINI_API_KEYS.get(args.api_key_name)

    if not api_key_value or api_key_value == "YOUR_API_KEY_HERE":
        print(f"!!! エラー: 指定されたAPIキー '{args.api_key_name}' がconfig.jsonで見つからないか、有効な値ではありません。")
        sys.exit(1)

    # 3. 環境変数を設定する（最重要）
    os.environ["GOOGLE_API_KEY"] = api_key_value
    print(f"--- APIキー '{args.api_key_name}' をCogneeの環境変数に設定しました ---")

    # 4. 全ての設定が完了した後で、Cogneeをインポートする
    import cognee_manager

    # 5. メインの処理関数を呼び出す
    run_retry_importer(args.character, args.api_key_name)
# ▲▲▲【修正ここまで】▲▲▲
