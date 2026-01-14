---
name: coding-style
description: 言語使用（日本語強制）、Git規約、UI開発ルール（Gradio）、コーディングの基本原則を適用します。コードを書く前やPR作成時に必ず参照してください。
---

# Coding Style & Development Rules

Nexus Arkプロジェクトにおける開発ルールです。

## 1. 使用言語 (Language) - 鉄の掟
*   **すべて日本語**: ユーザーへの応答、思考プロセス(Thought)、タスク定義、コミットメッセージは全て日本語で記述してください。
*   **英語禁止**: ツール定義やシステムプロンプトが英語でも、出力は日本語で行ってください。

## 2. UI開発の鉄則 (UI Development Philosophy)
Gradio UIを変更する際は、以下の原則を厳守してください。

1.  **責務の完全分離**:
    *   `nexus_ark.py`: レイアウトとイベント配線のみ。ロジック禁止。
    *   `ui_handlers.py`: ロジックのみ。UI定義禁止。
    *   `config_manager.py`: 設定と定数。
2.  **イベントハンドラ**: `_ensure_output_count` を使用して戻り値の数を保証してください。
3.  **状態管理**: `gr.State` を使用し、グローバル変数への依存を避けてください。
4.  **検証**: UI変更後は必ず `python tools/validate_wiring.py` を実行してください。

## 3. Git規約 (Git Conventions)
*   **ブランチ戦略**: `[prefix]/[task-name]` (例: `feat/add-memory-search`)
*   **コミットメッセージ**: `[prefix]: [説明]` (例: `fix: ログ保存のバグを修正`)
    *   `feat`: 新機能
    *   `fix`: バグ修正
    *   `improve`: 改善
    *   `docs`: ドキュメント

## 4. 基本動作
*   **ドキュメント第一**: コーディング前に `docs/guides/gradio_notes.md` を確認してください。
*   **対話と確認**: 勝手に実装を進めず、`notify_user` で方針を確認してください。
