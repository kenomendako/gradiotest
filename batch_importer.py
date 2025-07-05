# batch_importer.py (最終安定版 v4 - 自己修復モード)
import os
import argparse
import time
import json
import traceback
import re # 正規表現モジュールをインポート
from typing import List, Dict

# Nexus Arkの既存モジュールをインポート
import config_manager
import mem0_manager
from utils import load_chat_log

# --- (parse_log_for_mem0 関数は変更なし) ---
def parse_log_for_mem0(log_messages: List[Dict[str, str]]) -> List[List[Dict[str, str]]]:
    conversation_pairs = []
    current_pair = []
    for msg in log_messages:
        # メッセージの役割を'user'か'assistant'に正規化
        # load_chat_logは'role'として'user'または'model'(またはキャラクター名)を返す想定
        # Mem0は'user'と'assistant'を期待する
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

    # ユーザー発言のみで終わったペアは valid_pairs で除外される
    if current_pair and current_pair[0]["role"] == "user" and len(current_pair) == 1: # ユーザー発言のみのペアも一旦追加
        pass # valid_pairs のフィルタリングに任せる

    valid_pairs = [p for p in conversation_pairs if len(p) == 2 and p[0]['role'] == 'user' and p[1]['role'] == 'assistant']
    return valid_pairs

PROGRESS_FILE = "importer_progress.json"

def load_progress():
    """進捗記録ファイルを読み込む"""
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                content = f.read()
                if not content.strip(): # 空ファイルの場合
                    return {}
                return json.loads(content)
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
    parser.add_argument("--model", default="gemini-2.5-flash-lite-preview-06-17", help="インポート処理に使用するAIモデル名 (デフォルト: gemini-2.5-flash-lite-preview-06-17)")
    args = parser.parse_args()

    progress = load_progress()

    if args.reset:
        # 特定のキャラクターの進捗のみをリセットするか、ファイル全体をリセットするか
        # ここではファイル全体をリセットする実装とする
        progress = {}
        if os.path.exists(PROGRESS_FILE):
            try:
                os.remove(PROGRESS_FILE)
                print(f"進捗ファイル '{PROGRESS_FILE}' を削除しました。最初から処理を開始します。")
            except OSError as e:
                print(f"エラー: 進捗ファイル '{PROGRESS_FILE}' の削除に失敗しました: {e}")
                # return # 削除失敗時は処理を続行しない方が安全か、あるいは progress={} で進めるか
        else:
            print("進捗ファイルは存在しません。最初から処理を開始します。")
        save_progress(progress) # リセット後、空の進捗を保存


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
        print(f"エラー: 指定されたログディレクトリ '{args.logs_dir}' が存在しないか、ディレクトリではありません。")
        return

    all_log_files = sorted([f for f in os.listdir(args.logs_dir) if f.endswith(".txt")])
    if not all_log_files:
        print(f"エラー: 指定されたディレクトリ '{args.logs_dir}' に.txtファイルが見つかりません。")
        return

    # キャラクターごとの進捗を取得/初期化
    char_progress = progress.get(args.character, {"processed_files": [], "total_success_count": 0, "total_fail_count": 0})
    processed_files = char_progress.get("processed_files", [])
    total_success_count = char_progress.get("total_success_count", 0)
    total_fail_count = char_progress.get("total_fail_count", 0)


    try:
        print("\n--- Mem0インスタンスの初期化を試みます ---")
        mem0_instance = mem0_manager.get_mem0_instance(args.character, api_key, model_name=args.model)
        print("--- Mem0インスタンスの初期化に成功しました ---")

        for filename in all_log_files:
            if filename in processed_files:
                print(f"\n--- ファイル '{filename}' は処理済みのためスキップします。 ---")
                continue

            print(f"\n--- ファイルを処理中: {filename} ---")
            filepath = os.path.join(args.logs_dir, filename)
            # load_chat_logの第二引数はログファイル内のAI名。args.characterをそのまま使用。
            raw_messages = load_chat_log(filepath, args.character)
            conversation_pairs = parse_log_for_mem0(raw_messages)

            total_pairs_in_file = len(conversation_pairs)
            if total_pairs_in_file == 0:
                print("  -> このファイルには有効な会話ペアが見つかりませんでした。スキップします。")
                processed_files.append(filename)
                char_progress["processed_files"] = processed_files
                # total_success_count, total_fail_count はこのファイルでは変動なし
                progress[args.character] = char_progress
                save_progress(progress)
                continue

            print(f"  -> {total_pairs_in_file} 件の会話ペアを記憶します。")

            i = 0
            while i < total_pairs_in_file:
                pair = conversation_pairs[i]
                try:
                    mem0_instance.add(messages=pair, user_id=args.character)
                    print(f"    - 記憶成功 ({i + 1}/{total_pairs_in_file})")
                    total_success_count += 1
                    i += 1

                    # ★★★ 修正箇所 ★★★
                    # 成功時も、レートリミットを確実に守るため、4.1秒待機する
                    time.sleep(4.1)

                except Exception as e:
                    error_str = str(e)
                    if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str.upper():
                        delay_match = re.search(r"'retryDelay': '(\d+)s'", error_str)
                        wait_time = int(delay_match.group(1)) + 1 if delay_match else 61
                        print(f"      (レートリミットエラー検出。APIの指示に従い {wait_time}秒 待機して再試行します)")
                        time.sleep(wait_time)
                        continue
                    else:
                        print(f"    - 警告: 回復不能なエラーのため、会話ペア ({i + 1}/{total_pairs_in_file}) をスキップします。")
                        # print(f"      (エラー詳細: {e})")
                        total_fail_count += 1
                        i += 1
                        continue # 回復不能エラーなので次のペアへ

            print(f"  -> ファイル '{filename}' の処理完了。")
            processed_files.append(filename)
            char_progress["processed_files"] = processed_files
            char_progress["total_success_count"] = total_success_count
            char_progress["total_fail_count"] = total_fail_count
            progress[args.character] = char_progress
            save_progress(progress)

    except Exception as e:
        print("\nエラー: 処理中に致命的な問題が発生しました。")
        print(traceback.format_exc())
        # この場合でも、ここまでに処理したファイルの進捗は保存されているはず
        char_progress["total_success_count"] = total_success_count # 例外発生時点までのカウントを保存
        char_progress["total_fail_count"] = total_fail_count
        progress[args.character] = char_progress
        save_progress(progress)
        return

    print("\n--- すべての指定ログファイルのインポート試行が終了しました ---")
    print(f"キャラクター「{args.character}」の総合結果: 成功 {total_success_count}件, 失敗 {total_fail_count}件")
    print(f"総処理済みファイル数: {len(processed_files)}")

if __name__ == "__main__":
    main()
