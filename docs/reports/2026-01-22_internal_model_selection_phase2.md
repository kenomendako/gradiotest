# 内部モデル選択機能 (Phase 2)

**日付:** 2026-01-22  
**ブランチ:** `feat/internal-model-selection`  
**ステータス:** ✅ 基本実装完了

---

## 問題の概要

内部処理（検索クエリ生成、要約、情景描写など）で使用するモデルがGemini固定（`force_google=True`）だったため、ユーザーが選択できなかった。Phase 2では設定管理とUIを追加し、内部処理モデルをカスタマイズ可能にした。

---

## 修正内容

### 1. 設定管理 (config_manager.py)

4つの新規関数を追加:

| 関数名 | 機能 |
|--------|------|
| `get_internal_model_settings()` | 内部モデル設定を取得（デフォルト値マージ） |
| `save_internal_model_settings()` | 設定を保存 |
| `get_effective_internal_model()` | ロールに応じたプロバイダ・モデル名を取得 |
| `reset_internal_model_settings()` | デフォルトにリセット |

### 2. LLMFactory改修 (llm_factory.py)

- `internal_role`引数追加（"processing", "summarization", "supervisor"）
- `force_google`を後方互換として維持
- プロバイダ優先順位: `internal_role` > `force_google` > ルーム設定

### 3. 呼び出し箇所の修正

| ファイル | 修正内容 |
|---------|---------|
| `agent/graph.py` (2箇所) | 情景描写、検索クエリ生成 → `internal_role="processing"` |
| `motivation_manager.py` | 問い自動解決 → `internal_role="processing"` |
| `entity_memory_manager.py` | 記憶統合 → `internal_role="processing"` |

### 4. UI追加

共通設定タブに「⚙️ 内部処理モデル設定」アコーディオン:
- プロバイダ選択（Google/OpenAI互換）
- 軽量処理モデル、要約モデル、司会モデルのドロップダウン
- 保存/リセットボタン

---

## 変更したファイル

- `config_manager.py` - 設定管理関数4つ追加
- `llm_factory.py` - `internal_role`引数追加
- `agent/graph.py` - 2箇所の呼び出し修正
- `motivation_manager.py` - 1箇所の呼び出し修正
- `entity_memory_manager.py` - 1箇所の呼び出し修正
- `nexus_ark.py` - UI追加
- `ui_handlers.py` - ハンドラ2つ追加

---

## 検証結果

- [x] 設定関数のユニットテスト（デフォルト値取得、ロール別モデル取得）
- [x] シンタックスチェック（全ファイルPASS）
- [ ] 手動検証（UI操作、設定保存・反映）

---

## 残課題

- **SUMMARIZATION_MODEL対応**: 約10箇所が`get_configured_llm`を直接使用しており、`LLMFactory`経由に変更が必要（別タスクとして対応予定）
