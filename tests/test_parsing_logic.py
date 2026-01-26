
import re

def _parse_notes_entries(content: str) -> list:
    """
    タイムスタンプセクションでノートをパースしてエントリリストを返す。
    形式: --- で始まり、📝 YYYY-MM-DD HH:MM のヘッダーがあるセクション
    あるいは --- で始まり、[YYYY-MM-DD HH:MM] のヘッダーがあるセクション
    """
    import re
    entries = []
    
    # 区切り線(---)の後にタイムスタンプが続く場合のみ分割
    sections = re.split(r'\n---+\n\s*(?=📝|\[)', content)
    
    for section in sections:
        section = section.strip()
        if not section:
            continue
        
        # タイムスタンプを探す (📝 YYYY-MM-DD HH:MM 形式)
        match1 = re.search(r'📝\s*(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})', section)
        # [YYYY-MM-DD HH:MM] 形式
        match2 = re.search(r'\[(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\]', section)
        
        if match1:
            date_str = match1.group(1)
            time_str = match1.group(2)
            timestamp = f"{date_str} {time_str}"
            # ヘッダー行を除いたコンテンツ
            content_start = match1.end()
            entry_content = section[content_start:].strip()
        elif match2:
            date_str = match2.group(1)
            time_str = match2.group(2)
            timestamp = f"{date_str} {time_str}"
            content_start = match2.end()
            entry_content = section[content_start:].strip()
        else:
            # タイムスタンプがない場合はセクション全体を1つのエントリとして扱う
            timestamp = "日付なし"
            date_str = ""
            entry_content = section
        
        if entry_content:
            entries.append({
                "timestamp": timestamp,
                "date": date_str,
                "content": entry_content,
                "raw_section": section
            })
    
    # ここが追加された修正箇所
    return entries[::-1]

def test_notes_order():
    # Sample content with 3 entries
    content = """
---
📝 2026-01-01 10:00
Oldest entry
---
📝 2026-02-01 10:00
Middle entry
---
📝 2026-03-01 10:00
Latest entry
"""
    
    entries = _parse_notes_entries(content)
    
    print(f"Total entries: {len(entries)}")
    for i, e in enumerate(entries):
        print(f"Index {i}: {e['timestamp']} - {e['content'][:20]}")
    
    # Check if index 0 is the latest
    assert "2026-03-01" in entries[0]['timestamp']
    assert "Latest entry" in entries[0]['content']
    
    # Check if index 2 is the oldest
    assert "2026-01-01" in entries[-1]['timestamp']
    assert "Oldest entry" in entries[-1]['content']
    
    print("Verification SUCCESS: Latest entry is at index 0.")

if __name__ == "__main__":
    test_notes_order()
