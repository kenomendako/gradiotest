# エディター向け指示書: モデル名付記バグ修正

## 問題

ルーム個別設定でモデル変更後、タイムスタンプに**古いモデル名**が付記される。

**症状:**
- ターミナル: `gemini-3-pro-preview` (正しい)
- タイムスタンプ: `gemini-2.5-pro` (古い)

## 原因

`agent/graph.py` の `agent_node` 関数が返却値に `model_name` を含めていない。

`ui_handlers.py` は `final_state.get('model_name')` で取得しようとするが `None` になり、フォールバックで古い設定を読み込む。

## 修正箇所

### `agent/graph.py`

**L843** (ツール呼び出しなしの場合):
```python
# 変更前
return {"messages": [response], "loop_count": loop_count, "last_successful_response": response}

# 変更後
return {"messages": [response], "loop_count": loop_count, "last_successful_response": response, "model_name": state['model_name']}
```

**L845** (ツール呼び出しありの場合):
```python
# 変更前
return {"messages": [response], "loop_count": loop_count}

# 変更後
return {"messages": [response], "loop_count": loop_count, "model_name": state['model_name']}
```

### 追加確認: エラーハンドリング

**L861付近** と **L900付近** のエラーハンドリングの返却値も同様に確認し、必要に応じて `model_name` を追加。

## ブランチ

```bash
git checkout -b fix/model-name-timestamp
```

## テスト

1. ルーム個別設定でモデルを `gemini-2.5-pro` から `gemini-3-pro-preview` に変更
2. メッセージを送信
3. タイムスタンプのモデル名が `gemini-3-pro-preview` になっていることを確認
