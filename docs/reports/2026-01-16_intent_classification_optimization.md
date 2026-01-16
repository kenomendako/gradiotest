# Intent分類APIコスト最適化レポート

**日付:** 2026-01-16  
**ブランチ:** `feat/intent-classification-optimization`  
**ステータス:** ✅ 完了

---

## 問題の概要

Intent-Aware Retrieval（Phase 1-3で実装）では、記憶検索のたびにIntent分類のためのLLM呼び出しが発生していた。retrieval_nodeでのクエリ生成と重複するため、API呼び出しを統合してコスト削減を図った。

---

## 修正内容

**retrieval_nodeでIntent分類を統合**し、API呼び出しを1回に削減：

1. **プロンプト拡張**: RAG/KEYWORDに加えてINTENT行も出力
2. **パース処理追加**: INTENT行を抽出しsearch_memoryに渡す
3. **LLM分類スキップ**: intentが渡された場合はLLM分類をスキップ

---

## 変更したファイル

- `agent/graph.py` - retrieval_nodeのプロンプトとパース処理
- `tools/memory_tools.py` - search_memoryにintentパラメータ追加
- `rag_manager.py` - search()でintent受け取り時はLLM分類をスキップ
- `docs/specifications/MEMORY_SYSTEM_SPECIFICATION.md` - 処理フロー更新

---

## 検証結果

- [x] 構文チェック通過
- [x] アプリ起動確認
- [x] ログで`[pre-classified]`表示を確認（LLM分類スキップの証拠）

**コスト削減効果:** 検索1回あたり **2 API calls → 1 API call**

---

## 残課題

なし（完了）
