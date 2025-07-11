# batch_importer.py (v3: Rate limit handling fix)
import os
import sys
import json # load_progress と save_progress のために必要
from pathlib import Path # logs_path で使用するため再度有効化
import argparse
import time
import traceback
import re
from typing import List, Dict
import importlib.util

# --- ライブラリ存在チェック ---
# psutil は utils.py で処理されるため、ここでの直接的な存在チェックは不要になる可能性があるが、
# スクリプト単体で psutil を使う他の箇所が将来的に追加される可能性を考慮し、
# 当面は残しても良いかもしれない。ただし、ロック処理自体は utils に移管する。
# 今回の指示では psutil のインポート自体は残す形になっていないため、コメントアウトまたは削除する。
# psutil_spec = importlib.util.find_spec("psutil")
# if psutil_spec is None:
#     print("エラー: 'psutil'ライブラリが見つかりません。 'pip install psutil' を実行してください。")
#     sys.exit(1)
# import psutil


# --- 必要なモジュールをインポート ---
import mem0_manager
from utils import load_chat_log, acquire_lock, release_lock # ★★★ acquire_lockとrelease_lockをインポート ★★★

# --- グローバル・ロック処理 (既存のコードを全て削除) ---
# LOCK_FILE_PATH = Path.home() / ".nexus_ark.global.lock"
# def check_and_clear_stale_lock():
# ... (ここから既存のロック処理関数を全て削除) ...

# --- ログ解析・進捗管理関数 (ここはそのまま) ---
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
        # json は import から削除したので、ここで json モジュールを直接使えない。
        # progress_data が辞書であることを前提とし、Python の標準的な方法で書き込むか、
        # utils.py に json を扱うヘルパー関数を作る必要がある。
        # ただし、このファイル内で json はまだ load_progress でも使われている。
        # load_progress の json.loads と save_progress の json.dump のために、
        # batch_importer.py の先頭で `import json` を残す必要がある。
        # 元の指示では json を削除するようになっているが、ここでは残す。
        import json # save_progress と load_progress のために必要
        json.dump(progress_data, f, indent=2, ensure_ascii=False)

