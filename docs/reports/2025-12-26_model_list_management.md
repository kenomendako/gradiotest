# モデルリスト精査・管理機能強化

**日付:** 2025-12-26  
**ブランチ:** `improve/model-list-management`  
**ステータス:** ✅ 完了

---

## 問題の概要

モデル選択リストに不要なモデルが蓄積しても削除する手段がなく、ユーザー体験が悪化していた。また、デフォルトモデルリストも古いモデルを含んでいた。

---

## 修正内容

### 1. デフォルトモデルリストの精査・更新

各プロバイダのデフォルトモデルを2025年12月時点で推奨できるものに更新:

| プロバイダ | モデル数 | 主なモデル |
|-----------|---------|-----------|
| Gemini | 5 | gemini-2.5-flash, gemini-2.5-pro, gemini-2.5-flash-lite, gemini-3-flash-preview, gemini-3-pro-preview |
| OpenAI Official | 2 | gpt-5.2-2025-12-11, chatgpt-4o-latest |
| OpenRouter | 3 | deepseek-v3.1:free (16.4万トークン), llama-3.3-70b:free, gemma-3-27b-it:free |
| Groq | 3 | llama-3.3-70b-versatile, llama3-groq-70b-8192-tool-use-preview (ツール特化), llama-3.1-8b-instant |
| Ollama | 4 | phi3.5 (VRAM 2.5GB), qwen2.5:3b, gemma2:2b, qwen2.5:0.5b |

### 2. モデル管理UI機能追加

全4箇所に「削除」「デフォルトに戻す」ボタンを追加:
- 共通設定 → Google (Gemini)
- 共通設定 → OpenAI互換
- 個別設定 → Google (Gemini)
- 個別設定 → OpenAI互換

---

## 変更したファイル

- `config_manager.py`
  - デフォルトモデルリスト更新
  - `_get_default_config()`: OpenAI互換プロファイルのデフォルト取得
  - `get_default_available_models()`: Geminiデフォルトモデルリスト取得
  - `remove_model_from_list()`: モデル削除
  - `reset_models_to_default()`: Geminiモデルリストリセット

- `ui_handlers.py`
  - `handle_delete_gemini_model()`: Geminiモデル削除ハンドラー
  - `handle_reset_gemini_models_to_default()`: Geminiリセットハンドラー
  - `handle_delete_openai_model()`: OpenAI互換モデル削除ハンドラー
  - `handle_reset_openai_models_to_default()`: OpenAI互換リセットハンドラー

- `nexus_ark.py`
  - 4箇所にUI（削除・リセットボタン）追加
  - 対応するイベントハンドラー登録

---

## 検証結果

- [x] アプリ起動確認
- [x] 削除ボタン動作確認
- [x] デフォルトに戻すボタン動作確認
- [x] モジュールインポートテスト成功

---

## 残課題

- 各モデルでの実際の会話動作テストは未実施（別タスクで対応可能）
