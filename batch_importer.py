# -*- coding: utf-8 -*-
# batch_importer.py (v5: 全面改修版)
# 指定されたディレクトリ内の全てのログファイルを順次処理し、記憶をMOSに移植する。
# 中断・再開に対応した堅牢な進捗管理機能を備える。

import os
import sys
import json
import time
import argparse
import traceback
from pathlib import Path
from typing import List, Dict, Any

import memos_manager
import config_manager
from utils import load_chat_log, acquire_lock, release_lock

PROGRESS_FILE = "importer_progress.json"

def load_progress() -> Dict[str, Any]:
    """進捗記録ファイルを読み込む。"""
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                content = f.read()
                if not content.strip():
                    return {}
                return json.loads(content)
        except (json.JSONDecodeError, IOError) as e:
            print(f"[警告] 進捗ファイル '{PROGRESS_FILE}' の読み込みに失敗しました: {e}")
            return {}
    return {}

def save_progress(progress_data: Dict[str, Any]):
    """進捗記録ファイルに書き込む。"""
    try:
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(progress_data, f, indent=2, ensure_ascii=False)
    except IOError as e:
        print(f"[エラー] 進捗ファイル '{PROGRESS_FILE}' の保存に失敗しました: {e}")


def parse_log_for_import(log_messages: List[Dict[str, str]]) -> List[List[Dict[str, str]]]:
    """ログデータからユーザーとアシスタントの会話ペアを抽出する。"""
    conversation_pairs = []
    current_pair = []
    for msg in log_messages:
        # MemOSの役割（user, assistant）に正規化
        role = "assistant" if msg.get("role") == "model" else "user"
        content = msg.get("content", "").strip()
        if not content:
            continue

        if role == 'user':
            if len(current_pair) == 2: # 完成済みのペアがあれば確定
                conversation_pairs.append(current_pair)
                current_pair = []
            # ユーザー発言から新しいペアを開始
            if not current_pair:
                current_pair.append({"role": "user", "content": content})
        elif role == 'assistant' and current_pair and current_pair[0]["role"] == "user":
            # ユーザー発言に続くアシスタント発言でペアを完成
            current_pair.append({"role": "assistant", "content": content})
            conversation_pairs.append(current_pair)
            current_pair = [] # ペアをリセット

    return conversation_pairs


def main():
    """メイン処理"""
    # UIからサブプロセスとして呼び出されることを想定し、ロック処理は行わない
    try:
        parser = argparse.ArgumentParser(
            description="過去の会話ログをMemOSに一括でインポートするバッチ処理ツール。",
            formatter_class=argparse.RawTextHelpFormatter
        )
        parser.add_argument("--character", required=True, help="記憶の持ち主であるキャラクター名。")
        parser.add_argument("--logs-dir", required=True, help="複数のログファイル(.txt)が格納されたディレクトリのパス。")
        parser.add_argument("--reset", action="store_true", help="指定したキャラクターのインポート進捗をリセットし、最初からやり直します。")
        args = parser.parse_args()

        # --- 初期設定 ---
        config_manager.load_config()
        mos_instance = memos_manager.get_mos_instance(args.character)

        # --- 進捗の読み込みとリセット ---
        progress_data = load_progress()
        if args.reset and args.character in progress_data:
            print(f"キャラクター '{args.character}' の進捗をリセットします。")
            del progress_data[args.character]
            save_progress(progress_data)

        character_progress = progress_data.setdefault(args.character, {
            "last_processed_file": None,
            "last_processed_pair_index": -1,
            "total_success_count": 0,
            "total_fail_count": 0
        })

        # --- ログファイルのリストアップとソート ---
        logs_path = Path(args.logs_dir)
        if not logs_path.is_dir():
            print(f"[エラー] 指定されたログディレクトリが見つかりません: {args.logs_dir}")
            sys.exit(1)

        # アルファベット順（log_01, log_02...）にソート
        log_files = sorted([p for p in logs_path.glob("*.txt") if not p.name.endswith("_summary.txt")])

        if not log_files:
            print("処理対象のログファイルがありません。")
            sys.exit(0)

        print(f"--- {len(log_files)}個のログファイルを検出しました。インポート処理を開始します。 ---")

        # --- 中断箇所から処理を再開するための準備 ---
        start_file_index = 0
        last_file = character_progress.get("last_processed_file")
        if last_file:
            try:
                # ファイル名だけで比較
                start_file_index = [p.name for p in log_files].index(last_file)
            except ValueError:
                print(f"[警告] 前回のファイル '{last_file}' が見つかりません。最初から処理します。")
                character_progress["last_processed_pair_index"] = -1

        # --- メインループ: ファイル単位の処理 ---
        for i in range(start_file_index, len(log_files)):
            filepath = log_files[i]
            print(f"\n[{i+1}/{len(log_files)}] ファイル処理開始: {filepath.name}")

            log_data = load_chat_log(str(filepath), args.character)
            conversation_pairs = parse_log_for_import(log_data)

            if not conversation_pairs:
                print("  - 会話ペアが見つかりませんでした。スキップします。")
                continue

            # --- 中断箇所から処理を再開 ---
            start_pair_index = 0
            # 現在のファイルが前回中断したファイルの場合、中断したペアの次から開始
            if filepath.name == character_progress.get("last_processed_file"):
                start_pair_index = character_progress.get("last_processed_pair_index", -1) + 1

            print(f"  - {len(conversation_pairs)}個の会話ペアを検出。{start_pair_index + 1}番目から処理を開始します。")

            # --- サブループ: 会話ペア単位の処理 ---
            for j in range(start_pair_index, len(conversation_pairs)):
                pair = conversation_pairs[j]

                try:
                    # ★★★ MemOSへの記憶追加 ★★★
                    mos_instance.add(messages=pair)

                    character_progress["total_success_count"] += 1
                    print(f"    - 記憶成功 ({j + 1}/{len(conversation_pairs)})", end="\r")
                    time.sleep(1.2)  # APIのレート制限を考慮

                except Exception as e:
                    character_progress["total_fail_count"] += 1
                    print(f"\n    - [エラー] 記憶追加に失敗 ({j + 1}/{len(conversation_pairs)}): {e}")
                    # UIからの実行を想定し、自動でスキップする

                finally:
                    # --- 各ペア処理後に進捗を保存 ---
                    character_progress["last_processed_file"] = filepath.name
                    character_progress["last_processed_pair_index"] = j
                    save_progress(progress_data)

            print(f"\n  - ファイル '{filepath.name}' の処理完了。")
            # ファイルが完了したら、次のファイルは最初から処理するためインデックスをリセット
            character_progress["last_processed_pair_index"] = -1
            save_progress(progress_data)

        print("\n--- 全てのログファイルのインポートが完了しました。 ---")
        print(f"最終結果: 成功 {character_progress['total_success_count']}件, 失敗 {character_progress['total_fail_count']}件")

    except KeyboardInterrupt:
        print("\n[情報] ユーザーの操作により処理が中断されました。進捗は保存されています。")
    except Exception as e:
        print(f"\n[致命的エラー] 予期せぬエラーが発生しました: {e}")
        traceback.print_exc()
    finally:
        print("インポーターを終了します。")

if __name__ == "__main__":
    main()
