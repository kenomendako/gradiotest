# Groq内部処理モデル対応 (Phase 3b)

**日付:** 2026-01-24  
**ブランチ:** `feat/groq-internal-model`  
**ステータス:** ✅ 完了

---

## 問題の概要

マルチモデルアーキテクチャ計画の Phase 3b として、Groq を内部処理モデルのプロバイダとして追加する。

---

## 修正内容

### 1. Groq プロバイダ統合
- `config_manager.py`: `GROQ_API_KEY` グローバル変数追加、`load_config()` で読み込み
- `llm_factory.py`: `internal_role="groq"` の分岐追加（ChatOpenAI使用）
- `nexus_ark.py`: APIキー入力UI、内部プロバイダ選択肢に Groq 追加
- `ui_handlers.py`: `handle_save_groq_key` 関数追加、初期ロード対応

### 2. UI改善（ユーザーフィードバック対応）
- Groq APIキー説明のリンクをプレーンテキストに変更（テーマ依存の色問題回避）
- ルーム個別設定の Base URL / API Key 入力を非表示（共通設定で一元管理）

---

## 変更したファイル

- `config_manager.py` - GROQ_API_KEY 変数追加、load_config 更新
- `llm_factory.py` - groq プロバイダ分岐追加
- `nexus_ark.py` - Groq UI追加、ルーム設定のAPI入力非表示
- `ui_handlers.py` - handle_save_groq_key 追加、initial_load 更新

---

## 検証結果

- [x] シンタックスチェック通過（全4ファイル）
- [x] コミット完了（2件）
- [ ] 手動テスト（ユーザーによる動作確認待ち）

---

## 残課題

- ルーム個別設定でのGLM（Zhipu AI）対応 → マルチモデル計画完了後に検討
- Phase 3c（ローカルLLM対応）/ Phase 4（フォールバック機構）
