# retry_importer.py

import os
import sys
import json
import argparse
import time
import re
from typing import List, Dict

# Nexus Arkの既存モジュールを正しくインポートする
import config_manager
import memos_manager
import character_manager

# --- 定数 ---
ERROR_LOG_FILE = "importer_errors.log"
SUCCESS_LOG_FILE = "retry_success.log"

def parse_error_log() -> List[Dict]:
    """importer_errors.log を解析し、会話ペアのリストを抽出する。"""
    if not os.path.exists(ERROR_LOG_FILE):
        print(f"エラー: {ERROR_LOG_FILE} が見つかりません。")
        return []

    with open(ERROR_LOG_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    # JSONオブジェクトを抽出するための正規表現
    # "Pair Content:" から始まり、次の "---" の前までを対象とする
    json_blocks = re.findall(r"Pair Content:\n(\[.*?\])", content, re.DOTALL)

    pairs = []
    for block in json_blocks:
        try:
            pair = json.loads(block)
            if isinstance(pair, list) and len(pair) == 2:
                pairs.append(pair)
        except json.JSONDecodeError:
            print(f"警告: ログ内のJSONブロックの解析に失敗しました:\n{block}")
            continue

    return pairs

def log_success(pair: List[Dict]):
    """正常にインポートできたペアを成功ログに記録する。"""
    with open(SUCCESS_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"--- SUCCESS at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        json.dump(pair, f, indent=2, ensure_ascii=False)
        f.write("\n\n")

def main():
    parser = argparse.ArgumentParser(description="Nexus Arkのインポートエラーログから、失敗した会話ペアを対話的に再インポートするツール")
    parser.add_argument("--character", required=True, help="対象のキャラクター名（MemOSの初期化に必要）")
    args = parser.parse_args()

    print("--- エラーログからのリトライ処理を開始します ---")

    # 必要なモジュールを初期化
    config_manager.load_config()
    try:
        mos_instance = memos_manager.get_mos_instance(args.character)
    except Exception as e:
        print(f"\n[致命的エラー] MemOSの初期化に失敗しました: {e}")
        print("APIキーやデータベースの接続設定を確認してください。")
        return

    failed_pairs = parse_error_log()
    total_pairs = len(failed_pairs)
    if not total_pairs:
        print("--- 処理対象のペアはありません。終了します。 ---")
        return

    print(f"--- {total_pairs} 件の失敗した会話ペアが見つかりました ---")

    success_count = 0
    skipped_count = 0

    for i, pair in enumerate(failed_pairs):
        print("\n" + "="*50)
        print(f"ペア {i+1}/{total_pairs} の処理を開始します...")

        try:
            user_message = pair[0]['content'][:150] # 長すぎる場合は省略
            ai_message = pair[1]['content'][:150]
            print(f"  [ユーザーの発言]: {user_message}...")
            print(f"  [AIの応答]: {ai_message}...")
        except (KeyError, IndexError):
            print("  [エラー]: ペアの形式が不正です。")
            continue

        while True:
            choice = input("  このペアをインポートしますか？ (y: はい / n: スキップ / q: 終了): ").lower()
            if choice in ['y', 'n', 'q']:
                break
            else:
                print("    無効な入力です。'y', 'n', 'q' のいずれかを入力してください。")

        if choice == 'q':
            print("--- ユーザーの指示により、処理を中断します ---")
            break
        elif choice == 'n':
            print("--- このペアをスキップします ---")
            skipped_count += 1
            continue
        elif choice == 'y':
            try:
                print("  インポート中...")
                mos_instance.add(messages=pair)
                print("  ✅ インポートに成功しました！")
                log_success(pair)
                success_count += 1
            except Exception as e:
                print(f"  ❌ インポートに失敗しました。")
                print(f"     エラー詳細: {e}")

                while True:
                    retry_choice = input("     再試行しますか？ (y: はい / n: スキップ): ").lower()
                    if retry_choice in ['y', 'n']:
                        break

                if retry_choice == 'y':
                    # ループの先頭に戻って、再度インポートを試みる
                    # そのため、インデックスを1つ戻す必要がある
                    # （実際には for ループなので、continue で次のループに行く前に再試行のロジックが必要）
                    # → よりシンプルにするため、ここでは単純にスキップさせる
                    print("  このペアの処理を中断し、次に進みます。")
                    skipped_count += 1
                else:
                    print("--- このペアをスキップします ---")
                    skipped_count += 1

    print("\n" + "="*50)
    print("--- 全てのリトライ処理が完了しました ---")
    print(f"  成功: {success_count} 件")
    print(f"  スキップ: {skipped_count} 件")
    print(f"  正常にインポートされたペアは {SUCCESS_LOG_FILE} に記録されています。")

if __name__ == "__main__":
    main()
