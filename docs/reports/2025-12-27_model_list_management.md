# モデルリスト管理機能とドロップダウンバグ修正

**日付:** 2025-12-27  
**ブランチ:** `fix/openai-tool-history-bug`  
**ステータス:** ✅ 完了

---

## 問題の概要

OpenAI互換プロバイダ（OpenRouter/Groq/Ollama）のモデル管理機能が不足しており、また個別設定のモデルドロップダウンが起動時に開かないバグがあった。

---

## 修正内容

### 1. モデルリスト取得機能
- `config_manager.py` に `fetch_models_from_api()` を追加
- OpenAI互換エンドポイント `/v1/models` からモデルリストを取得

### 2. お気に入りトグル機能
- `config_manager.py` に `toggle_favorite_model()` を追加
- モデル名に `⭐` マークを付け外しできるように

### 3. プロバイダ切り替えバグ修正
- `handle_provider_change` がラジオボタンの内部ID（"google"/"openai"）を正しく処理するよう修正

### 4. ドロップダウン表示問題修正
- **根本原因**: `visible=False` グループ内のDropdownがGradioで正しくレンダリングされない
- **解決策**: `initial_load_outputs` に `room_openai_model_dropdown` を追加し、`handle_initial_load` で起動時に更新

---

## 変更したファイル

- `config_manager.py` - `fetch_models_from_api()`, `toggle_favorite_model()`, `add_model_to_list()` 追加
- `ui_handlers.py` - `handle_fetch_models()`, `handle_toggle_favorite()` 追加、`handle_provider_change()` バグ修正、`handle_initial_load()` にroom_openai_model_dropdown対応
- `nexus_ark.py` - 「📥 モデルリスト取得」「⭐ お気に入りに追加/削除」ボタン追加、イベント登録追加、`initial_load_outputs` 更新
- `docs/INBOX.md` - 完了タスクにチェック

---

## 検証結果

- [x] アプリ起動確認
- [x] モデルリスト取得機能動作確認
- [x] お気に入りトグル機能動作確認
- [x] プロバイダ切り替え動作確認
- [x] 個別設定のモデルドロップダウンが起動時に開くことを確認

---

## 残課題

- APIキー設定を「🔑 APIキー / Webhook管理」に集約する（INBOXに記録済み）
