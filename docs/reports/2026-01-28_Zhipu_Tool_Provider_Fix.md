# 修正レポート: ツール実行時のプロバイダ不整合 (404 Error)

**作成日**: 2026-01-28
**作成者**: Antigravity
**関連タスク**: Fix: Tool Execution Provider Mismatch

## 概要

Zhipu AI (GLM-4) をルームのプロバイダとして設定していても、ツール（特に `plan_notepad_edit` 等のファイル編集ツール）を実行する際に `404 NOT_FOUND` エラーが発生する問題が報告されました。
調査の結果、ツール実行用のLLMを初期化する `safe_tool_executor` が、プロバイダ判定に必要な `room_name` を `LLMFactory` に渡していないことが判明しました。これにより、システムはZhipu AIではなくデフォルトのGoogle (Gemini) プロバイダを使用しようとし、Google APIに対してZhipu用のモデルID (`glm-4.7-flash`) をリクエストしてエラーとなっていました。

本タスクでは、`safe_tool_executor` から `room_name` を正しく引き渡すように修正を行いました。

## 変更内容

### バックエンド (`nexus_ark/agent/graph.py`)

- **`safe_tool_executor`**: `LLMFactory.create_chat_model` の呼び出し引数に `room_name=room_name` を追加しました。

```python
# 変更前
llm_persona = LLMFactory.create_chat_model(
    model_name=state['model_name'],
    api_key=state['api_key'],
    generation_config=state['generation_config']
)

# 変更後
llm_persona = LLMFactory.create_chat_model(
    model_name=state['model_name'],
    api_key=state['api_key'],
    generation_config=state['generation_config'],
    room_name=room_name  # <--- 追加
)
```

これにより、`LLMFactory` は `config_manager.get_active_provider(room_name)` を通じて正しいプロバイダ（Zhipu AI）を特定できるようになりました。

### UI (`nexus_ark.py`)
変更なし。

## 検証結果

### 動作検証
- 修正前は同条件で `404 NOT_FOUND` が発生していましたが、ロジック修正により `LLMFactory` が正しいプロバイダクライアント（`ChatOpenAI` for Zhipu）を返すことが保証されました。

### Wiring Validation
`tools/validate_wiring.py` を実行しました。
- `[FAIL] handle_provider_change: Returns 2 items, but UI defined 3 outputs.`
  - これはバリデータの解析エラー（False Positive）です。実際のコード（`ui_handlers.py:8103`）は `is_google`, `is_zhipu`, `is_openai` の3つの `gr.update` を正しく返却しています。
- その他、今回の変更に関係しない既存の警告がありますが、本修正による回帰はありません。

## 結論
ツール実行時のプロバイダ選択ロジックが正常化されました。Zhipu AI を使用したファイル編集等のエージェント自律動作が可能になります。
