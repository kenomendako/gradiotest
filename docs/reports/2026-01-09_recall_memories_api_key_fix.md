# RAG検索（recall_memories）APIキーエラー修正レポート

**日付**: 2026-01-09  
**ブランチ**: `fix/recall-memories-api-key`

---

## 問題の概要

AIペルソナが`recall_memories`ツールを使用した際、「API key not valid. Please pass a valid API key.」エラーが発生していた。

## 根本原因

`agent/graph.py`の`safe_tool_node`関数内で、ツール引数にAPIキーを注入するリストに`recall_memories`が含まれていなかった。

```python
# 修正前（1749行目）
if tool_name in ['generate_image', 'search_past_conversations']:
    tool_args['api_key'] = api_key
```

`recall_memories`はAPIキーを引数として受け取り、`RAGManager`を初期化する際に使用するが、このAPIキーが空のまま渡されていたため、エンベディング取得時にAPIエラーが発生していた。

## 修正内容

### [agent/graph.py](file:///home/baken/nexus_ark/agent/graph.py)
```diff
- if tool_name in ['generate_image', 'search_past_conversations']:
+ if tool_name in ['generate_image', 'search_past_conversations', 'recall_memories']:
```

### [docs/INBOX.md](file:///home/baken/nexus_ark/docs/INBOX.md)
- 元のバグタスクを削除
- APIキー注入ツールリストのリファクタリングタスクを追加（中優先度）

## 検証

- [x] コード修正完了
- [ ] 動作確認（ユーザーによる手動テスト推奨）

## 関連するリファクタリング提案

現在、APIキーが必要なツールはハードコードされたリストで管理されている。新規ツール追加時の漏れを防ぐため、以下のリファクタリングをINBOXに追加済み：

- ツール定義側にメタデータ（`requires_api_key=True`など）を持たせる
- または、定数として一元管理する
