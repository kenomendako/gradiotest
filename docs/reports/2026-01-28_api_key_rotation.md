# APIキーローテーション実装 (429エラー対策)

## 概要
Gemini APIの `ResourceExhausted` (429) エラーに対処するため、複数のAPIキーを自動的にローテーションする機能を実装しました。
`gemini_api.py` にてAPI呼び出しをラップし、エラー発生時に「トークン枯渇」としてマークし、次の利用可能なキーに切り替えてリトライします。
また、UI上に有効化/無効化の設定スイッチを追加しました。

## 変更内容

### 1. UI変更 (nexus_ark.py, ui_handlers.py)
- **共通設定**: 「APIキーローテーションを有効にする」チェックボックスを追加。
- **ルーム個別設定**: `room_rotation_dropdown` を追加し、共通設定に従うか、個別に強制有効/無効化するかを選択可能に。
- **イベントハンドラ**: 初期ロード時および設定保存時に、ローテーション設定が正しく読み書きされるよう配線。

### 2. ロジック変更 (gemini_api.py, config_manager.py)
- **リトライループ**: `invoke_nexus_agent_stream` 内にリトライループを実装。
- **エラー捕捉**: `google.api_core.exceptions.ResourceExhausted` を捕捉。
- **ローテーション**:
  - `config_manager.mark_key_as_exhausted(current_key)` を呼び出し。
  - `config_manager.get_next_available_gemini_key()` で次のキーを取得。
  - キーが尽きた場合はエラーを通知して停止。
- **設定値参照**: 実行時に `config_manager.get_effective_settings` から `enable_api_key_rotation` フラグを参照。

### 3. 設定管理 (config.json, room_config.json)
- `enable_api_key_rotation` (bool) を保存対象に追加。
- ルーム設定では `enable_api_key_rotation` (None/True/False) として保存。

## 検証結果

### 自動テスト
ユニットテスト `tests/test_api_key_rotation.py` を作成し、以下のケースを検証しました。
- `test_rotation_success`: 429エラー発生時に次のキーへ切り替えて成功すること。
- `test_rotation_failure_all_exhausted`: 全てのキーが枯渇した場合、適切なエラーで終了すること。
- `test_rotation_disabled`: 設定が無効の場合、ローテーションせずにエラーを返すこと。

テストは**PASS**しました。

### Wiring Validation
`tools/validate_wiring.py` を実行し、UI配線の整合性を確認しました。
`handle_initial_load` の出力数不一致（TypeErrorの原因）を修正し、現在は正常です。

```
[PASS] handle_initial_load: Output count matches signature default (172).
```

(注: `handle_room_change_for_all_tabs` など一部のレガシーな警告は残存していますが、今回の変更による新たな不整合はありません)

## 関連ドキュメント
- [Implementation Plan](../../.gemini/antigravity/brain/e7fc5384-d245-4efb-b4eb-41eb4beb6655/implementation_plan.md)
- [Walkthrough](../../.gemini/antigravity/brain/e7fc5384-d245-4efb-b4eb-41eb4beb6655/walkthrough.md)
