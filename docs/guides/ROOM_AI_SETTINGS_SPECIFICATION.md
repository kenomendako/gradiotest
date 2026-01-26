# ルーム個別AIプロバイダ設定 仕様書

**実装日:** 2025-12-15  
**関連ドキュメント:** [MULTI_MODEL_ROADMAP.md](./MULTI_MODEL_ROADMAP.md)

---

## 1. 概要

Nexus Arkでは、各ルーム（AIペルソナ）ごとに異なるAIプロバイダとモデルを設定できます。これにより、グループ会話で複数の異なるAIモデルが同時に会話することが可能になります。

### 主な機能

| 機能 | 説明 |
|-----|------|
| **プロバイダ選択** | 「共通設定に従う」「Google (Gemini)」「OpenAI互換」から選択 |
| **モデル選択** | プロバイダごとのモデルリストから選択、カスタムモデル追加も可能 |
| **ツール使用設定** | OpenAI互換プロバイダでFunction Callingの有効/無効を設定 |
| **設定の永続化** | 設定は `room_config.json` に保存され、再起動後も保持 |

---

## 2. UI構成

### 個別設定タブ → AIプロバイダ設定

```
┌─────────────────────────────────────────────────────┐
│ AIプロバイダ                                         │
│ ○ 共通設定に従う  ○ Google (Gemini)  ○ OpenAI互換  │
├─────────────────────────────────────────────────────┤
│ [Google設定]                                         │
│   モデル: [Dropdown] ▼                               │
│   APIキー: [Dropdown] ▼                              │
│   + カスタムモデル追加                                │
├─────────────────────────────────────────────────────┤
│ [OpenAI互換設定]                                     │
│   プロファイル: [Dropdown] ▼                         │
│   Base URL: [Textbox]                               │
│   API Key: [Textbox]                                │
│   モデル: [Dropdown] ▼                               │
│   ☑ ツール使用（Function Calling）を有効にする       │
│   + カスタムモデル追加                                │
└─────────────────────────────────────────────────────┘
```

---

## 3. 設定ファイル構造

### room_config.json

```json
{
  "override_settings": {
    "provider": "openai",
    "openai_settings": {
      "profile": "Groq",
      "base_url": "https://api.groq.com/openai/v1",
      "api_key": "gsk_...",
      "model": "llama-3.3-70b-versatile",
      "tool_use_enabled": false
    }
  }
}
```

### provider の値

| 値 | 意味 |
|---|------|
| `null` または未設定 | 共通設定に従う |
| `"default"` | 共通設定に従う（明示的） |
| `"google"` | Google (Gemini) を使用 |
| `"openai"` | OpenAI互換を使用 |

---

## 4. 処理フロー

### プロバイダ決定の優先順位

```
1. ルーム個別設定 (room_config.json → override_settings.provider)
   ↓ 未設定の場合
2. 共通設定 (config.json → active_provider)
```

### モデル決定の優先順位

**Google (Gemini) の場合:**
```
1. ルーム個別の model_name
   ↓ 未設定の場合
2. UI選択のグローバルモデル
   ↓ 未設定の場合
3. DEFAULT_MODEL_GLOBAL
```

**OpenAI互換の場合:**
```
1. ルーム個別の openai_settings.model
   ↓ 未設定の場合
2. グローバルなアクティブプロファイルの default_model
```

---

## 5. 関連関数

### config_manager.py

| 関数 | 説明 |
|------|------|
| `get_active_provider(room_name)` | ルーム個別のプロバイダ設定を優先して返す |
| `is_tool_use_enabled(room_name)` | ルーム個別のtool_use_enabled設定を返す |
| `get_effective_settings(room_name)` | 全設定を統合して返す（provider, openai_settings含む） |

### llm_factory.py

| 関数 | 説明 |
|------|------|
| `create_chat_model(room_name=...)` | ルーム個別のOpenAI設定を優先してLLMを生成 |

---

## 6. 注意事項

### ツール使用の制限

一部のモデル（Ollama、一部のGroqモデル等）はFunction Calling非対応です。
これらのモデルを使用する場合は、「ツール使用」をOFFにしてください。

ツールエラーが発生した場合、チャット欄にエラーメッセージが表示されます：
```
⚠️ モデル非対応エラー: 選択されたモデル `llama-3.3-70b-versatile` は
ツール呼び出し（Function Calling）に対応していません。

【解決方法】
1. 設定タブ→プロバイダ設定で「ツール使用」をOFFにする
2. または、Function Calling対応モデルに変更する
3. または、Geminiプロバイダに切り替える
```

### 内部処理モデル

検索クエリ生成、情景描写等の内部処理は、ルーム設定に関係なく **Gemini (gemini-2.5-flash)** を使用します。これは `force_google=True` パラメータにより強制されます。

### AI応答のモデル表示

AI応答のタイムスタンプには使用モデル名が付記されます：
```
2025-12-15 (Sun) 14:17:37 | gemini-2.5-flash
```

---

## 7. グループ会話での動作

グループ会話では、各参加者のルーム設定に従って異なるモデルが使用されます。

**例:**
| ルーム | プロバイダ | モデル |
|--------|-----------|--------|
| 音声機能テスト | Groq | llama-3.3-70b-versatile |
| 思考ログテスト | Google | gemini-2.5-flash |
| テスト | OpenAI | gpt-5-mini-2025-08-07 |

これにより、異なる性格や能力を持つAIペルソナを使い分けることができます。
