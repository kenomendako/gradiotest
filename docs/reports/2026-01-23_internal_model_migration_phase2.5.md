# Phase 2.5: 内部処理モデル動的選択機能の移行

**日付**: 2026-01-23
**ステータス**: ✅ 完了
**ブランチ**: `feat/summarization-model-migration-v2` → `main` にマージ済み

## 概要

Phase 2（内部モデル選択機能）の拡張として、全ての `get_configured_llm` 直接呼び出しを `LLMFactory.create_chat_model` の `internal_role` 引数経由に移行した。これにより、内部処理モデルの選択が設定ベースで動的に行われるようになった。

## 変更点

### 1. `config_manager.py` - 内部モデル設定関数の追加

| 関数名 | 説明 |
|--------|------|
| `get_internal_model_settings()` | 内部モデル設定を取得（デフォルト値とマージ） |
| `save_internal_model_settings()` | 内部モデル設定を保存 |
| `reset_internal_model_settings()` | 設定をデフォルトにリセット |
| `get_effective_internal_model(role)` | ロールに応じたプロバイダ/モデル名を取得 |

### 2. `llm_factory.py` - `internal_role` 引数の追加

- `create_chat_model` に `internal_role` 引数を追加
- `internal_role` 指定時、`get_effective_internal_model` で設定を自動取得
- 対応ロール: `"processing"`, `"summarization"`, `"supervisor"`

### 3. 移行した呼び出し箇所（計14箇所）

| ファイル | 箇所数 | internal_role |
|---------|-------|--------------|
| `episodic_memory_manager.py` | 4 | summarization |
| `dreaming_manager.py` | 4 | 1 summarization, 3 processing |
| `ui_handlers.py` | 3 | 2 summarization, 1 processing |
| `rag_manager.py` | 1 | processing |
| `tools/memory_tools.py` | 2 | summarization |

## 検証結果

- ✅ シンタックスチェック通過（全5ファイル）
- ✅ アプリ起動テスト成功
- ✅ 睡眠時処理（Dreaming Process）正常動作確認

## 技術的な詳細

### 移行パターン

**移行前:**
```python
from gemini_api import get_configured_llm
llm = get_configured_llm(constants.SUMMARIZATION_MODEL, api_key, settings)
```

**移行後:**
```python
from llm_factory import LLMFactory
llm = LLMFactory.create_chat_model(
    api_key=api_key,
    generation_config=settings,
    internal_role="summarization"
)
```

### 設定の優先順位

1. `internal_role` 引数（最優先）
2. `force_google` 引数
3. ルーム個別設定
4. グローバル設定

## 今後の拡張

- Phase 3: UI設定画面で内部モデルを選択可能にする
- Phase 4: OpenAI/Claude対応（内部処理用）
