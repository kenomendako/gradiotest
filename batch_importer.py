# batch_importer_v9.py (importlibによるチェックとロジック修正版)
import os
import sys
import json
from pathlib import Path
import argparse
import time
import traceback
import re
from typing import List, Dict

# ★修正点1: より確実なライブラリ存在チェック
import importlib.util
psutil_spec = importlib.util.find_spec("psutil")
if psutil_spec is None:
    print("エラー: 'psutil'ライブラリが見つかりません。ロック機能が使用できません。")
    print("このスクリプトの全機能を利用するには、ターミナルで 'pip install psutil' を実行してください。")
    # 存在しない場合は、ロック機能を使わないという選択肢もあるが、安全のため終了する
    sys.exit(1)
# 存在が確認できたので、インポートする
import psutil

# これ以降に、他のライブラリをインポートする
import config_manager
import mem0_manager
from utils import load_chat_log

# --- グローバル・ロック処理 (この関数自体は変更なし) ---
LOCK_FILE_PATH = Path.home() / ".nexus_ark.global.lock"
def check_and_clear_stale_lock():
    if not LOCK_FILE_PATH.exists():
        return True
    try:
        with open(LOCK_FILE_PATH, "r", encoding="utf-8") as f:
            lock_info = json.load(f)
        pid = lock_info.get('pid')
        path = lock_info.get('path', '不明')
        if pid is None:
            print(f"警告: PID情報のないロックファイルが見つかりました: {LOCK_FILE_PATH}")
            LOCK_FILE_PATH.unlink()
            print("-> 不正なロックファイルを削除しました。")
            return True
        if psutil.pid_exists(pid):
            print("エラー: Nexus Arkの別のプロセス（またはバッチ処理）がすでに実行中です。")
            print(f"  - 実行中のプロセスID: {pid}")
            print(f"  - 実行中のフォルダパス: {path}")
            return False
        else:
            print(f"警告: 古いロックファイルが見つかりました (プロセスID: {pid} は実行されていません)。")
            user_input = input("-> このロックファイルを削除して起動しますか？ (y/n): ").lower()
            if user_input == 'y':
                LOCK_FILE_PATH.unlink()
                print("-> 古いロックファイルを削除しました。")
                return True
            else:
                print("-> 起動をキャンセルしました。")
                return False
    except (json.JSONDecodeError, FileNotFoundError): # FileNotFoundErrorもキャッチ
        print(f"警告: ロックファイル '{LOCK_FILE_PATH}' が不正または見つかりませんでした。")
        user_input = input("-> 起動を続行しますか？ (y/n): ").lower() # 起動続行の選択肢は危険なので注意
        if user_input == 'y':
            if LOCK_FILE_PATH.exists():
                try:
                    LOCK_FILE_PATH.unlink()
                    print("-> 不正なロックファイルを削除しました。")
                except Exception as e_unlink:
                    print(f"-> 不正なロックファイルの削除に失敗しました: {e_unlink}")
                    return False
            return True
        return False
    except Exception as e:
        print(f"エラー: ロックファイルの処理中に予期せぬ問題が発生しました: {e}")
        traceback.print_exc() # 詳細なエラーを表示
        return False

# --- (parse_log_for_mem0, load_progress, save_progress 関数は変更なし) ---
def parse_log_for_mem0(log_messages: List[Dict[str, str]]) -> List[List[Dict[str, str]]]:
    conversation_pairs = []
    current_pair = []
    for msg in log_messages:
        role = "assistant" if msg.get("role") == "model" or msg.get("role") not in ["user"] else "user"
        content = msg.get("content", "").strip()
        if not content: continue
        if role == 'user':
            if len(current_pair) == 2: # 前のペアが完成していれば追加
                conversation_pairs.append(current_pair)
            current_pair = [{"role": "user", "content": content}] # 新しいペアを開始
        elif role == 'assistant' and current_pair and current_pair[0]["role"] == "user" and len(current_pair) == 1:
            current_pair.append({"role": "assistant", "content": content})
            conversation_pairs.append(current_pair)
            current_pair = [] # ペア完成したのでリセット
    # ループ後にcurrent_pairがuserのみで残っている場合は、valid_pairsのフィルタで除外される
    valid_pairs = [p for p in conversation_pairs if len(p) == 2 and p[0]['role'] == 'user' and p[1]['role'] == 'assistant']
    return valid_pairs

