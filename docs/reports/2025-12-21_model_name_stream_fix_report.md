# モデル名タイムスタンプ不一致バグ 修正レポート（第2弾）

**日付**: 2025-12-21  
**ブランチ**: `fix/model-name-mismatch`  
**ステータス**: ✅ 完了・マージ済み

---

## 問題

ターミナルでは正しいモデル名（`gemini-3-flash-preview`）が表示されているにもかかわらず、チャットログのタイムスタンプには古いモデル名（`gemini-2.5-...`）が付記される。

**症状**:
- ターミナル: `使用モデル: gemini-3-flash-preview` ✅
- チャットログ: `2025-12-21 (Sun) 19:22:45 | gemini-2.5-` ❌

## 根本原因

LangGraphの`app.stream()`の動作仕様に起因する問題。

```
グラフ実行フロー:
supervisor → context_generator → retrieval_node → agent → (safe_tool_node ↔ agent) → 終了
```

1. `agent_node`は正しく`{"model_name": "gemini-3-flash-preview"}`を返す
2. しかし、`app.stream()`は各ノード実行後に`values`ペイロードを発行
3. 最終的な`final_state`は、**最後に実行されたノードの返り値**で状態が更新される
4. `safe_tool_node`等が`model_name`を返さない場合、`final_state`には初期値（古いモデル名）が残る

## 修正内容

### [ui_handlers.py](../../ui_handlers.py)

**変更1: ストリーム処理中の`model_name`キャプチャ (L1003-1022)**

```python
# 【重要】model_nameはストリームの途中で取得できた値を保持する
captured_model_name = None
for mode, chunk in gemini_api.invoke_nexus_agent_stream(agent_args_dict):
    if mode == "values":
        final_state = chunk
        if chunk.get("model_name"):
            captured_model_name = chunk.get("model_name")  # NEW
```

**変更2: タイムスタンプ生成時の優先順位 (L1118-1131)**

```python
# 優先順位: 1.captured_model_name → 2.final_state → 3.effective_settings
actual_model_name = captured_model_name or (final_state.get("model_name") if final_state else None)
```

## 関連情報

- 前回の修正: [2025-12-21_model_name_timestamp_fix_report.md](2025-12-21_model_name_timestamp_fix_report.md)
  - `agent_node`に`model_name`を返り値として追加した修正
- 今回の修正はその続編で、**ストリーム処理側の取得ロジック**を強化

## 教訓

> **LangGraphのストリームにおいて、最終状態（final_state）は最後のノード出力に依存する。**
> 途中のノードが返した値を確実に取得するには、ストリーム処理中に都度キャプチャする必要がある。
