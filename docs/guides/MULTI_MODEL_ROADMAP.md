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
    *   **Groq:** 高速推論（Llama 3.3等）。
    *   **Ollama:** ローカル環境での完全無料運用。
    *   **OpenAI:** 本家GPT-4o等。

### B. 設定ファイルの構造 (`config.json`)
プロバイダごとの設定と、OpenAI互換エンドポイントの柔軟な設定を可能にする。

```json
{
  "active_provider": "google",
  "active_openai_profile": "OpenRouter",
  "openai_provider_settings": [
    {
      "name": "OpenRouter",
      "base_url": "https://openrouter.ai/api/v1",
      "api_key": "",
      "default_model": "google/gemma-2-9b-it:free",
      "available_models": [
        "google/gemma-2-9b-it:free",
        "meta-llama/llama-3-8b-instruct:free",
        "anthropic/claude-3.5-sonnet"
      ]
    },
    {
      "name": "Groq",
      "base_url": "https://api.groq.com/openai/v1",
      "api_key": "",
      "default_model": "llama-3.3-70b-versatile",
      "available_models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
    },
    {
      "name": "Local Ollama",
      "base_url": "http://localhost:11434/v1",
      "api_key": "ollama",
      "default_model": "phi3.5",
      "available_models": ["phi3.5", "gemma2:2b", "llama3.1:8b"]
    },
    {
      "name": "OpenAI Official",
      "base_url": "https://api.openai.com/v1",
      "api_key": "",
      "default_model": "gpt-4o",
      "available_models": ["gpt-4o", "gpt-4o-mini", "o1-preview"]
    }
  ]
}
```

---

## 3. 開発フェーズ

### Phase 1: 基礎工事 (Foundation) ✅ 完了
*   [x] `config_manager.py`: マルチプロバイダ対応の設定構造（`openai_provider_settings`）を導入。
*   [x] `llm_factory.py`: `ChatOpenAI` を利用した汎用接続ロジックの実装。
*   [x] `nexus_ark.py`: 設定タブに「プロバイダ切り替え」「OpenAI互換設定」UIを追加。

---

### Phase 1.5: モデル選択UIの強化 ✅ 完了 (2025-12-12)
*   [x] 設定構造の設計完了
*   [x] `config_manager.py`: 各プロバイダの `available_models` を最新モデルで更新
*   [x] `nexus_ark.py`: モデル選択を **Textbox → Dropdown** に変更
*   [x] `nexus_ark.py`: **カスタムモデル追加機能**（Textbox + Buttonで新規モデルを追加可能に）
*   [x] `ui_handlers.py`: `handle_add_custom_openai_model` 関数の追加
*   [x] ユーザー追加モデルの永続化（`config.json` への保存）

#### 更新済みプリセットモデルリスト

| プロバイダ | デフォルト | プリセットモデル |
|:---|:---|:---|
| **OpenRouter** | `google/gemma-2-9b-it:free` | 無料: `llama-3-8b-instruct:free`, `mistral-7b-instruct:free`, `deepseek-chat:free` / 有料: `claude-3.5-sonnet`, `gpt-4o` |
| **Groq** | `llama-3.3-70b-versatile` | `llama-3.3-70b-specdec`, `llama-3.1-70b-versatile`, `llama-3.1-8b-instant`, `mixtral-8x7b-32768` |
| **Ollama** | `phi3.5` | 軽量: `gemma2:2b`, `qwen2.5:0.5b` / 中量: `llama3.1:8b`, `mistral` / 大型: `llama3.1:70b`, `mixtral:8x7b` |
| **OpenAI** | `gpt-4o` | `gpt-4o-mini`, `gpt-4-turbo`, `gpt-4`, `o1-preview`, `o1-mini` |

---

### Phase 2: エージェントの移植 (Migration) ✅ 完了
*   [x] `agent/graph.py`: `llm_factory` 経由でのモデル取得に移行。
*   [x] **内部処理モデルの分離**: `force_google=True` パラメータにより、検索クエリ生成・情景描写等の内部処理は**Gemini固定**で実行。ユーザー選択の最終応答モデル（OpenAI等）とは独立して動作。
*   [x] `gemini_api.py`: `get_model_token_limits` がOpenAIモデル（gpt-、o1-等）を正しく処理するように修正。
*   [x] **ツール不使用モード**: `tool_use_enabled` 設定により、Function Calling非対応モデルでも会話が可能に。

#### 2025-12-13 修正: ツール不使用モード実装
OllamaやGPT-3.5等のFunction Calling非対応モデル使用時にエラーが発生していた問題を解決：
- プロバイダ設定に `tool_use_enabled` フラグを追加（Local Ollamaはデフォルトでfalse）
- `config_manager.is_tool_use_enabled()` で現在の設定を取得
- `agent_node` でフラグに応じてツールバインドをスキップ
- UIの「ツール使用（Function Calling）を有効にする」チェックボックスで切り替え可能

