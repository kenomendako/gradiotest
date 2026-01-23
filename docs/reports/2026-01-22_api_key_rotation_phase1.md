# APIキーローテーション機能 (Phase 1)

**日付:** 2026-01-22  
**ブランチ:** `feat/api-key-rotation`  
**ステータス:** ✅ 完了

---

## 問題の概要

Gemini APIの無料枠縮小に対応するため、複数のAPIキーをローテーションして使用する機能を実装。無料キーを優先し、上限到達時に別のキーへ自動切替、最終手段として有料キーを使用する仕組みを構築。

---

## 修正内容

### 1. コア機能 (config_manager.py)

5つの新規関数を追加:

| 関数名 | 機能 |
|--------|------|
| `get_next_available_gemini_key()` | 無料キー優先でローテーション取得 |
| `mark_key_as_exhausted()` | キーを一時停止（翌日0時自動解除） |
| `clear_exhausted_keys()` | 期限切れのexhausted状態をクリア |
| `get_current_key_status()` | UI表示用ステータス取得 |
| `toggle_key_paid_status()` | 有料/無料をトグル |

### 2. ヘルパー関数 (llm_factory.py)

| 関数名 | 機能 |
|--------|------|
| `get_api_key_with_rotation()` | ローテーション対応のキー取得 |
| `report_key_exhausted()` | レート制限報告と次キー取得 |

### 3. UI拡張 (nexus_ark.py / ui_handlers.py)

- APIキー管理セクションにステータス表示エリアを追加
- 各キーの状態をアイコンで視覚化（✅利用可能 / ⏸️上限到達、🆓無料 / 💰有料）
- 「ステータスを更新」ボタンでリアルタイム確認可能

---

## 変更したファイル

- `config_manager.py` - 5つのローテーション関数追加、delete時のexhausted_keysクリア対応
- `llm_factory.py` - 2つのヘルパー関数追加
- `nexus_ark.py` - ステータス表示UI追加、ワイヤリング追加
- `ui_handlers.py` - `handle_refresh_key_status` ハンドラ追加
- `tests/test_api_key_rotation.py` - ユニットテスト追加（新規）

---

## 検証結果

- [x] config_manager関数のユニットテスト（4項目PASS）
- [x] ステータス表示関数の動作確認
- [x] コードのシンタックスチェック

---

## 残課題

- **Phase 1.5**: `agent/graph.py`でのレート制限エラー時の自動キー切り替え統合
  - 影響範囲が広いため、別途実装を推奨
