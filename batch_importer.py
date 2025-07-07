# batch_importer.py (v3: Rate limit handling fix)
import os
import sys
import json
from pathlib import Path
import argparse
import time
import traceback
import re
from typing import List, Dict
import importlib.util

# --- ライブラリ存在チェック ---
psutil_spec = importlib.util.find_spec("psutil")
if psutil_spec is None:
    print("エラー: 'psutil'ライブラリが見つかりません。 'pip install psutil' を実行してください。")
    sys.exit(1)
import psutil

# --- 必要なモジュールをインポート ---
import mem0_manager
from utils import load_chat_log

# --- グローバル・ロック処理 (変更なし) ---
LOCK_FILE_PATH = Path.home() / ".nexus_ark.global.lock"
def check_and_clear_stale_lock():
    if not LOCK_FILE_PATH.exists():
        return True
    try:
        with open(LOCK_FILE_PATH, "r", encoding="utf-8") as f:
            lock_info = json.load(f)
        pid = lock_info.get('pid')
        if pid is None or not psutil.pid_exists(pid):
            LOCK_FILE_PATH.unlink()
            return True
        else:
            path = lock_info.get('path', '不明')
            print(f"エラー: Nexus Arkの別のプロセスがすでに実行中です。 (PID: {pid}, Path: {path})")
            return False
    except Exception:
        try:
            LOCK_FILE_PATH.unlink()
            return True
        except Exception:
            return False

