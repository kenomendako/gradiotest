# ローカルLLM対応 & フォールバック機構 (Phase 3c & 4)

**日付:** 2026-01-24  
**ブランチ:** `feat/local-llm-fallback`  
**ステータス:** ✅ 完了

---

## 問題の概要

マルチモデルアーキテクチャ計画の最終フェーズとして、ローカルLLM対応（Phase 3c）とフォールバック機構（Phase 4）を実装。

---

## 修正内容

### Phase 3c: ローカルLLM対応 (llama-cpp-python)

- **llama-cpp-python** を使用したGGUFモデルのローカル実行をサポート
- Ollama を廃止し、llama-cpp-python に統一（配布の容易性のため）
- 共通設定 → 「🔑 APIキー / Webhook管理」→「ローカルLLM (llama.cpp)」でパス設定

### Phase 4: フォールバック機構

- プライマリプロバイダ（Zhipu, Groq, ローカル等）でエラー発生時、**Googleへ自動フォールバック**
- フォールバック有効/無効をチェックボックスで切替可能
- `create_chat_model_with_fallback()` ラッパー関数を追加

---

## 変更したファイル

- `config_manager.py` - LOCAL_MODEL_PATH 変数追加、fallback設定追加
- `llm_factory.py` - local プロバイダ分岐追加、フォールバックラッパー追加
- `nexus_ark.py` - ローカルモデルパス入力UI、フォールバックチェックボックス追加
- `ui_handlers.py` - handle_save_local_model_path追加、ハンドラ更新
- `requirements.txt` - llama-cpp-python 追加
- `docs/plans/multi_model_architecture_plan.md` - ステータス更新

---

## 検証結果

- [x] シンタックスチェック通過（全変更ファイル）
- [x] コミット完了（2件）
- [ ] 手動テスト（ユーザーによる動作確認待ち）

---

## 残課題

- **OpenRouter等のAPIキー設定を共通設定に集約** → 別タスクとして対応予定
- **コスト最適化ダッシュボード** → 将来検討
