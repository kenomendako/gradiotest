# 記憶検索（RAG）の重複除去

## 概要
RAG検索結果で同一コンテンツ・同一スコアのエントリが複数返される問題を修正。

## 問題の詳細
ペルソナAIに渡されるRAG検索結果に重複が含まれていた:
- `Score: 0.3569` のエントリが2件
- `Score: 0.4201` のエントリが3件

### 原因
`rag_manager.py`の`search`メソッドで静的・動的インデックスの検索結果を単純に結合しており、重複除去が行われていなかった。

## 修正内容

### 変更ファイル
- `rag_manager.py` - `RAGManager.search`メソッドに重複除去ロジックを追加

### 修正箇所
```python
# [2026-01-10 追加] コンテンツベースの重複除去
seen_contents = set()
unique_results = []
duplicate_count = 0
for doc, score in results_with_scores:
    # 先頭100文字で重複判定
    content_key = doc.page_content[:100].strip()
    if content_key not in seen_contents:
        seen_contents.add(content_key)
        unique_results.append((doc, score))
    else:
        duplicate_count += 1

if duplicate_count > 0:
    print(f"  - [RAG] 重複除去: {len(results_with_scores)}件 → {len(unique_results)}件 ({duplicate_count}件除去)")
```

## 動作確認
- 重複があった場合、ターミナルに `[RAG] 重複除去: X件 → Y件 (Z件除去)` のログが出力される
- 重複がない場合はログ出力なし

## 関連タスク
- TASK_LIST.md: 記憶想起の重複問題（🟡中優先度）
