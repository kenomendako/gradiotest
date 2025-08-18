# [batch_importer.py を、この内容で完全に置き換える]

import os
import sys
import json
import argparse
import time
import re
from typing import List, Dict

# 必要なモジュールをインポート
import config_manager
import memos_manager
import character_manager # ★★★ キャラクター名簿を参照するために、インポート ★★★

# --- 定数 ---
PROGRESS_FILE = "importer_progress.json"

# --- 新しい、ログ解析関数 (v4: キャラクター名簿参照版) ---
def parse_log_for_memos(log_content: str, character_name: str, all_character_list: List[str]) -> List[Dict[str, str]]:
    """
    全ての形式のログファイルを解析し、キャラクター名簿に基づいて発言者の役割を正確に判定する。
    """
    messages = []
    pattern = re.compile(r"^(?:##\s|\[.*?\]\s*)?([^:]+):\s*([\sS]*?)(?=\n(?:##\s|\[.*?\]\s*)?[^:]+:|\Z)", re.MULTILINE)

    for match in pattern.finditer(log_content):
        speaker = match.group(1).strip()
        content = match.group(2).strip()

        # ★★★【核心的な修正】★★★
        # 発言者名が、キャラクター名簿（all_character_list）に、存在するかどうかで、役割を判断
        # これにより、グループ会話の、他のAIは'assistant'、それ以外は'user'として、正しく、分類される
        if speaker in all_character_list:
            role = "assistant"
        else:
            role = "user"

        messages.append({"role": role, "content": content})

    return messages

def group_messages_into_pairs(messages: List[Dict[str, str]]) -> List[List[Dict[str, str]]]:
    """
    解析されたメッセージリストを、[ユーザー発言, AI応答] のペアにグループ化する。
    """
    pairs = []
    i = 0
    while i < len(messages):
        # ユーザー発言を探す
        if messages[i]["role"] == "user":
            # 次の発言がAIの応答であれば、ペアとして成立
            if i + 1 < len(messages) and messages[i+1]["role"] == "assistant":
                pairs.append([messages[i], messages[i+1]])
                i += 2 # ペアが見つかったので、2つ進む
                continue
        # ペアが成立しない場合は、1つ進む
        i += 1
    return pairs

# --- 進捗管理 (変更なし) ---
def load_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except (json.JSONDecodeError, IOError): return {}
    return {}

def save_progress(progress_data):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress_data, f, indent=2, ensure_ascii=False)

# --- メイン処理 ---
def main():
    config_manager.load_config() # ★★★ この一行を追加 ★★★
    parser = argparse.ArgumentParser(description="Nexus Arkの過去ログをMemOSに一括インポートするツール")
    parser.add_argument("--character", required=True, help="対象のキャラクター名")
    parser.add_argument("--logs-dir", required=True, help="過去ログファイル（.txt）が格納されているディレクトリのパス")

    args = parser.parse_args()

    try:
        # ★★★【核心的な修正】処理の、開始前に、一度だけ、キャラクター名簿を、取得する ★★★
        all_characters = character_manager.get_character_list()
        print(f"--- 認識しているAIキャラクター名簿: {all_characters} ---")

        mos_instance = memos_manager.get_mos_instance(args.character)

        progress_data = load_progress()
        character_progress = progress_data.get(args.character, {})

        processed_files = set(character_progress.get("processed_files", []))
        total_success_count = character_progress.get("total_success_count", 0)

        log_files = sorted([f for f in os.listdir(args.logs_dir) if f.endswith(".txt") and not f.endswith("_summary.txt")])

        print(f"--- {len(log_files)}個のログファイルを検出しました。インポート処理を開始します。 ---")

        for i, filename in enumerate(log_files):
            if filename in processed_files:
                print(f"\n[{i+1}/{len(log_files)}] ファイルは処理済みです: {filename} ... スキップします。")
                continue

            print(f"\n[{i+1}/{len(log_files)}] ファイル処理開始: {filename}")
            filepath = os.path.join(args.logs_dir, filename)

            with open(filepath, "r", encoding="utf-8", errors='ignore') as f:
                content = f.read()

            # ★★★【核心的な修正】解析関数に、キャラクター名簿を、渡す ★★★
            all_messages = parse_log_for_memos(content, args.character, all_characters)
            conversation_pairs = group_messages_into_pairs(all_messages)

            if not conversation_pairs:
                print("  - 会話ペアが見つかりませんでした。スキップします。")
                processed_files.add(filename)
                continue

            print(f"  - {len(conversation_pairs)} 件の会話ペアを検出。MemOSに記憶します...")

            for pair_idx, pair in enumerate(conversation_pairs):
                try:
                    # addに渡すのは、あくまで、対象キャラクターの、記憶となる、ペアのみ
                    mos_instance.add(messages=pair)
                    total_success_count += 1
                    print(f"\r    - 進捗: {pair_idx + 1}/{len(conversation_pairs)}", end="")
                    time.sleep(0.1)
                except Exception as e:
                    print(f"\n    - エラー: 会話ペア {pair_idx + 1} の記憶中にエラーが発生しました: {e}")

            print("\n  - ファイルの処理が完了しました。")
            processed_files.add(filename)

            character_progress["processed_files"] = list(processed_files)
            character_progress["total_success_count"] = total_success_count
            progress_data[args.character] = character_progress
            save_progress(progress_data)

        print("\n--- 全てのログファイルのインポートが完了しました。 ---")
        print(f"最終結果: {total_success_count}件の会話を記憶しました。")

    except Exception as e:
        error_message = str(e).encode(sys.stdout.encoding, errors='replace').decode(sys.stdout.encoding)
        print(f"\n[致命的エラー] 予期せぬエラーが発生しました: {error_message}")
    finally:
        print("インポーターを終了します。")

if __name__ == "__main__":
    main()
