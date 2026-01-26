
import sys
import os
import re

# Mocking modules that might be imported by ui_handlers
from unittest.mock import MagicMock
sys.modules['gradio'] = MagicMock()
sys.modules['pandas'] = MagicMock()
sys.modules['room_manager'] = MagicMock()
sys.modules['constants'] = MagicMock()
sys.modules['constants'].ROOMS_DIR = "/home/baken/nexus_ark/characters" # Local rooms dir

# Import the code to test
import ui_handlers

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
    
    entries = ui_handlers._parse_notes_entries(content)
    
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