#### 2025-12-13 修正: 内部処理モデルとプロバイダ分離
OpenAIプロバイダ使用時に以下のエラーが発生していた問題を修正：
- `gemini-2.5-flash-lite does not exist` → 内部処理が誤ってOpenAI APIに送信されていた
- `Model is not found: models/gpt-X` → モデル情報取得がGemini API専用だった

**解決策**: `LLMFactory.create_chat_model()` に `force_google` パラメータを追加。内部処理（RAG検索、情景生成等）は常にGemini Native APIを使用し、最終応答のみユーザー選択のプロバイダを使用する設計に。

---

### Phase 3: 用途別モデル選択 (Role-Based Model Selection)
*   [ ] **最終応答モデル**: ユーザーへの返答に使用するメインモデル
*   [ ] **要約モデル**: 会話要約・コア記憶更新に使用
*   [ ] **内部処理モデル**: ツール判断・RAG検索クエリ生成に使用（**gemini-2.5-flash 固定推奨**）
*   [ ] **画像生成モデル**: 風景画像生成に使用

---

### Phase 4: ルームごとのAI設定 ✅ 完了 (2025-12-15)
*   [x] 各ルームで異なるプロバイダ/モデルを設定可能に
*   [x] `room_config.json` の `override_settings` にAI設定（provider, openai_settings）を追加
*   [x] ルーム個別のツール使用設定（tool_use_enabled）
*   [x] AI応答にタイムスタンプ + 使用モデル名を表示

#### 2025-12-15 実装: ルーム個別プロバイダ設定

**機能概要:**
- ルームごとに「共通設定に従う」「Google (Gemini)」「OpenAI互換」を選択可能
- 各ルームで異なるプロバイダ・モデル・ツール使用設定を持てる
- グループ会話で3つの異なるモデルが同時に会話可能に

**UI構成:**
- 個別設定タブに「AIプロバイダ設定」セクションを追加
- プロバイダラジオボタン: 「共通設定に従う」「Google (Gemini)」「OpenAI互換」
- Google設定: モデル選択Dropdown、APIキー選択、カスタムモデル追加
- OpenAI設定: プロファイル選択、Base URL、API Key、モデル選択、ツール使用チェックボックス

**技術的変更:**
- `get_active_provider(room_name)`: ルーム名を受け取りルーム個別設定を優先
- `is_tool_use_enabled(room_name)`: ルーム個別のtool_use_enabled設定を参照
- `LLMFactory.create_chat_model(room_name=...)`: ルーム個別のopenai_settingsを使用
- `get_effective_settings()`: provider, openai_settingsをeffective_settingsに含める

**対応ファイル:**
- `config_manager.py`: 設定取得関数にroom_name引数追加
- `llm_factory.py`: ルーム個別OpenAI設定優先ロジック追加
- `agent/graph.py`: LLMFactory呼び出しにroom_name渡し
- `gemini_api.py`: is_tool_use_enabled呼び出しにroom_name渡し
- `ui_handlers.py`: 設定の保存・読み込み対応、AI応答にモデル名表示
- `nexus_ark.py`: 個別設定UIの追加

---

### Phase 5: "Bring Your Own AI" (Local & RAG)
*   [ ] **Ollama対応強化:** モデル一覧の自動取得（`ollama list` コマンド連携）
*   [ ] **RAGの抽象化:** EmbeddingモデルもGemini依存から脱却し、HuggingFace（ローカル）やOpenAI互換Embeddingに対応させる。

---

## 4. 推奨モデル戦略

| ユーザー層 | 推奨プロバイダ | 特徴 |
| :--- | :--- | :--- |
| **ライトユーザー** | **OpenRouter (Free)** | 設定が簡単。`meta-llama/llama-3-8b-instruct:free` 等を利用。 |
| **ヘビーユーザー** | **OpenRouter (Paid)** | `anthropic/claude-3.5-sonnet` 等、従量課金で高品質な体験。 |
| **ゲーミングPC勢** | **Ollama** | `llama3.1:70b` 等をローカルで動かし、完全無料・無制限。 |
| **開発者(低スペ)** | **Ollama (Tiny)** | `phi3.5` や `gemma2:2b` で機能テストを行い、本番はOpenRouterで確認。 |

### Ollama スペック別推奨モデル

| PCスペック | VRAM目安 | 推奨モデル |
| :--- | :--- | :--- |
| **低スペック** | 4GB以下 | `phi3.5`, `gemma2:2b`, `qwen2.5:0.5b` |
| **中スペック** | 8GB程度 | `llama3.1:8b`, `gemma2:9b`, `mistral` |
| **高スペック** | 12GB以上 | `llama3.1:70b`, `mixtral:8x7b`, `qwen2.5:32b` |

---

## 5. 開発のゴール
「Geminiの無料枠が終わった？ 問題ない、OpenRouterの無料モデルに切り替えればいい」とユーザーが言える状態を目指す。