# Nexus Ark マルチモデル対応ロードマップ：Google依存からの脱却

## 1. 背景と目的
2025年12月、Gemini APIの無料枠縮小（2.5 Pro廃止、FlashのRPD制限）に伴い、Nexus Arkの持続可能な運用が困難となった。
本プロジェクトは、特定のAIプロバイダ（Google）への依存を排除し、**Groq** をはじめとするOpenAI互換API、およびローカルLLM（Ollama等）に対応するための、アーキテクチャの根本的な刷新を目的とする。

## 2. アーキテクチャ改革の方針

### A. 抽象化レイヤー (`llm_factory.py`) の導入
現在は `gemini_api.py` が直接 Google SDK を叩いているが、これを廃止する。
代わりに、設定に基づいて適切な LangChain チャットモデル (`ChatGoogleGenerativeAI` や `ChatOpenAI`) を生成して返す「ファクトリー（工場）」を作成する。

**変更前:**
```python
# gemini_api.py
llm = ChatGoogleGenerativeAI(model="gemini-...", ...)
```

**変更後:**
```python
# llm_factory.py
def get_llm(provider, model_name, api_key, ...):
    if provider == "google":
        return ChatGoogleGenerativeAI(...)
    elif provider == "groq" or provider == "openai":
        return ChatOpenAI(base_url=..., api_key=..., ...)
```

### B. 設定ファイルの構造変更 (`config.json`)
プロバイダごとの設定を管理できる構造へ移行する。

```json
{
  "active_provider": "groq",
  "providers": {
    "google": {
      "api_key": "...",
      "default_model": "gemini-2.5-flash"
    },
    "groq": {
      "api_key": "...",
      "default_model": "llama-3.3-70b-versatile"
    },
    "openai": {
      "api_key": "...",
      "base_url": "https://api.openai.com/v1"
    }
  }
}
```

## 3. 開発フェーズ

### Phase 1: 基礎工事 (Foundation)
*   [ ] `config_manager.py`: マルチプロバイダ対応の設定読み書きロジックを追加。
*   [ ] `llm_factory.py`: プロバイダに応じたLLMインスタンス生成ロジックの実装。
*   [ ] `nexus_ark.py`: 設定タブに「AIプロバイダ選択」「Groq APIキー入力」UIを追加。

### Phase 2: エージェントの移植 (Migration)
*   [ ] `agent/graph.py`: `gemini_api` への依存を `llm_factory` に置き換え。
*   [ ] ツール呼び出し（Function Calling）の互換性確認。Google検索ツールなど、Gemini固有機能の代替策（DuckDuckGo）の標準化。

### Phase 3: 記憶とRAGの対応 (Memory & RAG)
*   [ ] `rag_manager.py`: Embeddingモデルの抽象化。
    *   当面はGeminiのEmbedding（無料枠）を使い続けるか、HuggingFace等のローカルEmbeddingへの切り替えを検討。
    *   **暫定措置:** 会話はGroq、EmbeddingはGeminiという「ハイブリッド構成」を許容する。

## 4. 推奨モデル構成 (Groq移行後)

| 用途 | 推奨モデル (Groq) | 理由 |
| :--- | :--- | :--- |
| **メイン会話** | `llama-3.3-70b-versatile` | Gemini Pro相当の知能と、圧倒的な推論速度。 |
| **高速処理** | `llama-3.1-8b-instant` | 情景描写や要約など、Flash Liteの代替。 |
| **思考特化** | `deepseek-r1-distill-llama-70b` | 論理的思考が必要なタスク用。 |

## 5. 開発のゴール
ユーザーが設定画面で「Google」「Groq」「OpenAI」を切り替えるだけで、バックエンドのAIが即座に切り替わり、会話やツール使用が問題なく継続できる状態を目指す。