# batch_importer.py
import os
import argparse
import time
import json
import traceback
from typing import List, Dict

# Nexus Arkの既存モジュールをインポート
import config_manager
import mem0_manager
from utils import load_chat_log

# parse_log_for_mem0 関数 (前回から変更なしと想定されるが、念のため最新版を記述)
def parse_log_for_mem0(log_messages: List[Dict[str, str]]) -> List[List[Dict[str, str]]]:
    conversation_pairs = []
    current_pair = []
    for msg in log_messages:
        role = "assistant" if msg.get("role") == "model" or msg.get("role") not in ["user"] else "user"
        content = msg.get("content", "").strip()
        if not content:
            continue
        if role == 'user':
            if current_pair and current_pair[-1]["role"] == "assistant":
                conversation_pairs.append(current_pair)
                current_pair = []
            elif current_pair and current_pair[-1]["role"] == "user":
                current_pair = []
            current_pair.append({"role": "user", "content": content})
        elif role == 'assistant':
            if current_pair and current_pair[-1]["role"] == "user":
                current_pair.append({"role": "assistant", "content": content})
                conversation_pairs.append(current_pair)
                current_pair = []
    valid_pairs = [p for p in conversation_pairs if len(p) == 2 and p[0]['role'] == 'user' and p[1]['role'] == 'assistant']
    return valid_pairs

PROGRESS_FILE = "importer_progress.json"

def load_progress():
    """進捗記録ファイルを読み込む"""
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"警告: 進捗ファイル '{PROGRESS_FILE}' が不正なJSON形式です。新しい進捗ファイルを作成します。")
            return {}
    return {}

def save_progress(progress_data):
    """進捗記録ファイルに書き込む"""
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress_data, f, indent=2)

def main():
    parser = argparse.ArgumentParser(description="Nexus Arkの過去ログをMem0に一括インポートするツール")
    parser.add_argument("--character", required=True, help="対象のキャラクター名 (Nexus Arkシステム上の名前)")
    parser.add_argument("--logs-dir", required=True, help="過去ログファイル（.txt）が格納されているディレクトリのパス")
    parser.add_argument("--api-key-name", required=True, help="config.jsonに登録されているAPIキー名")
    parser.add_argument("--reset", action="store_true", help="進捗をリセットして最初からインポートを開始します。")
    # ★★★ ここからが修正・追加箇所 ★★★
    parser.add_argument(
        "--model",
        default="gemini-2.5-flash-lite-preview-06-17",
        help="インポート処理に使用するAIモデル名 (デフォルト: gemini-2.5-flash-lite-preview-06-17)"
    )
    # ★★★ 修正ここまで ★★★
    args = parser.parse_args()

    if args.reset:
        if os.path.exists(PROGRESS_FILE):
            try:
                os.remove(PROGRESS_FILE)
                print(f"進捗ファイル '{PROGRESS_FILE}' を削除しました。最初から処理を開始します。")
            except OSError as e:
                print(f"エラー: 進捗ファイル '{PROGRESS_FILE}' の削除に失敗しました: {e}")
                return
        else:
            print("進捗ファイルは存在しません。最初から処理を開始します。")

    print("--- 過去ログのインポート処理を開始します ---")
    print(f"対象キャラクター: {args.character}")
    print(f"ログディレクトリ: {args.logs_dir}")
    print(f"使用APIキー名: {args.api_key_name}")
    print(f"使用AIモデル: {args.model}") # ★★★ 使用モデルを表示 ★★★

    config_manager.load_config()
    api_key = config_manager.API_KEYS.get(args.api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        print(f"エラー: APIキー '{args.api_key_name}' が無効です。処理を中断します。")
        return

    if not os.getenv("MEM0_TELEMETRY_ENABLED"):
        os.environ["MEM0_TELEMETRY_ENABLED"] = "false"
    os.environ['GOOGLE_API_KEY'] = api_key

    if not os.path.isdir(args.logs_dir):
        print(f"エラー: 指定されたログディレクトリ '{args.logs_dir}' が存在しないか、ディレクトリではありません。")
        return

    all_log_files = sorted([f for f in os.listdir(args.logs_dir) if f.endswith(".txt")])
    if not all_log_files:
        print(f"エラー: 指定されたディレクトリ '{args.logs_dir}' に.txtファイルが見つかりません。")
        return

    progress = load_progress()
    processed_files = progress.get(args.character, {}).get("processed_files", [])

    overall_success_count = 0
    overall_fail_count = 0
    newly_processed_files_in_this_run = []

    try:
        # ★★★ 修正箇所 ★★★
        # コマンドラインで指定されたモデル名を渡す
        mem0_instance = mem0_manager.get_mem0_instance(args.character, api_key, model_name=args.model)

        for filename in all_log_files:
            if filename in processed_files:
                print(f"\n--- ファイル '{filename}' は処理済みのためスキップします。 ---")
                continue

            print(f"\n--- ファイルを処理中: {filename} ---")
            filepath = os.path.join(args.logs_dir, filename)
            raw_messages = load_chat_log(filepath, args.character)
            conversation_pairs = parse_log_for_mem0(raw_messages)

            total_pairs_in_file = len(conversation_pairs)
            if total_pairs_in_file == 0:
                print("  -> このファイルには有効な会話ペアが見つかりませんでした。スキップします。")
                newly_processed_files_in_this_run.append(filename)
                current_char_progress = progress.get(args.character, {"processed_files": []})
                current_char_progress["processed_files"].append(filename)
                progress[args.character] = current_char_progress
                save_progress(progress)
                continue

            print(f"  -> {total_pairs_in_file} 件の会話ペアを記憶します。")
            file_success_count = 0
            file_fail_count = 0

            for i, pair in enumerate(conversation_pairs):
                try:
                    mem0_instance.add(messages=pair, user_id=args.character)
                    print(f"    - 記憶成功 ({i + 1}/{total_pairs_in_file})")
                    file_success_count += 1
                    # ★★★ 修正箇所 ★★★
                    # 60RPMのレートリミットを遵守するため、1秒以上の待機時間を設ける
                    time.sleep(1.1)
                except Exception as e:
                    print(f"    - 警告: 会話ペア ({i + 1}/{total_pairs_in_file}) の記憶に失敗。スキップします。")
                    fail_count += 1
                    continue

            overall_success_count += file_success_count
            overall_fail_count += file_fail_count
            print(f"  -> ファイル '{filename}' の処理完了 (成功: {file_success_count}, 失敗: {file_fail_count})")
            newly_processed_files_in_this_run.append(filename)

            current_char_progress = progress.get(args.character, {"processed_files": []})
            current_char_progress["processed_files"].append(filename)
            progress[args.character] = current_char_progress
            save_progress(progress)

    except Exception as e:
        print("\nエラー: Mem0への記憶処理中に致命的な問題が発生しました。")
        print(traceback.format_exc())
        return

    print("\n--- すべての指定ログファイルのインポート試行が終了しました ---")
    print(f"今回の実行で新たに処理したファイル数: {len(newly_processed_files_in_this_run)}")
    print(f"今回の実行での総結果: 成功 {overall_success_count}件, 失敗 {overall_fail_count}件")
    print(f"キャラクター '{args.character}' の総処理済みファイル数: {len(progress.get(args.character, {}).get('processed_files', []))}")

if __name__ == "__main__":
    main()