PROGRESS_FILE = "importer_progress.json"
def load_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                content = f.read()
                if not content.strip(): return {}
                f.seek(0) # 修正: ファイルポインタを先頭に戻す
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"警告: 進捗ファイル '{PROGRESS_FILE}' の読み込みに失敗しました: {e}。リセットして開始します。")
            return {}
    return {}

def save_progress(progress_data):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress_data, f, indent=2, ensure_ascii=False)

def main():
    # main関数の最初にロックチェック
    if not check_and_clear_stale_lock():
        sys.exit(1)

    # try...finallyでロックファイルの作成と削除を保証
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

        progress_data = load_progress()

        if args.reset:
            if args.character in progress_data:
                del progress_data[args.character]
                save_progress(progress_data) # 保存してからメッセージ表示
                print(f"キャラクター「{args.character}」の進捗をリセットしました。")
                print("再度スクリプトを実行して、インポートを開始してください。")
            else:
                print("リセット対象の進捗データはありませんでした。")
            return # リセット処理が完了したのでプログラムを終了

        print("--- 過去ログのインポート処理を開始します ---")
        print(f"対象キャラクター: {args.character}")
        print(f"ログディレクトリ: {args.logs_dir}")
        print(f"使用APIキー名: {args.api_key_name}")
        print(f"使用AIモデル: {args.model}")

        config_manager.load_config()
        api_key = config_manager.API_KEYS.get(args.api_key_name)
        if not api_key or api_key.startswith("YOUR_API_KEY"):
            print(f"エラー: APIキー '{args.api_key_name}' が無効です。処理を中断します。")
            return

        if not os.getenv("MEM0_TELEMETRY_ENABLED"):
            os.environ["MEM0_TELEMETRY_ENABLED"] = "false"
        os.environ['GOOGLE_API_KEY'] = api_key

        if not os.path.isdir(args.logs_dir):
            print(f"エラー: 指定されたログディレクトリ '{args.logs_dir}' が存在しません。")
            return

        all_log_files = sorted([f for f in os.listdir(args.logs_dir) if f.endswith(".txt")])
        if not all_log_files:
            print(f"エラー: 指定されたディレクトリ '{args.logs_dir}' に.txtファイルが見つかりません。")
            return

        character_progress = progress_data.setdefault(args.character, {}) # setdefaultでキーがなければ作成
        last_processed_filename = character_progress.get("last_file", None)
        last_processed_pair_index = character_progress.get("last_index", -1)
        total_success_count = character_progress.get("total_success_count", 0)
        total_fail_count = character_progress.get("total_fail_count", 0)

        start_file_index = all_log_files.index(last_processed_filename) if last_processed_filename in all_log_files else 0

        print("\n--- Mem0インスタンスの初期化を試みます ---")
        mem0_instance = mem0_manager.get_mem0_instance(args.character, api_key, model_name=args.model)
        print("--- Mem0インスタンスの初期化に成功しました ---")

        for file_idx in range(start_file_index, len(all_log_files)):
            filename = all_log_files[file_idx]
            print(f"\n--- ファイル '{filename}' ({file_idx + 1}/{len(all_log_files)}) を処理中... ---")
            filepath = os.path.join(args.logs_dir, filename)

            # load_chat_log の第二引数はログファイル内のAI名。args.character を使用。
            conversation_pairs = parse_log_for_mem0(load_chat_log(filepath, args.character))
            total_pairs_in_file = len(conversation_pairs)

            if total_pairs_in_file == 0:
                print("  -> このファイルには有効な会話ペアがありません。完了として記録します。")
                character_progress["last_file"] = filename # 処理しようとしたファイルとして記録
                character_progress["last_index"] = -1      # そのファイル内のペアは処理していない
                # processed_files リストは使わない方針になったので、以下の行は不要
                # character_progress.setdefault("processed_files", []).append(filename)
                progress_data[args.character] = character_progress
                save_progress(progress_data)
                last_processed_pair_index = -1
                continue

            start_pair_index = last_processed_pair_index + 1 if filename == last_processed_filename else 0
            if start_pair_index > 0:
                print(f"  -> 前回の続きから再開します (このファイルの開始位置: ペア {start_pair_index + 1}/{total_pairs_in_file})")

            print(f"  -> {total_pairs_in_file - start_pair_index} 件の会話ペアを記憶します (ファイル全体では {total_pairs_in_file} 件)。")

            for i in range(start_pair_index, total_pairs_in_file):
                pair = conversation_pairs[i]
                try:
                    mem0_instance.add(messages=pair, user_id=args.character)
                    print(f"    - 記憶成功 (ファイル内: {i + 1}/{total_pairs_in_file})")
                    total_success_count += 1

                    character_progress["last_file"] = filename
                    character_progress["last_index"] = i
                    character_progress["total_success_count"] = total_success_count
                    character_progress["total_fail_count"] = total_fail_count
                    progress_data[args.character] = character_progress
                    save_progress(progress_data)
                    time.sleep(4.1)
                except Exception as e:
                    error_str = str(e)
                    print(f"    - 警告: 会話ペア (ファイル内: {i + 1}/{total_pairs_in_file}) の記憶に失敗。スキップします。")
                    error_str = str(e)
                    # error_str = str(e) # error_str はexceptブロックの先頭で定義済
                    # is_429_error = "429" in error_str or "RESOURCE_EXHAUSTED" in error_str.upper()
                    # current_pair_processed = False # このペアが正常に処理されたか、スキップが確定したか

                    # ↑これらの変数は、このelseブロックの外側、exceptの直後で定義・初期化されている前提

                    # 5. 'quota'が含まれていなかったら、1分あたりの上限と判断し、従来のリトライロジックを実行
                    is_429_error_flag = "429" in error_str or "RESOURCE_EXHAUSTED" in error_str.upper()
                    # current_pair_processed はこのelseブロックに入る前にFalseにリセットされているか確認が必要
                    # → except直後では未定義なので、ここで初期化するのが安全
                    current_pair_processed_in_else = False


                    if is_429_error_flag: # 429エラーの場合のみ詳細解析とリトライを試みる
                        retry_attempt_for_current_pair = 0
                        max_retries_for_per_minute = 3

                        while True: # リトライのループ
                            # is_per_day_limit_detail = False # PerDay判定は上位の'quota' in error_strで行うので不要
                            is_per_minute_limit_detail = False
                            wait_time_for_per_minute = 61

                            try:
                                error_details_list = getattr(e, 'details', None)
                                if callable(error_details_list):
                                    error_details_list = error_details_list()

                                if error_details_list and isinstance(error_details_list, list):
                                    quota_failure_found = False
                                    retry_info_found = False
                                    for detail_item in error_details_list:
                                        item_type = detail_item.get('@type')
                                        if isinstance(detail_item, dict) and item_type == 'type.googleapis.com/google.rpc.QuotaFailure':
                                            quota_failure_found = True
                                            quota_id_str = detail_item.get('quotaId', '')
                                            if quota_id_str:
                                                if "PerMinute" in quota_id_str: is_per_minute_limit_detail = True
                                            else:
                                                violations = detail_item.get('violations', [])
                                                for violation in violations:
                                                    desc_text = violation.get('description', '')
                                                    subj_text = violation.get('subject', '')
                                                    if "PerMinute" in desc_text or "PerMinute" in subj_text:
                                                        is_per_minute_limit_detail = True; break
                                            if is_per_minute_limit_detail: break

                                        elif isinstance(detail_item, dict) and item_type == 'type.googleapis.com/google.rpc.RetryInfo':
                                            retry_info_found = True
                                            delay_str = detail_item.get('retryDelay')
                                            if delay_str:
                                                delay_match_rpc = re.search(r"(\d+)s", delay_str)
                                                if delay_match_rpc:
                                                    wait_time_for_per_minute = int(delay_match_rpc.group(1)) + 1

                                    if not quota_failure_found and not retry_info_found:
                                        delay_match_legacy = re.search(r"'retryDelay': '(\d+)s'", error_str)
                                        if delay_match_legacy:
                                            is_per_minute_limit_detail = True
                                            wait_time_for_per_minute = int(delay_match_legacy.group(1)) + 1

                                if is_per_minute_limit_detail:
                                    if retry_attempt_for_current_pair < max_retries_for_per_minute:
                                        retry_attempt_for_current_pair += 1
                                        print(f"      (レートリミット(PerMinute詳細解析)検出。{wait_time_for_per_minute}秒待機。リトライ {retry_attempt_for_current_pair}/{max_retries_for_per_minute})")
                                        time.sleep(wait_time_for_per_minute)
                                        try:
                                            mem0_instance.add(messages=pair, user_id=args.character)
                                            print(f"    - 記憶成功 (ファイル内: {i + 1}/{total_pairs_in_file}) (リトライ {retry_attempt_for_current_pair}回目で成功)")
                                            total_success_count += 1
                                            current_pair_processed_in_else = True
                                            break # while True リトライのループ
                                        except Exception as retry_e:
                                            e = retry_e; error_str = str(e)
                                            is_429_error_flag = "429" in error_str or "RESOURCE_EXHAUSTED" in error_str.upper()
                                            if not is_429_error_flag:
                                                print(f"    - 警告: リトライ中に予期せぬエラー ({str(e)[:200]})。スキップします。")
                                                total_fail_count +=1; current_pair_processed_in_else = True; break
                                            if 'quota' in error_str.lower():
                                                print(f"    - エラー(リトライ中メッセージ判定): 1日の利用上限に達しました。({error_str[:200]}) 終了します。")
                                                total_fail_count += 1; current_pair_processed_in_else = True # 失敗として処理
                                                character_progress["last_file"] = filename
                                                character_progress["last_index"] = i - 1
                                                character_progress["total_success_count"] = total_success_count
                                                character_progress["total_fail_count"] = total_fail_count
                                                progress_data[args.character] = character_progress
                                                save_progress(progress_data)
                                                sys.exit(1)
                                            continue
                                    else:
                                        print(f"    - 警告: PerMinuteリミット(詳細解析)でリトライ上限。スキップします。({str(e)[:200]})")
                                        total_fail_count += 1; current_pair_processed_in_else = True; break
                                else:
                                    print(f"    - 警告: 429エラー(詳細不明)。スキップします。({str(e)[:200]})")
                                    total_fail_count += 1; current_pair_processed_in_else = True; break

                            except Exception as detail_parse_e:
                                print(f"    - 警告: 429エラー詳細解析中にエラー ({detail_parse_e})。スキップします。({str(e)[:200]})")
                                total_fail_count += 1; current_pair_processed_in_else = True; break
                        # --- リトライwhileループ終了 ---

                    else: # is_429_error_flag が False (元から429ではなかった、かつ 'quota' も含まない)
                        print(f"    - 警告: 会話ペア (ファイル内: {i + 1}/{total_pairs_in_file}) の記憶に失敗(非429,非quota)。スキップします。エラー: {e}")
                        total_fail_count += 1
                        current_pair_processed_in_else = True

                    # --- 'quota' not in error_str.lower() の else ブロックの最後 ---
                    # current_pair_processed_in_else が True (成功 or スキップ確定) になっているはず
                    # 進捗保存は except ブロックの外側で行う
                    # ただし、current_pair_processed_in_else を呼び出し元の current_pair_processed に反映する必要があるか？
                    # → このスコープで完結しているので不要。進捗保存は後続の共通処理で行う。

        # --- except Exception as e: の最後 ---
        # 進捗保存 (PerDayの場合は上でsys.exit済みなので、ここには到達しない)
        # 'quota' in str(e).lower() の評価を再度行うのは冗長なので、フラグを使うか、
        # current_pair_processed が True になっているかで判断する。
        # ただ、str(e) は変わる可能性があるので、元の error_str を使うべき。
        # is_per_day_exit_flag = 'quota' in error_str.lower() # exceptの最初に評価したerror_str

        # if not is_per_day_exit_flag:
        # current_pair_processed が True になっていれば、何らかの処理がされた。
        # PerDayでexitした場合、current_pair_processed は True になっている。
        # やはり、PerDayでexitしなかった場合にのみ、ここで進捗保存するのが正しい。
        # そのためには、PerDayでexitしたかどうかのフラグが必要。
        # → PerDayの場合はsys.exitするので、ここに到達する時点でPerDayではない。
        #   したがって、この進捗保存は常に実行されて問題ない。
        #   ただし、変数のスコープに注意。current_pair_processed は if/else の中で使われている。
        #   PerDayでexitしなかった場合、current_pair_processed_in_else の状態が最終状態。
        #   しかし、進捗保存の character_progress["last_index"] = i は、
        #   PerDayでなければ常に現在のペアiを指す、で良い。

            character_progress["last_file"] = filename
            character_progress["last_index"] = i
            character_progress["total_success_count"] = total_success_count
            character_progress["total_fail_count"] = total_fail_count
            progress_data[args.character] = character_progress
            save_progress(progress_data)

            # --- ファイル内の全ペア処理後 ---
            print(f"  -> ファイル '{filename}' の処理完了。")
            character_progress["last_file"] = filename
            character_progress["last_index"] = -1 # ファイル完了なのでインデックスリセット
            progress_data[args.character] = character_progress
            save_progress(progress_data)
            # last_processed_pair_index は次のファイル処理のためにリセット (ループの先頭で再計算されるため不要かも)
            # last_processed_pair_index = -1 # これは main 関数のローカル変数なので、ここで変更しても影響範囲注意
                                         # → last_processed_index_from_progress を使うように変更したのでこの変数は不要になったはず

            # start_pair_index の計算をループの先頭で行うため、ここで last_processed_pair_index を更新する必要はない
            # → 実際には last_processed_pair_index はループの外の変数なので、ここで更新するのは適切
            #   しかし、ファイル完了時は-1になる、という既存ロジックを踏襲
            if 'last_processed_pair_index' in locals() or 'last_processed_pair_index' in globals():
                 # この変数は load_progress 後に character_progress から取得する形に変更したため、
                 # 直接の代入は不要になっているはず。
                 # last_processed_pair_index = -1 # ファイル完了時はリセット
                 pass


        # --- 全ファイル処理後 ---

        print("\n--- すべての指定ログファイルのインポート試行が終了しました ---")
        print(f"キャラクター「{args.character}」の総合結果: 成功 {total_success_count}件, 失敗 {total_fail_count}件")

    finally:
        if LOCK_FILE_PATH.exists():
            try:
                with open(LOCK_FILE_PATH, "r", encoding="utf-8") as f:
                    lock_info = json.load(f)
                if lock_info.get('pid') == os.getpid():
                    LOCK_FILE_PATH.unlink()
                    print("\nグローバル・ロックファイルを解除し、バッチ処理を終了しました。")
            except Exception as e:
                print(f"\nエラー: グローバル・ロックファイルの解除/確認中に問題が発生しました: {e}")
        else:
            print("\nグローバル・ロックファイルは存在しませんでした。バッチ処理を終了します。")

if __name__ == "__main__":
    main()
