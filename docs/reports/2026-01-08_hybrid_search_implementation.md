# ハイブリッド検索の導入レポート

**実装日**: 2026-01-08
**ブランチ**: `feat/hybrid-retrieval` → `main` にマージ済み

---

## 概要

`retrieval_node`（記憶想起ノード）にキーワード検索を追加し、RAG検索（ベクトル検索）と併用するハイブリッド検索を実装しました。

過去にキーワード検索は「ノイズが多い」ため封印されていましたが、7つのノイズ対策を実装し、精度高く復活させました。

---

## 実装内容

### 1. クエリ生成の拡張

LLMが以下の形式で2種類のクエリを生成するようプロンプトを拡張:

```
RAG: 田中さん 友人 知り合い
KEYWORD: 田中
```

- **RAG**: 類義語・関連語を含む広いキーワード群（意味検索用）
- **KEYWORD**: 固有名詞・特定フレーズのみ（0-3語、完全一致検索用）

### 2. キーワード検索用内部関数

`_keyword_search_for_retrieval` 関数を新規追加:

- 検索対象: `log.txt`, `log_archives/*.txt`, `log_import_source/*.txt`
- 送信ログ除外: 既にコンテキストに含まれる直近ログを除外
- 発言者フィルタ: USER/AGENTのみ検索（SYSTEM除外）
- 時間帯別枠取り: 新2 + 古2 + 中間ランダム1 = 計5件

### 3. ノイズ対策一覧

| 対策 | 説明 |
|------|------|
| 特徴的キーワード抽出 | LLMで固有名詞のみ0-3語抽出 |
| 送信ログ除外 | 既にコンテキストにある直近ログを除外 |
| 時間帯別枠取り | 新2 + 古2 + 中間ランダム1 = 計5件 |
| コンテンツベース重複除去 | 先頭200文字で重複判定 |
| 発言者フィルタ | USER/AGENTのみ、SYSTEM除外 |
| 長すぎるブロック切り捨て | 500文字超 +「続きがあります」表示 |
| 短すぎるブロック除外 | 30文字未満はスキップ |

---

## 変更ファイル

| ファイル | 変更内容 |
|----------|----------|
| [agent/graph.py](file:///c:/Users/baken/OneDrive/デスクトップ/gradio_github/gradiotest/agent/graph.py) | `_keyword_search_for_retrieval`関数追加、クエリ生成プロンプト拡張、retrieval_nodeにキーワード検索呼び出し追加 |
| [tools/memory_tools.py](file:///c:/Users/baken/OneDrive/デスクトップ/gradio_github/gradiotest/tools/memory_tools.py) | `search_past_conversations`に時間帯別枠取り拡張、コンテンツベース重複除去、長文切り捨てを追加 |
| [docs/specifications/MEMORY_SYSTEM_SPECIFICATION.md](file:///c:/Users/baken/OneDrive/デスクトップ/gradio_github/gradiotest/docs/specifications/MEMORY_SYSTEM_SPECIFICATION.md) | ハイブリッド検索仕様を追記 |

---

## 動作確認

ターミナルログで以下の出力を確認:

```
[Retrieval] RAGクエリ: '記憶想起 デバッグログ 記憶検索 試行錯誤 改善'
[Retrieval] キーワードクエリ: 'デバッグログ'
-> 日記: ヒット (1370 chars)
-> [時間帯別枠取り] 全8件 → 重複除去後7件 → 選択5件
-> 過去ログ: ヒット (5件)
-> エンティティ記憶: なし
```

---

## 修正したバグ

1. **エンティティ記憶のsearch_query未定義エラー**: `rag_query`への変数名変更に伴う参照漏れを修正
2. **キーワード検索の重複問題**: コンテンツベースの重複除去（先頭200文字）を実装

---

## 今後の課題

- [ ] **専用ツール `get_full_memory_block`** の追加（切り捨てられたブロックの全文取得）
- [ ] **RAGインデックスのチャンク品質改善**（空に近い結果が返る問題）
