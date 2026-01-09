# RAG検索結果コンテンツ空問題修正レポート

**日付**: 2026-01-09  
**ブランチ**: `fix/rag-empty-content`

---

## 問題の概要

`recall_memories`でRAG検索を実行すると、ヒットはするもののコンテンツが「*」のみになる問題が報告されていた。

## 根本原因

`memory_main.txt`がマークダウン形式の箇条書き（`*   テキスト`）を使用しており、`RecursiveCharacterTextSplitter`（chunk_size=300）による分割時に「*」単体が独立したチャンクとして生成されていた。

デバッグスクリプトで調査した結果、FAISSインデックス内に**27件の「*」のみのドキュメント**が存在していることを特定。

```
=== 統計 ===
空のドキュメント: 0
「*」のみのドキュメント: 27
```

## 修正内容

### [rag_manager.py](file:///home/baken/nexus_ark/rag_manager.py)

1. **`_filter_meaningful_chunks`メソッドを追加（L99-127）**
   - 10文字未満のチャンクを除外
   - マークダウン記号のみのチャンク（`*`, `-`, `#`, `**`等）を除外

2. **フィルタリングを3箇所で適用**
   - `update_memory_index`（L367）
   - `update_knowledge_index`（L407）
   - `update_current_log_index_with_progress`（L443）

### [scripts/debug_faiss_index.py](file:///home/baken/nexus_ark/scripts/debug_faiss_index.py)（新規）
- FAISSインデックスの内容を調査するデバッグスクリプト

## 適用手順

修正を反映するには、既存のインデックスを削除して再作成が必要：

1. `characters/<ルーム名>/rag_data/faiss_index_static` フォルダを削除
2. アプリ起動後、「記憶索引を更新」ボタンを押す

## 検証

- [x] コード修正完了
- [x] コミット完了
- [ ] インデックス再作成テスト（ユーザー確認待ち）