def main():
    # ★★★ ロック取得処理を置き換え ★★★
    if not acquire_lock():
        sys.exit(1)
    
    # ★★★ try...finally ブロックでメイン処理を囲む ★★★
    try:
        # with open(LOCK_FILE_PATH, ... ) の行は不要なので削除
        
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
                        # エラーハンドリング開始
                        error_message = str(e)
                        error_str_lower = error_message.lower() # 比較用に小文字版も用意
                        retry_attempt += 1

                        # --- エラー種別の判定と処理 ---
                        # 1. 「1日の上限エラー」 (PerDay Quota)
                        #    エラーメッセージに 'quotaId': '...PerDay...' または単に 'PerDay' が含まれる場合。
                        #    このエラーはリトライしても回復しないため、進捗を保存して終了する。
                        if "'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'" in error_message or \
                           "PerDay" in error_message: # 広範囲の "PerDay" を含むエラーも捕捉
                            print(f"\n[!!!] 1日の利用上限 (PerDay Quota) に達しました。")
                            print("本日の処理を安全に終了します。")
                            character_progress["last_file"] = filepath.name
                            # 現在処理中のペア(i)は未完了のため、その一つ前を記録。
                            # iが0の場合は-1を記録し、次回起動時にファイル先頭から処理されるようにする。
                            character_progress["last_index"] = i - 1 if i > 0 else -1
                            character_progress["total_success_count"] = total_success_count
                            character_progress["total_fail_count"] = total_fail_count
                            save_progress(progress_data)
                            sys.exit(1) # 1日の上限エラーのため終了

                        # 2. 「1分あたりの上限エラー」 (Rate Limit)
                        #    HTTPステータスコード "429" (Too Many Requests) や "resource_exhausted" が含まれる場合。
                        #    APIからの指示があればそれに従い、なければ一定時間待機してリトライする。
                        elif "429" in error_str_lower or "resource_exhausted" in error_str_lower:
                            print(f"    - 警告: 1分あたりの利用上限に達した可能性があります。リトライします。 ({retry_attempt}/{max_retries})")
                            delay_match = re.search(r"'retrydelay': '(\d+)s'", error_message)
                            if delay_match:
                                wait_time = int(delay_match.group(1)) + 1 # API指示時間に1秒追加
                                print(f"      (APIの指示に従い、{wait_time}秒待機します)")
                            else:
                                wait_time = 61 # デフォルトの待機時間 (1分 + 1秒)
                                print(f"      (APIからの待機時間指示なし。デフォルトの{wait_time}秒待機します)")
                            time.sleep(wait_time)
                        
                        # 3. プロジェクトレベルのアクセス拒否 (リトライ不可)
                        #    'user_project_denied' などが含まれる場合。設定ミスの可能性が高い。
                        elif 'user_project_denied' in error_str_lower:
                            print(f"\n[!!!] プロジェクトレベルでアクセスが拒否されました。APIキーやプロジェクト設定を確認してください。")
                            print("処理を終了します。")
                            character_progress["last_file"] = filepath.name
                            character_progress["last_index"] = i - 1 if i > 0 else -1
                            character_progress["total_success_count"] = total_success_count
                            character_progress["total_fail_count"] = total_fail_count
                            save_progress(progress_data)
                            sys.exit(1) # リトライ不可能なエラーのため終了

                        # 4. その他の予期せぬエラー (リトライ対象)
                        #    上記以外のエラー。一定時間待機してリトライする。
                        else:
                            print(f"    - 警告: 予期せぬエラーで記憶に失敗。リトライします。 ({retry_attempt}/{max_retries})")
                            print(f"      (エラー詳細: {error_message[:200]}...)")
                            default_wait_time = 10 # 短めの待機時間
                            print(f"      ({default_wait_time}秒待機します)")
                            time.sleep(default_wait_time)
                        # エラーハンドリングここまで

                else: # 内側のwhileループ (リトライループ) がbreakされずに終わった場合 (リトライ上限到達)
                    print(f"    - エラー: リトライ上限 ({max_retries}回) に達しました。")
                    # ユーザーに次のアクションを選択させるプロンプトを表示
                    while True:
                        user_choice = input("      このペアの処理をどうしますか？ (s: スキップ, r: 再リトライ, q: 終了): ").lower()
                        if user_choice == 's':
                            print("      -> スキップします。")
                            total_fail_count += 1
                            i += 1 # 次のペアへ進む (現在のペアはスキップ)
                            break # ユーザー入力ループを抜ける
                        elif user_choice == 'r':
                            print("      -> 再度リトライします。")
                            # retry_attempt は、このelseブロックを抜けた後、外側の `while i < total_pairs_in_file:` ループが
                            # 同じ `i` で継続される際に、そのループの先頭で `retry_attempt = 0` と初期化されるため、
                            # ここで明示的にリセットする必要はない。ユーザー入力ループを抜けるだけで良い。
                            break # ユーザー入力ループを抜ける (外側のループで同じiでリトライが始まる)
                        elif user_choice == 'q':
                            print("      -> 処理を中断し、進捗を保存して終了します。")
                            character_progress["last_file"] = filepath.name
                            # 現在処理中のペア(i)は未完了のため、その一つ前を記録。
                            # これにより次回再開時にこのペアからリトライできる。
                            character_progress["last_index"] = i - 1 if i > 0 else -1
                            character_progress["total_success_count"] = total_success_count
                            character_progress["total_fail_count"] = total_fail_count
                            save_progress(progress_data)
                            sys.exit(0) # ユーザーの指示により正常終了
                        else:
                            print("      無効な選択です。's', 'r', 'q' のいずれかを入力してください。")

                    if user_choice == 'r': # 'r' (再リトライ) が選択された場合
                        # 同じ i で処理を継続するため、外側のループ (`while i < total_pairs_in_file:`) の
                        # 現在のイテレーションを `continue` で再実行する。
                        # これにより、同じペアに対して `retry_attempt` が0から再開される。
                        continue
                
                # --- 進捗の保存 ---
                # 各ペアの処理試行後 (成功時またはスキップ選択時) に進捗を保存する。
                # (リトライ上限で'q'選択時や1日の上限エラー時は、それぞれのブロック内で保存・終了している)
                #
                # `last_index` は、次に処理を開始すべきペアのインデックスの「一つ前」を指すように保存する。
                # 例えば、ペア `i` が正常に処理された (またはスキップされた) 場合、`i` は次のインデックスに更新されている。
                # そのため `i-1` を保存することで、次回は `(i-1)+1` すなわち元の次のインデックスから再開できる。
                character_progress["last_file"] = filepath.name
                character_progress["last_index"] = i - 1
                character_progress["total_success_count"] = total_success_count
                character_progress["total_fail_count"] = total_fail_count
                save_progress(progress_data)

            print(f"  -> ファイル '{filepath.name}' の処理完了。")
            # ファイル内の全ペア処理完了後、次のファイルから処理を始めるために last_index を -1 に設定。
            # これにより、次回起動時は次のファイルのインデックス0から開始される (last_index + 1)。
            character_progress["last_file"] = filepath.name
            character_progress["last_index"] = -1
            save_progress(progress_data)

        print("\n--- すべての指定ログファイルのインポート試行が終了しました ---")
        print(f"最終結果: 成功 {total_success_count}件, 失敗 {total_fail_count}件")

    finally:
        # ★★★ finallyブロックの中身をこの一行に置き換え ★★★
        release_lock()

if __name__ == "__main__":
    main()
