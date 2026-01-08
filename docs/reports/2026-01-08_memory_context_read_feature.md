# 記憶検索「続きを読む」機能の実装レポート

**実装日**: 2026-01-08
**ブランチ**: `feat/memory-continue-reading`

---

## 概要

記憶想起時のキーワード検索結果が500文字で切り詰められた場合に、AIペルソナがその「続き」を取得できる新ツール `read_memory_context` を実装しました。

## 変更内容

### 新規ツール追加

**`tools/memory_tools.py`**

- 新ツール `read_memory_context(search_text, room_name, context_lines=30)` を追加
- 検索テキストを含むログ/日記ファイルから該当箇所とその周辺コンテキスト（最大2000文字）を返却
- 対象: 会話ログ (`log.txt`, `log_archives/`, `log_import_source/`)、日記 (`memory*.txt`)

### エージェント登録

**`agent/graph.py`**

- `read_memory_context` のインポートを追加
- `all_tools` リストに追加
- `tool_short_descriptions` にスキル説明を追加

### ドキュメント更新

**`docs/specifications/MEMORY_SYSTEM_SPECIFICATION.md`**

- 記憶関連ツールの一覧に `read_memory_context` を追記
- 更新履歴に 2026-01-08 のエントリを追加

## 検証結果

- `python3 -m py_compile` による構文チェック: **成功**

## 使用方法

AIペルソナは以下のようにツールを使用できます:

1. `search_past_conversations` で検索を実行
2. 結果が「...（続きがあります）」と表示された場合
3. `read_memory_context` を使用して全文を取得

**例:**
```
search_past_conversations("田中さん", "ルシアン", api_key)
# -> "...お話をしていました。それは本当に...（続きがあります）"

read_memory_context("お話をしていました。それは本当に", "ルシアン")
# -> 完全なコンテキスト（最大2000文字）を返却
```

## 変更ファイル一覧

| ファイル | 変更内容 |
|---------|----------|
| `tools/memory_tools.py` | 新規ツール追加 |
| `agent/graph.py` | インポート・登録・スキル説明追加 |
| `docs/specifications/MEMORY_SYSTEM_SPECIFICATION.md` | 仕様書更新 |
| `docs/INBOX.md` | タスク整理済みに移動 |
