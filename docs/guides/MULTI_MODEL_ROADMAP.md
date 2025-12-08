# Nexus Ark マルチモデル対応ロードマップ：分散と自律の時代へ

## 1. 背景と目的
2025年12月、Gemini APIの無料枠縮小（2.5 Pro廃止、FlashのRPD制限）に伴い、Nexus Arkの持続可能な運用が困難となった。
本プロジェクトは、Google単独依存のリスクを解消し、**OpenRouter** をハブとした多モデル対応、および **Local LLM (Ollama)** による自律運用を実現するための、アーキテクチャ刷新を行う。

## 2. アーキテクチャ改革の方針

### A. 抽象化レイヤー (`llm_factory.py`) の導入
`gemini_api.py` への直接依存を廃止し、設定に基づいて適切なLangChainチャットモデルを生成するファクトリーパターンを導入する。

**対応プロバイダ:**
1.  **Google (Gemini Native):** 既存の無料枠（RPD制限内）および有料枠用。
2.  **OpenAI Compatible:** 業界標準API。以下のサービスを一括でカバーする。
    *   **OpenRouter:** 多数のモデル（無料/有料）への統一ゲートウェイ。
    *   **Groq:** 高速推論（Llama 3等）。
    *   **Ollama:** ローカル環境での完全無料運用。
    *   **OpenAI:** 本家GPT-4o等。

### B. 設定ファイルの構造変更 (`config.json`)
プロバイダごとの設定と、OpenAI互換エンドポイントの柔軟な設定を可能にする。

```json
{
  "active_provider": "openrouter",
  "providers": {
    "google": { ... },
    "openai_compatible": [
      {
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": "sk-or-...",
        "default_model": "google/gemma-2-9b-it:free"
      },
      {
        "name": "Local Ollama",
        "base_url": "http://localhost:11434/v1",
        "api_key": "ollama", 
        "default_model": "phi3.5"
      }
    ]
  }
}
```

## 3. 開発フェーズ

### Phase 1: 基礎工事 (Foundation) - 今回のスコープ
*   [ ] `config_manager.py`: マルチプロバイダ対応の設定構造へ移行。
*   [ ] `llm_factory.py`: `ChatOpenAI` を利用した汎用接続ロジックの実装。
*   [ ] `nexus_ark.py`: 設定タブに「プロバイダ切り替え」「OpenAI互換設定」UIを追加。

### Phase 2: エージェントの移植 (Migration)
*   [ ] `agent/graph.py`: `gemini_api` 依存の排除。`llm_factory` 経由でのモデル取得。
*   [ ] ツール呼び出し（Tool Calling）の互換性検証。
    *   Gemini以外のモデルでは、ツール定義のバインド方法が異なる場合があるため調整する。

### Phase 3: "Bring Your Own AI" (Local & RAG)
*   [ ] **Ollama対応:** ローカルサーバー（`localhost:11434`）への接続テストと、モデル一覧の自動取得。
    *   ※開発環境（低スペック）では `phi3.5` や `gemma2:2b` で動作検証を行う。
*   [ ] **RAGの抽象化:** EmbeddingモデルもGemini依存から脱却し、HuggingFace（ローカル）やOpenAI互換Embeddingに対応させる。

## 4. 推奨モデル戦略

| ユーザー層 | 推奨プロバイダ | 特徴 |
| :--- | :--- | :--- |
| **ライトユーザー** | **OpenRouter (Free)** | 設定が簡単。`meta-llama/llama-3-8b-instruct:free` 等を利用。 |
| **ヘビーユーザー** | **OpenRouter (Paid)** | `anthropic/claude-3.5-sonnet` 等、従量課金で高品質な体験。 |
| **ゲーミングPC勢** | **Ollama** | `llama3.3:70b` 等をローカルで動かし、完全無料・無制限。 |
| **開発者(低スペ)** | **Ollama (Tiny)** | `phi3.5` 等で機能テストを行い、本番はOpenRouterで確認。 |

## 5. 開発のゴール
「Geminiの無料枠が終わった？ 問題ない、OpenRouterの無料モデルに切り替えればいい」とユーザーが言える状態を目指す。