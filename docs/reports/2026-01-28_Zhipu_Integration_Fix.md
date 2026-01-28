# Task Report: Zhipu AI Integration & Dynamic Fetching

## 概要
Zhipu AI (GLM-4) を会話モデルとして統合し、APIから動的にモデルリストを取得する機能を実装しました。
また、検証中に発見された複数の重大な不具合（プロバイダ設定の無視、モデル名の不整合）を修正しました。

## 実施した変更
1.  **バックエンド (`config_manager.py`, `ui_handlers.py`)**:
    -   `save_zhipu_models`: 取得したモデルリストを保存するロジックを実装。
    -   `handle_fetch_zhipu_models`: APIからモデルリストを取得し、ドキュメントに反映するハンドラを実装。
    -   **Bug Fix**: `get_active_provider` と `set_active_provider` を修正し、"zhipu" プロバイダが正しく認識されるようにしました。
    -   **Bug Fix**: `get_effective_settings` を修正し、Zhipu選択時に正しいモデル名（`zhipu_model`）が使用されるようにしました（Error 1211解消）。

2.  **UI (`nexus_ark.py`)**:
    -   グローバル設定およびルーム設定に「モデル一覧を取得」ボタンを追加。
    -   各ボタンとハンドラのWiringを実施。

3.  **定数 (`constants.py`)**:
    -   デフォルトのZhipuモデルリストから廃止された `glm-4` を削除し、`glm-4-plus` をデフォルトに変更しました。

## 検証結果
-   [x] **UI表示**: 設定画面にボタンが表示され、Zhipu AIが選択可能であることを確認。
-   [x] **モデル取得**: ボタン押下によりAPIからモデルリストが取得・更新されることを確認。
-   [x] **発話テスト**:
    -   初期: Error 1211 (Model does not exist) -> 修正済み。
    -   最終: Error 429 (Balance insufficient) -> モデル名自体は正しくAPIに送信され、課金エラーが返ることを確認（＝統合成功）。

## 今後の課題
-   APIキーの残高確保（ユーザー責務）。
-   他のプロバイダ（OpenRouter等）の動的取得対応（必要に応じて）。