# --- ログ解析・進捗管理関数 (変更なし) ---
def parse_log_for_mem0(log_messages: List[Dict[str, str]]) -> List[List[Dict[str, str]]]:
    conversation_pairs = []
    current_pair = []
    for msg in log_messages:
        role = "assistant" if msg.get("role") == "model" or msg.get("role") not in ["user"] else "user"
        content = msg.get("content", "").strip()
        if not content: continue
        if role == 'user':
            if len(current_pair) == 2:
                conversation_pairs.append(current_pair)
            current_pair = [{"role": "user", "content": content}]
        elif role == 'assistant' and current_pair and current_pair[0]["role"] == "user" and len(current_pair) == 1:
            current_pair.append({"role": "assistant", "content": content})
            conversation_pairs.append(current_pair)
            current_pair = []
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
    if not check_and_clear_stale_lock():
        sys.exit(1)
    
    try:
        with open(LOCK_FILE_PATH, "w", encoding="utf-8") as f:
            lock_data = {"pid": os.getpid(), "path": os.path.abspath(os.path.dirname(__file__))}
            json.dump(lock_data, f)
        
        parser = argparse.ArgumentParser(description="Nexus Arkの過去ログをMem0に一括インポートするツール")
        parser.add_argument("--character", required=True, help="対象のキャラクター名")
        parser.add_argument("--logs-dir", required=True, help="過去ログファイル（.txt）が格納されているディレクトリのパス")
        parser.add_argument("--api-key-name", required=True, help="config.jsonに登録されているAPIキー名")
        parser.add_argument("--reset", action="store_true", help="このキャラクターの進捗をリセットして最初からインポートを開始します。")
        parser.add_argument("--model", default="gemini-2.5-flash-lite-preview-06-17", help="インポート処理に使用するAIモデル名")
        args = parser.parse_args()

        try:
            with open("config.json", "r", encoding="utf-8") as f:
                config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"\n[エラー] 設定ファイル(config.json)の読み込みに失敗しました: {e}")
            sys.exit(1)

        api_key = config.get("api_keys", {}).get(args.api_key_name)
        if not api_key:
            print(f"エラー: 指定されたAPIキー名 '{args.api_key_name}' がconfig.jsonに見つかりません。")
            sys.exit(1)
            
        os.environ['GOOGLE_API_KEY'] = api_key
        
        mem0_instance = mem0_manager.get_mem0_instance(args.character, api_key, args.model)
        
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
        
        logs_dir = args.logs_dir
        logs_path = Path(logs_dir)

        print("\n--- デバッグ情報 ---")
        print(f"指定されたログディレクトリ: {logs_dir}")

        if not logs_path.is_dir():
            print(f"[エラー] 指定されたディレクトリが見つかりません。パスが正しいか確認してください。")
            sys.exit(1)
        
        all_log_files_paths = sorted(logs_path.glob("*.txt"))
        all_log_files = [p for p in all_log_files_paths if not p.name.endswith("_summary.txt")]

        print(f"検出されたログファイル数: {len(all_log_files)}")
        if all_log_files:
            print(f"検出されたログファイル（最初の5件）: {[p.name for p in all_log_files[:5]]}")
        else:
            print("[警告] 処理対象のログファイルが1件も見つかりませんでした。")
        print("--------------------\n")
        
        if not all_log_files:
            print("処理を終了します。")
            sys.exit(0)

        start_file_index = 0
        if last_file:
            try:
                start_file_index = [p.name for p in all_log_files].index(last_file)
            except ValueError:
                last_index = -1

        for file_idx in range(start_file_index, len(all_log_files)):
            filepath = all_log_files[file_idx]
            print(f"\n--- ファイル処理開始: {filepath.name} ({file_idx + 1}/{len(all_log_files)}) ---")
            
            log_data = load_chat_log(filepath, args.character)
            if not log_data: continue
            
            conversation_pairs = parse_log_for_mem0(log_data)
            total_pairs_in_file = len(conversation_pairs)
            if total_pairs_in_file == 0: continue
            
            start_pair_index = last_index + 1 if file_idx == start_file_index and last_index is not None else 0
            
            i = start_pair_index
            while i < total_pairs_in_file:
                pair = conversation_pairs[i]
                retry_attempt = 0
                max_retries = 3

                while retry_attempt < max_retries:
                    try:
                        mem0_instance.add(messages=pair, user_id=args.character)
                        print(f"    - 記憶成功 (ファイル内: {i + 1}/{total_pairs_in_file})")
                        total_success_count += 1
                        i += 1
                        time.sleep(1.1)
                        break 
                    except Exception as e:
                        # ▼▼▼ 修正箇所 ▼▼▼
                        # エラーハンドリングのロジックを修正
                        error_str = str(e).lower()
                        retry_attempt += 1

                        # 1. 最初に、リトライ可能な「1分あたりの上限エラー」を処理する
                        if "429" in error_str or "resource_exhausted" in error_str:
                            print(f"    - 警告: 1分あたりの利用上限に達しました。リトライします。 ({retry_attempt}/{max_retries})")
                            delay_match = re.search(r"'retrydelay': '(\d+)s'", error_str)
                            wait_time = int(delay_match.group(1)) + 1 if delay_match else 61 # 1秒余裕を持たせる
                            print(f"      (APIの指示に従い、{wait_time}秒待機します)")
                            time.sleep(wait_time)
                        
                        # 2. 次に、リトライ不可能な「1日の上限エラー」を処理する
                        elif 'user_project_denied' in error_str or 'quota' in error_str:
                            print(f"\n[!!!] 1日の利用上限(Quota)に達したか、プロジェクトレベルでアクセスが拒否されました。")
                            print("本日の処理を安全に終了します。")
                            character_progress["last_file"] = filepath.name
                            character_progress["last_index"] = i - 1 # 現在のiは失敗しているので、その一つ前までを記録
                            save_progress(progress_data)
                            sys.exit(1)

                        # 3. その他の予期せぬエラーを処理する
                        else:
                            print(f"    - 警告: 予期せぬエラーで記憶に失敗。リトライします。 ({retry_attempt}/{max_retries})")
                            print(f"      (エラー詳細: {str(e)[:150]}...)")
                            print(f"      (10秒待機します)")
                            time.sleep(10)
                        # ▲▲▲ 修正ここまで ▲▲▲

                else: # whileループがbreakされずに終わった場合 (リトライ上限)
                    print(f"    - エラー: リトライ上限 ({max_retries}回) に達しました。このペアをスキップします。")
                    total_fail_count += 1
                    i += 1
                
                # ループの最後に必ず進捗を保存
                character_progress["last_file"] = filepath.name
                character_progress["last_index"] = i - 1 # 次回はiから再開するため、保存するのはi-1
                character_progress["total_success_count"] = total_success_count
                character_progress["total_fail_count"] = total_fail_count
                save_progress(progress_data)

            print(f"  -> ファイル '{filepath.name}' の処理完了。")
            # ファイル完了時、次のファイルから処理を開始できるようにインデックスをリセット
            character_progress["last_file"] = filepath.name
            character_progress["last_index"] = -1
            save_progress(progress_data)

        print("\n--- すべての指定ログファイルのインポート試行が終了しました ---")
        print(f"最終結果: 成功 {total_success_count}件, 失敗 {total_fail_count}件")

    finally:
        if LOCK_FILE_PATH.exists():
            try:
                os.unlink(LOCK_FILE_PATH)
            except OSError:
                pass

if __name__ == "__main__":
    main()
