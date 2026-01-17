#!/usr/bin/env python3
"""
エピソード記憶の月次ファイルへのマイグレーションスクリプト

既存の `episodic_memory.json` を月次ファイル（`memory/episodic/YYYY-MM.json`）に分割する。
元ファイルは `episodic_memory.json.backup` にリネーム。

使用方法:
    python tools/migrate_monthly_episodes.py [--room ROOM_NAME] [--dry-run]
"""

import sys
import os
import json
import re
import shutil
from pathlib import Path
from typing import Dict, List
from datetime import datetime

# パスの設定
sys.path.insert(0, str(Path(__file__).parent.parent))
import constants


def get_month_key(date_str: str) -> str:
    """
    日付文字列からYYYY-MM形式のキーを抽出する。
    範囲日付の場合は開始日を使用。
    """
    try:
        # 範囲日付の処理
        if '~' in date_str:
            date_str = date_str.split('~')[0].strip()
        elif '～' in date_str:
            date_str = date_str.split('～')[0].strip()
        
        # YYYY-MM形式を抽出
        match = re.match(r'^(\d{4}-\d{2})', date_str.strip())
        if match:
            return match.group(1)
    except Exception:
        pass
    
    return "unknown"


def migrate_room(room_dir: Path, dry_run: bool = False) -> Dict:
    """
    1つのルームのエピソード記憶を月次ファイルに移行する。
    
    Returns:
        {"status": "success" | "skipped" | "error", "message": str, "details": dict}
    """
    legacy_file = room_dir / "memory" / "episodic_memory.json"
    episodic_dir = room_dir / "memory" / "episodic"
    backup_file = room_dir / "memory" / "episodic_memory.json.backup"
    
    result = {
        "room": room_dir.name,
        "status": "skipped",
        "message": "",
        "details": {}
    }
    
    # レガシーファイルが存在しない場合はスキップ
    if not legacy_file.exists():
        result["message"] = "episodic_memory.json が存在しません"
        return result
    
    # すでにバックアップが存在する場合はスキップ（移行済み）
    if backup_file.exists():
        result["message"] = "既に移行済み（バックアップファイルが存在）"
        return result
    
    try:
        # レガシーファイルを読み込み
        with open(legacy_file, 'r', encoding='utf-8') as f:
            episodes = json.load(f)
        
        if not isinstance(episodes, list):
            result["status"] = "error"
            result["message"] = "ファイル形式が不正（配列ではない）"
            return result
        
        if not episodes:
            result["message"] = "エピソードが空"
            return result
        
        # 月ごとにグループ化
        monthly_groups: Dict[str, List[Dict]] = {}
        for ep in episodes:
            date_str = ep.get('date', '')
            month_key = get_month_key(date_str)
            if month_key not in monthly_groups:
                monthly_groups[month_key] = []
            monthly_groups[month_key].append(ep)
        
        result["details"] = {
            "total_episodes": len(episodes),
            "monthly_files": len(monthly_groups),
            "breakdown": {k: len(v) for k, v in monthly_groups.items()}
        }
        
        if dry_run:
            result["status"] = "dry_run"
            result["message"] = f"{len(episodes)}件を{len(monthly_groups)}個のファイルに分割予定"
            return result
        
        # エピソードディレクトリを作成
        episodic_dir.mkdir(parents=True, exist_ok=True)
        
        # 各月次ファイルに保存
        for month_key, month_episodes in monthly_groups.items():
            # 日付順にソート
            month_episodes.sort(key=lambda x: x.get('date', '').split('~')[0].split('～')[0])
            
            monthly_file = episodic_dir / f"{month_key}.json"
            with open(monthly_file, 'w', encoding='utf-8') as f:
                json.dump(month_episodes, f, ensure_ascii=False, indent=2)
            
            print(f"    - {month_key}.json: {len(month_episodes)}件")
        
        # 元ファイルをバックアップとしてリネーム
        shutil.move(str(legacy_file), str(backup_file))
        
        result["status"] = "success"
        result["message"] = f"{len(episodes)}件を{len(monthly_groups)}個のファイルに移行完了"
        return result
        
    except Exception as e:
        result["status"] = "error"
        result["message"] = f"エラー: {e}"
        return result


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="エピソード記憶を月次ファイルに移行")
    parser.add_argument("--room", type=str, help="特定のルームのみ処理")
    parser.add_argument("--dry-run", action="store_true", help="実際には変更せず、プレビューのみ")
    args = parser.parse_args()
    
    rooms_dir = Path(constants.ROOMS_DIR)
    
    if not rooms_dir.exists():
        print(f"エラー: ルームディレクトリが存在しません: {rooms_dir}")
        sys.exit(1)
    
    print("=" * 60)
    print("エピソード記憶 月次ファイル移行スクリプト")
    print("=" * 60)
    print()
    
    if args.dry_run:
        print("🔍 ドライランモード（実際の変更は行いません）")
        print()
    
    # 対象ルームの取得
    if args.room:
        room_dirs = [rooms_dir / args.room]
        if not room_dirs[0].exists():
            print(f"エラー: ルーム '{args.room}' が見つかりません")
            sys.exit(1)
    else:
        room_dirs = [d for d in rooms_dir.iterdir() if d.is_dir() and not d.name.startswith('.')]
    
    results = []
    for room_dir in sorted(room_dirs):
        print(f"📂 {room_dir.name}:")
        result = migrate_room(room_dir, dry_run=args.dry_run)
        results.append(result)
        
        status_emoji = {
            "success": "✅",
            "skipped": "⏭️",
            "error": "❌",
            "dry_run": "🔍"
        }.get(result["status"], "❓")
        
        print(f"   {status_emoji} {result['message']}")
        
        if result["details"]:
            details = result["details"]
            if "breakdown" in details:
                breakdown_str = ", ".join([f"{k}: {v}件" for k, v in sorted(details["breakdown"].items())])
                print(f"      詳細: {breakdown_str}")
        print()
    
    # サマリー
    print("=" * 60)
    print("サマリー")
    print("=" * 60)
    
    success_count = sum(1 for r in results if r["status"] == "success")
    skipped_count = sum(1 for r in results if r["status"] == "skipped")
    error_count = sum(1 for r in results if r["status"] == "error")
    dry_run_count = sum(1 for r in results if r["status"] == "dry_run")
    
    print(f"  ✅ 成功: {success_count}")
    print(f"  ⏭️ スキップ: {skipped_count}")
    print(f"  ❌ エラー: {error_count}")
    if args.dry_run:
        print(f"  🔍 ドライラン対象: {dry_run_count}")
    
    if args.dry_run and dry_run_count > 0:
        print()
        print("💡 実際に移行するには --dry-run を外して再実行してください")


if __name__ == "__main__":
    main()
