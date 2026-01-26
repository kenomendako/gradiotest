#!/usr/bin/env python
"""
既存のエピソード記憶にIDを付与するマイグレーションスクリプト

Phase H: 記憶共鳴フィードバック機構のために、既存記憶にも一意なIDを付与する。
"""

import json
import os
from pathlib import Path
from collections import defaultdict

# プロジェクトのルートからの相対パス
CHARACTERS_DIR = Path(__file__).parent.parent / "characters"


def migrate_episodic_memory(memory_file: Path) -> dict:
    """
    エピソード記憶ファイルにIDを付与する。
    
    Returns:
        {"added": int, "skipped": int, "total": int}
    """
    if not memory_file.exists():
        return {"added": 0, "skipped": 0, "total": 0, "error": "ファイルが存在しません"}
    
    try:
        with open(memory_file, 'r', encoding='utf-8') as f:
            episodes = json.load(f)
    except json.JSONDecodeError as e:
        return {"added": 0, "skipped": 0, "total": 0, "error": f"JSONパースエラー: {e}"}
    
    if not episodes:
        return {"added": 0, "skipped": 0, "total": 0}
    
    # 日付ごとの連番を管理
    date_counters = defaultdict(int)
    
    # 既存のIDを収集して連番の開始点を決める
    for ep in episodes:
        if "id" in ep:
            ep_id = ep["id"]
            # episode_2026-01-15_001 形式からカウンターを抽出
            parts = ep_id.split("_")
            if len(parts) >= 3:
                try:
                    date_part = parts[1]
                    seq = int(parts[2])
                    date_counters[date_part] = max(date_counters[date_part], seq)
                except (ValueError, IndexError):
                    pass
    
    added = 0
    skipped = 0
    
    for ep in episodes:
        if "id" in ep:
            skipped += 1
            continue
        
        date_str = ep.get("date", "unknown")
        # 範囲日付の場合は開始日を使用
        if "~" in date_str:
            date_str = date_str.split("~")[0].strip()
        elif "～" in date_str:
            date_str = date_str.split("～")[0].strip()
        else:
            date_str = date_str.strip()
        
        date_counters[date_str] += 1
        ep["id"] = f"episode_{date_str}_{date_counters[date_str]:03d}"
        added += 1
    
    # 保存
    with open(memory_file, 'w', encoding='utf-8') as f:
        json.dump(episodes, f, indent=2, ensure_ascii=False)
    
    return {"added": added, "skipped": skipped, "total": len(episodes)}


def main():
    print("=" * 60)
    print("エピソード記憶 ID マイグレーション")
    print("=" * 60)
    
    if not CHARACTERS_DIR.exists():
        print(f"エラー: {CHARACTERS_DIR} が見つかりません")
        return
    
    total_added = 0
    total_skipped = 0
    
    # 各キャラクターディレクトリを処理
    for char_dir in CHARACTERS_DIR.iterdir():
        if not char_dir.is_dir():
            continue
        
        memory_file = char_dir / "memory" / "episodic_memory.json"
        if not memory_file.exists():
            continue
        
        print(f"\n処理中: {char_dir.name}")
        print(f"  ファイル: {memory_file}")
        
        result = migrate_episodic_memory(memory_file)
        
        if "error" in result:
            print(f"  エラー: {result['error']}")
        else:
            print(f"  結果: 追加={result['added']}, スキップ={result['skipped']}, 合計={result['total']}")
            total_added += result["added"]
            total_skipped += result["skipped"]
    
    print("\n" + "=" * 60)
    print(f"完了: {total_added}件のIDを追加, {total_skipped}件はスキップ")
    print("=" * 60)


if __name__ == "__main__":
    main()
