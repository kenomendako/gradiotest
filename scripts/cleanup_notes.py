#!/usr/bin/env python3
"""
ノートデータクリーンアップスクリプト

問題:
- 同じタイムスタンプが1行ごとに繰り返される（コマ切れ）
- 空のセクション（日付のみ）

解決:
- 連続する同一タイムスタンプをマージ
- 空セクションを削除
"""

import re
import sys
import os
from pathlib import Path

def cleanup_notes(content: str) -> str:
    """ノート内容をクリーンアップする"""
    
    # タイムスタンプパターン
    # 形式1: 📝 YYYY-MM-DD HH:MM
    # 形式2: [YYYY-MM-DD HH:MM]
    timestamp_pattern_1 = re.compile(r'^📝\s*(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s*$', re.MULTILINE)
    timestamp_pattern_2 = re.compile(r'^\[(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\]', re.MULTILINE)
    separator_pattern = re.compile(r'^---+$', re.MULTILINE)
    
    # セクションに分割（--- で区切る）
    raw_sections = re.split(r'\n---+\n', content)
    
    cleaned_sections = []
    current_timestamp = None
    current_content_parts = []
    
    for section in raw_sections:
        section = section.strip()
        if not section:
            continue
        
        # セクションからタイムスタンプを抽出
        match1 = timestamp_pattern_1.search(section)
        match2 = timestamp_pattern_2.search(section)
        
        if match1:
            timestamp = f"{match1.group(1)} {match1.group(2)}"
            # タイムスタンプ行を除いたコンテンツ
            content_part = section[match1.end():].strip()
        elif match2:
            timestamp = f"{match2.group(1)} {match2.group(2)}"
            content_part = section[match2.end():].strip()
        else:
            # タイムスタンプなしのセクション
            timestamp = None
            content_part = section
        
        # 空のコンテンツをスキップ
        # 「---」だけの場合もスキップ
        if not content_part or content_part == "---":
            continue
        
        # 同じタイムスタンプならマージ
        if timestamp and timestamp == current_timestamp:
            current_content_parts.append(content_part)
        else:
            # 前のセクションを保存
            if current_content_parts:
                merged_content = "\n\n".join(current_content_parts)
                if current_timestamp:
                    cleaned_sections.append(f"📝 {current_timestamp}\n\n{merged_content}")
                else:
                    cleaned_sections.append(merged_content)
            
            # 新しいセクションを開始
            current_timestamp = timestamp
            current_content_parts = [content_part] if content_part else []
    
    # 最後のセクションを保存
    if current_content_parts:
        merged_content = "\n\n".join(current_content_parts)
        if current_timestamp:
            cleaned_sections.append(f"📝 {current_timestamp}\n\n{merged_content}")
        else:
            cleaned_sections.append(merged_content)
    
    # セクションを結合
    result = "\n\n---\n\n".join(cleaned_sections)
    
    return result


def main():
    if len(sys.argv) < 2:
        print("Usage: python cleanup_notes.py <file_path>")
        print("       python cleanup_notes.py <file_path> --dry-run")
        sys.exit(1)
    
    file_path = Path(sys.argv[1])
    dry_run = "--dry-run" in sys.argv
    
    if not file_path.exists():
        print(f"Error: File not found: {file_path}")
        sys.exit(1)
    
    # 読み込み
    content = file_path.read_text(encoding='utf-8')
    original_lines = len(content.split('\n'))
    
    # クリーンアップ
    cleaned = cleanup_notes(content)
    cleaned_lines = len(cleaned.split('\n'))
    
    print(f"Original: {original_lines} lines")
    print(f"Cleaned:  {cleaned_lines} lines")
    print(f"Removed:  {original_lines - cleaned_lines} lines")
    
    if dry_run:
        print("\n--- DRY RUN: First 100 lines of cleaned output ---\n")
        print('\n'.join(cleaned.split('\n')[:100]))
    else:
        # バックアップ作成
        backup_path = file_path.with_suffix(file_path.suffix + '.backup')
        file_path.rename(backup_path)
        print(f"Backup created: {backup_path}")
        
        # 保存
        file_path.write_text(cleaned, encoding='utf-8')
        print(f"Saved: {file_path}")


if __name__ == "__main__":
    main()
