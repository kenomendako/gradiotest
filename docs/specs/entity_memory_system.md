# エンティティ記憶 (Entity Memory) システム仕様書

## 概要

エンティティ記憶は、AIペルソナが会話から抽出した重要な概念（人物、場所、物事など）を長期保存するシステムです。従来の「話題クラスタリング」の後継として、より堅牢でユーザーが直接編集可能な形式を採用しています。

## ファイル構成

- **保存場所**: `rooms/<ルーム名>/entities/`
- **ファイル形式**: Markdown (`.md`)
- **ファイル名**: エンティティ名をファイル名として使用（例: `田中さん.md`）

## 推奨フォーマット

```markdown
# Entity Memory: [エンティティ名]
Created: [作成日時]

[エンティティに関する情報]

---Update: [更新日時]---
[追加情報]
```

## 動作フロー

### 1. 自動抽出（睡眠時記憶整理）

1. `dreaming_manager.py` が直近の会話ログを読み込む
2. RAG検索で関連する過去の記憶を取得
3. AIが両者を比較分析し、重要なエンティティを抽出
4. `entity_updates` としてJSON形式で出力
5. `EntityMemoryManager.create_or_update_entry()` で保存

### 2. 手動編集（UI）

- 「📌 エンティティ記憶」アコーディオンで一覧表示・編集・削除が可能

### 3. 検索・参照（RAG統合）

- `retrieval_node` がコンテキスト検索時にエンティティディレクトリもスキャン
- エージェントツール（`read_entity_memory`, `search_entity_memory` 等）からもアクセス可能

## 関連ファイル

| ファイル | 役割 |
|---------|------|
| `entity_memory_manager.py` | CRUD操作を管理するクラス |
| `tools/entity_tools.py` | エージェント用ツール群 |
| `dreaming_manager.py` | 自動抽出・更新ロジック |
| `ui_handlers.py` | UI操作ハンドラ |
| `agent/graph.py` | RAG統合・ツール登録 |

## 設定

- **`sleep_consolidation.update_entity_memory`**: 睡眠時の自動更新を有効化（デフォルト: `true`）
