# batch_importer.py (v4: MemOS対応)
import os
import sys
import json
from pathlib import Path
import argparse
import time
import traceback
import re
from typing import List, Dict

# --- 必要なモジュールをインポート ---
import memos_manager
import config_manager # configをロードするために必要
from utils import load_chat_log, acquire_lock, release_lock

# --- ログ解析・進捗管理関数 ---
def parse_log_for_import(log_messages: List[Dict[str, str]]) -> List[List[Dict[str, str]]]:
    conversation_pairs = []
    current_pair = []
    for msg in log_messages:
        role = "assistant" if msg.get("role") == "model" or msg.get("role") not in ["user"] else "user"
        content = msg.get("content", "").strip()
        if not content: continue

        # ユーザーの発言で新しいペアを開始
        if role == 'user':
            # 前のペアが完成していればリストに追加
            if len(current_pair) == 2:
                conversation_pairs.append(current_pair)
            current_pair = [{"role": "user", "content": content}]
        # アシスタントの発言でペアを完成
        elif role == 'assistant' and current_pair and current_pair[0]["role"] == "user" and len(current_pair) == 1:
            current_pair.append({"role": "assistant", "content": content})
            conversation_pairs.append(current_pair)
            current_pair = [] # ペアをリセット

    # 最後のペアが未完成の場合の処理は不要 (user発言のみのペアは含めない)
    valid_pairs = [p for p in conversation_pairs if len(p) == 2 and p[0]['role'] == 'user' and p[1]['role'] == 'assistant']
    return valid_pairs

PROGRESS_FILE = "importer_progress.json"
def load_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                content = f.read()
                if not content.strip(): return {}
                return json.loads(content)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}

def save_progress(progress_data):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress_data, f, indent=2, ensure_ascii=False)

def main():
    # ★★★ ロック処理 ★★★
    if not acquire_lock():
        print("他のプロセスが実行中のため、バッチインポーターを起動できません。")
        return

    try:
        # configを最初にロード
        config_manager.load_config()

        parser = argparse.ArgumentParser(description="Nexus Arkの過去ログを客観的記憶(MemOS)に一括インポートするツール")
        parser.add_argument("--character", required=True, help="対象のキャラクター名")
        parser.add_argument("--logs-dir", required=True, help="過去ログファイル（.txt）が格納されているディレクトリのパス")
        parser.add_argument("--reset", action="store_true", help="このキャラクターの進捗をリセットして最初からインポートを開始します。")
        args = parser.parse_args()

        # memos_managerからMOSインスタンスを取得
        # これにより、APIキーなどの設定はconfigから自動的に読み込まれる
        mos_instance = memos_manager.get_mos_instance(args.character)

        progress_data = load_progress()
        if args.reset and args.character in progress_data:
            print(f"'{args.character}' の進捗をリセットします。")
            del progress_data[args.character]
            save_progress(progress_data)

        character_progress = progress_data.get(args.character, {})
        progress_data[args.character] = character_progress

        last_file = character_progress.get("last_file")
        last_index = character_progress.get("last_index", -1)
        total_success_count = character_progress.get("total_success_count", 0)
        total_fail_count = character_progress.get("total_fail_count", 0)

        logs_path = Path(args.logs_dir)
        if not logs_path.is_dir():
            print(f"[エラー] 指定されたディレクトリが見つかりません: {args.logs_dir}")
            sys.exit(1)

        all_log_files = sorted([p for p in logs_path.glob("*.txt") if not p.name.endswith("_summary.txt")])

        print(f"\n--- 検出されたログファイル数: {len(all_log_files)} ---")
        if not all_log_files:
            print("処理対象のログファイルがありません。")
            sys.exit(0)

        start_file_index = 0
        if last_file:
            try:
                start_file_index = [p.name for p in all_log_files].index(last_file)
            except ValueError:
                last_index = -1 # ファイルが見つからない場合は最初から

        for file_idx in range(start_file_index, len(all_log_files)):
            filepath = all_log_files[file_idx]
            print(f"\n--- ファイル処理開始: {filepath.name} ({file_idx + 1}/{len(all_log_files)}) ---")

            log_data = load_chat_log(filepath, args.character)
            if not log_data: continue

            conversation_pairs = parse_log_for_import(log_data)
            total_pairs_in_file = len(conversation_pairs)
            if total_pairs_in_file == 0: continue

            start_pair_index = last_index + 1 if file_idx == start_file_index and last_index != -1 else 0

            i = start_pair_index
            while i < total_pairs_in_file:
                pair = conversation_pairs[i]
                retry_attempt = 0
                max_retries = 3

                while retry_attempt < max_retries:
                    try:
                        # ★★★ MemOSへの記憶 ★★★
                        mos_instance.add(messages=pair)
                        print(f"    - 記憶成功 (ファイル内: {i + 1}/{total_pairs_in_file})")
                        total_success_count += 1
                        i += 1
                        time.sleep(1.2) # APIレート制限を考慮
                        break
                    except Exception as e:
                        error_message = str(e)
                        retry_attempt += 1
                        print(f"    - 警告: 記憶に失敗。リトライします。 ({retry_attempt}/{max_retries})")
                        print(f"      (エラー詳細: {error_message[:200]}...)")
                        time.sleep(10) # 待機してリトライ

                else: # リトライ上限に達した場合
                    print(f"    - エラー: リトライ上限 ({max_retries}回) に達しました。")
                    user_choice = input("      このペアの処理をどうしますか？ (s: スキップ, r: 再リトライ, q: 終了): ").lower()
                    if user_choice == 's':
                        total_fail_count += 1
                        i += 1
                        continue
                    elif user_choice == 'r':
                        continue # 同じiで外側のループを再試行
                    elif user_choice == 'q':
                        print("      -> 処理を中断し、進捗を保存して終了します。")
                        character_progress["last_file"] = filepath.name
                        character_progress["last_index"] = i - 1
                        save_progress(progress_data)
                        sys.exit(0)

                # 各ペアの処理後に進捗を保存
                character_progress["last_file"] = filepath.name
                character_progress["last_index"] = i - 1
                character_progress["total_success_count"] = total_success_count
                character_progress["total_fail_count"] = total_fail_count
                save_progress(progress_data)

            print(f"  -> ファイル '{filepath.name}' の処理完了。")
            character_progress["last_index"] = -1 # 次のファイルは最初から
            save_progress(progress_data)

        print("\n--- すべての指定ログファイルのインポート試行が終了しました ---")
        print(f"最終結果: 成功 {total_success_count}件, 失敗 {total_fail_count}件")

    except KeyboardInterrupt:
        print("\n[情報] ユーザーの操作により処理が中断されました。")
    except Exception as e:
        print(f"\n[致命的エラー] 予期せぬエラーが発生しました: {e}")
        traceback.print_exc()
    finally:
        release_lock()

if __name__ == "__main__":
    main()
