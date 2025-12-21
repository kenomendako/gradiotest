# Changelog

All notable changes to Nexus Ark will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased] - 次回リリース予定

### Added - 新機能

#### 🤖 自律行動システム
- 自律行動モード（AIが自発的に行動・発言）
- 通知禁止時間帯（Quiet Hours）対応

#### 🌙 睡眠・記憶システム
- 睡眠・夢日記機能（Project Morpheus）
- 中期記憶（エピソード記憶）生成・注入機能
- 話題のクラスタリング機能
- 応答時記憶想起機能（RAG検索）

#### 🔀 マルチモデル対応
- OpenAI互換プロバイダへの対応
- グループ会話での各ペルソナ個別モデル設定

#### 📎 マルチモーダル強化
- 複数ファイル同時添付対応
- MP3音声ファイル認識

#### 🛡️ その他
- 設定ファイルの自動バックアップ＆自動復元機能
- 思考ログの形式を[THOUGHT]タグ方式に移行（後方互換あり）

### Fixed - バグ修正

#### UI / 表示
- 自律行動の重複発火バグ
- タイムスタンプ二重付記バグ（AIが日本語曜日形式でタイムスタンプ生成）
- AI応答の二重表示バグ
- LangGraphが生成する末尾の空AIMessageを除去
- `redaction_rules_state`の初期化時TypeError修正
- `handle_save_gemini_key`の戻り値数不足（オンボーディング時のValueError）
- 思考ログ内の文字置き換えでHTMLがエスケープされる問題
- 思考ログの折り返しが効かなくなる問題（CSS適用修正）

#### バックグラウンド処理
- アラーム・タイマーでAPI制限時もシステム通知を送信
- APIリトライ時にツール使用（アラーム・タイマー・ファイル編集等）の重複実行を防止
- 重複関数削除とタイマー・バックアップパス修正

### Known Issues - 既知の問題
- MP4動画: API制限のため送信失敗することがある

---

## [1.0.0] - 2025-10-19

*前回リリース*
