---
description: プロジェクトの開発ルール、ディレクトリ構成、UI開発の鉄則
---

# 開発ルールと規約 (Development Rules)

このファイルは、本プロジェクトの開発において遵守すべき厳格なルールを定義します。
AIエージェントは、作業開始前に必ずこのファイルを確認してください。

## 0. 基本原則 (Prime Directives)

1.  **使用言語 (Language)**:
    - 思考、計画、ユーザーへの応答、コミットメッセージなど、全てのコミュニケーションは **日本語** で行ってください。
    - 英語のドキュメントを作成する場合でも、補足や思考プロセスは日本語を使用してください。

2.  **ドキュメント第一 (Documentation First)**:
    - コーディングの前に、必ず関連するドキュメントを参照してください。
    - 特に **`docs/guides/gradio_notes.md`** は必読です。ここには、過去の失敗から得られた「Gradioの罠」と「解決策」が網羅されています。
    - UIを変更する場合は、まずこのドキュメントを確認し、既知の問題（イベント配線、ステート管理、CCS干渉など）を回避してください。

## 1. Git規約 (Git Conventions)

### ブランチ戦略
- **重要: `main` ブランチへの直接コミットは禁止です。**
- タスクごとに必ず新しいブランチを作成してください。
- **ブランチ名の命名規則:** `[prefix]/[task-name-kebab-case]`
    - `feat/`: 新機能
    - `fix/`: バグ修正
    - `improve/`: 改善、リファクタリング
    - `docs/`: ドキュメントのみの変更

### コミットメッセージ
- **言語:** 日本語
- **フォーマット:** `[prefix]: [変更内容の簡潔な説明]`
    - 例: `feat: ログイン画面のデザインを更新`
    - 例: `fix: メモリ検索の重複バグを修正`

## 2. ディレクトリ構成と重要な参照先

### 必読ドキュメント (Must-Read Docs)
- **Gradio開発の知見:** `docs/guides/gradio_notes.md`
    - **重要度: 最高**。UI開発におけるバイブルです。イベントハンドラの設計、状態管理、エラー処理のパターンが記載されています。
- **UI実装パターン:** `docs/guides/UI_IMPLEMENTATION_PATTERNS.md`
    - 標準的なUI構築パターン（ジェネレータ、中間保存など）が定義されています。
- **機能仕様書:** `docs/specifications/`
    - `SCENERY_SYSTEM_SPECIFICATION.md`: 情景画像の仕様（自動生成禁止、フォールバックロジック）
    - `MEMORY_SYSTEM_SPECIFICATION.md`: 記憶・RAGシステムの仕様

### 主要ディレクトリ
- **INBOX:** `docs/INBOX.md` (アイデア・バグ報告・未着手タスク)
- **タスクリスト:** `docs/plans/TASK_LIST.md` (優先順位付きバックログ)
- **レポート:** `docs/reports/YYYY-MM-DD_[TaskName].md` (完了報告書)
- **ガイド:** `docs/guides/` (仕様書、マニュアル)

## 3. UI開発の鉄則 (UI Development Philosophy)

`docs/guides/gradio_notes.md` に詳述されている原則の要約です。違反すると重大なバグにつながります。

1.  **責務の完全分離**:
    - `nexus_ark.py`: 「設計図」（レイアウトとイベント配線）のみ。ロジックを書かない。
    - `ui_handlers.py`: 「ロジック」（処理と戻り値）のみ。UI定義を書かない。
    - `config_manager.py`: 「設定」（テーマや定数）を一元管理。

2.  **イベントハンドラの契約**:
    - `inputs` の数と順序は、ハンドラ関数の引数と厳密に一致させる。
    - `outputs` の数と順序は、ハンドラ関数の戻り値（タプル）と厳密に一致させる。
    - これがずれると `ValueError` や `TypeError` でアプリがクラッシュします。

3.  **状態管理 (State Management)**:
    - グローバル変数に依存してはいけません。
    - 必ず `gr.State` を使用して、関数間でデータを安全に受け渡してください。
    - `gr.State` の初期化に `lambda` を使う際は、「関数オブジェクト」ではなく「結果」が渡されるように注意してください。

4.  **HTML/Markdown**:
    - `gr.Chatbot` は `render_markdown=False` で運用されています。
    - 複雑な表示が必要な場合は、Python側で完全なHTMLを生成してください。GradioにMarkdown解析を・させないでください。

## 4. 変更履歴 (CHANGELOG)

- **ファイル:** `CHANGELOG.md`
- タスク完了時に必ず更新してください。
- カテゴリ:
    - `Added` (追加)
    - `Fixed` (修正)
    - `Changed` (変更)
    - `Removed` (削除)
