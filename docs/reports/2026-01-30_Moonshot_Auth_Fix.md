# Moonshot AI (Kimi) 統合修正レポート

**日付:** 2026-01-30
**ブランチ:** `fix/moonshot-auth` (想定)
**ステータス:** ✅ 完了

---

## 問題の概要

Moonshot AI (Kimi) を使用する際に、以下の2つの重大なエラーが発生し、機能していなかった。
1.  **401 Unauthorized**: モデルリスト取得およびチャット実行時に認証エラーが発生。
2.  **400 Bad Request**: チャット実行時に `invalid temperature` エラーが発生。

---

## 修正内容

### 1. APIエンドポイントの修正 (401対策)
- **原因:** 公式ドキュメントに基づき `api.moonshot.cn` を使用していたが、実際には `api.moonshot.ai` が正しいエンドポイントであった（キーの種別による可能性あり）。
- **対応:** `config_manager.py` のデフォルト値を修正。また、既存ユーザーの `config.json` および `room_config.json` に残っていた古い `.cn` URL を修正するスクリプトを実行して一括置換した。

### 2. 動的APIキー注入の実装 (401対策・堅牢化)
- **原因:** ルーム設定 (`room_config.json`) に古いAPIキーや空の設定が残っていると、グローバル設定のキーが無視されるケースがあった。
- **対応:** `config_manager.get_effective_settings` および `ui_handlers.handle_fetch_models` にて、マネージドプロバイダ（Moonshot, Zhipu等）の場合は強制的にグローバル設定の有効なAPIキーを注入するロジックを追加した。

### 3. パラメータ強制オーバーライド (400対策)
- **原因:** Moonshot AI モデルは `temperature=1.0` 以外の値を許容しない厳格な制約があるが、アプリのデフォルト（0.7等）がそのまま送信されていた。
- **対応:** `LLMFactory` にて Moonshot AI プロバイダ使用時のみ、ユーザー設定に関わらず `temperature=1.0` に強制書き換えする処理を追加した。

### 4. UIイベントハンドラの修正
- **原因:** 「Moonshot AIキーを保存」ボタン押下時のイベントハンドラが未実装で、保存処理が走っていなかった。
- **対応:** `ui_handlers.handle_save_moonshot_key` を実装し、`nexus_ark.py` でボタンにバインドした（`outputs=None` として入力欄クリアを防止）。

---

## 変更したファイル

- `nexus_ark.py` - Moonshot保存ボタンのイベントバインド修正
- `ui_handlers.py` - `handle_save_moonshot_key` 実装、`handle_fetch_models` へのキー注入ロジック追加
- `config_manager.py` - `base_url` 初期値修正、`get_effective_settings` へのキー注入ロジック追加
- `llm_factory.py` - Moonshot AI 向けの `temperature=1.0` 強制ロジック追加

---

## 検証結果

- [x] **モデルリスト取得**: 「設定」タブで Moonshot AI のモデルリスト（`kimi-k2.5` 等）が正常に取得できることを確認。
- [x] **チャット動作**: ルームにて Moonshot AI を選択し、エラーなく応答が返ることを確認（パラメータエラー解消）。
- [x] **設定保存**: APIキーを入力して保存ボタンを押し、アプリ再起動後も正しくキーが維持されることを確認。
- [x] **個別/共通設定**: 共通設定だけでなく、個別ルーム設定（過去に作成したルーム）でも正しく動作することを確認（スクリプトによる修正済み）。

---

## 残課題（あれば）

なし
