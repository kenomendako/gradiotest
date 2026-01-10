# entity_memory_manager.py

import os
import json
from pathlib import Path
from datetime import datetime
import constants

class EntityMemoryManager:
    """
    Manages structured memories about specific entities (people, topics, objects).
    Stores data in Markdown files under room/memory/entities/
    """
    def __init__(self, room_name: str):
        self.room_name = room_name
        self.room_dir = Path(constants.ROOMS_DIR) / room_name
        self.entities_dir = self.room_dir / "memory" / "entities"
        self.entities_dir.mkdir(parents=True, exist_ok=True)

    def _get_entity_path(self, entity_name: str) -> Path:
        # Sanitize entity name for filename
        safe_name = "".join([c for c in entity_name if c.isalnum() or c in (' ', '_', '-')]).rstrip()
        return self.entities_dir / f"{safe_name}.md"

    def create_or_update_entry(self, entity_name: str, content: str, append: bool = False) -> str:
        """
        Creates or updates an entity memory file.
        """
        path = self._get_entity_path(entity_name)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if append and path.exists():
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"\n\n--- Update: {timestamp} ---\n{content}")
            return f"Entity memory for '{entity_name}' updated (appended)."
        else:
            header = f"# Entity Memory: {entity_name}\nCreated: {timestamp}\n\n"
            with open(path, "w", encoding="utf-8") as f:
                f.write(header + content)
            return f"Entity memory for '{entity_name}' created/overwritten."

    def read_entry(self, entity_name: str) -> str:
        """
        Reads the content of an entity memory file.
        """
        path = self._get_entity_path(entity_name)
        if not path.exists():
            return f"Error: No entity memory found for '{entity_name}'."
        
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def list_entries(self) -> list:
        """
        Lists all available entity names.
        """
        return [f.stem for f in self.entities_dir.glob("*.md")]

    def search_entries(self, query: str) -> list:
        """
        Simple keyword search across entity names and contents.
        Returns a list of matching entity names, sorted by relevance (match count).
        
        [2026-01-10 fix] クエリを単語分割して検索するよう修正。
        retrieval_nodeから渡されるrag_queryは複数単語のキーワード群のため、
        クエリ全体ではなく各単語でマッチングする必要がある。
        """
        # クエリを単語に分割（空白で区切る）
        query_words = [w.lower() for w in query.split() if w.strip()]
        if not query_words:
            return []
        
        scored_matches = []
        all_entities = self.list_entries()
        
        for name in all_entities:
            name_lower = name.lower()
            content_lower = self.read_entry(name).lower()
            
            # マッチした単語数をカウント
            match_count = 0
            for word in query_words:
                if word in name_lower or word in content_lower:
                    match_count += 1
            
            if match_count > 0:
                scored_matches.append((name, match_count))
        
        # マッチ数の多い順にソート
        scored_matches.sort(key=lambda x: x[1], reverse=True)
        return [name for name, _ in scored_matches]


    def delete_entry(self, entity_name: str) -> bool:
        """
        Deletes an entity memory file.
        """
        path = self._get_entity_path(entity_name)
        if path.exists():
            path.unlink()
            return True
        return False
