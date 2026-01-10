# entity_memory_manager.py

import os
import json
from pathlib import Path
from datetime import datetime
import constants
from llm_factory import LLMFactory

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

    def create_or_update_entry(self, entity_name: str, content: str, append: bool = False, consolidate: bool = False, api_key: str = None) -> str:
        """
        Creates or updates an entity memory file.
        - append: Trueの場合、末尾に追記します。
        - consolidate: Trueの場合、既存の記憶と新しい情報をLLMで統合・要約します（api_keyが必要）。
        """
        path = self._get_entity_path(entity_name)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if consolidate and path.exists() and api_key:
            return self.consolidate_entry(entity_name, content, api_key)
        
        if append and path.exists():
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"\n\n--- Update: {timestamp} ---\n{content}")
            return f"Entity memory for '{entity_name}' updated (appended)."
        else:
            header = f"# Entity Memory: {entity_name}\nCreated: {timestamp}\n\n"
            with open(path, "w", encoding="utf-8") as f:
                f.write(header + content)
            return f"Entity memory for '{entity_name}' created/overwritten."

    def consolidate_entry(self, entity_name: str, new_content: str, api_key: str) -> str:
        """
        既存の記憶と新しい情報をLLMで統合・整理します。
        """
        path = self._get_entity_path(entity_name)
        if not path.exists():
            return self.create_or_update_entry(entity_name, new_content)

        existing_content = self.read_entry(entity_name)
        
        # LLMによる統合処理
        llm = LLMFactory.create_chat_model(
            model_name=constants.INTERNAL_PROCESSING_MODEL,
            api_key=api_key,
            generation_config={},
            force_google=True
        )
        
        prompt = f"""
あなたは記憶整理の専門家です。
エンティティ「{entity_name}」に関する既存の記憶と、新しく得られた情報を統合し、一つの洗練されたMarkdownドキュメントとして再構成してください。

【既存の記憶】
{existing_content}

【新しい情報】
{new_content}

【統合ルール】
1. 冗長な表現や重複する情報を排除し、簡潔かつ網羅的にまとめてください。
2. 時系列的な変化（以前はこうだったが、今はこうなった）が重要な場合は、その流れを維持してください。
3. 以前の「--- Update: ... ---」といったセクション区切りは削除し、一つのまとまった文章または適切な見出し構造に整理してください。
4. Markdown形式で出力してください。
5. 前置きや解説は一切不要です。純粋な統合後のコンテンツのみを出力してください。

【出力フォーマット】
# Entity Memory: {entity_name}
(ここに統合された内容を記述)
"""
        try:
            response = llm.invoke(prompt).content.strip()
            
            # 保存
            with open(path, "w", encoding="utf-8") as f:
                f.write(response)
            
            return f"Entity memory for '{entity_name}' consolidated and updated."
        except Exception as e:
            # エラー時はフォールバックとして追記
            print(f"Consolidation error for {entity_name}: {e}")
            return self.create_or_update_entry(entity_name, new_content, append=True)

    def consolidate_all_entities(self, api_key: str):
        """
        すべてのエンティティ記憶ファイルを統合・整理します。
        """
        entities = self.list_entries()
        print(f"  - [Entity Maintenance] {len(entities)}件のエンティティ記憶のメンテナンスを開始します...")
        
        for name in entities:
            # すでに十分に短いものはスキップするなど最適化も可能だが、
            # 最初はすべてのファイルをクリーンアップの対象とする
            path = self._get_entity_path(name)
            if path.exists() and path.stat().st_size > 100: # 100バイト未満は無視
                try:
                    # new_contentを空にして呼び出すことで、既存の情報をクリーンアップする
                    res = self.consolidate_entry(name, "", api_key)
                    print(f"    - '{name}' を整理しました: {res}")
                except Exception as e:
                    print(f"    - '{name}' の整理中にエラー: {e}")

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
