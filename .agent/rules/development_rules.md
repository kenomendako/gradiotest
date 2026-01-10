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

## 2. 重要なドキュメントと参照先

以下のドキュメントはシステムの「正本」として機能します。

### 必読ガイド (Must-Read Guides)
- **Gradio開発の知見 (最重要):** `docs/guides/gradio_notes.md`
    - UI開発のバイブル。イベントハンドラ、CSS、状態管理のトラブルシューティング集。
- **UI実装パターン (UI仕様書):** `docs/guides/UI_IMPLEMENTATION_PATTERNS.md`
    - ジェネレータパターン、中間保存、エラーハンドリングなどの標準実装パターン。
- **機能仕様書:** `docs/specifications/`
    - `SCENERY_SYSTEM_SPECIFICATION.md`: 情景画像仕様
    - `MEMORY_SYSTEM_SPECIFICATION.md`: 記憶・RAGシステム仕様

### ディレクトリ構成
- **INBOX:** `docs/INBOX.md` (アイデア・バグ報告)
- **タスクリスト:** `docs/plans/TASK_LIST.md` (優先順位付きバックログ)
- **レポート:** `docs/reports/YYYY-MM-DD_[TaskName].md` (完了報告書)
- **設計判断:** `docs/decisions/NNN_[Title].md` (アーキテクチャ決定の記録)
- **教訓・知見:** `docs/journals/[Category]_LESSONS.md` (開発で得た知見)

## 3. ドキュメンテーション運用ルール

### 完了レポート (`/task-report`)
タスク完了時には必ずレポートを作成してください。含めるべき内容:
- 問題の概要と背景
- 具体的な修正内容（変更したファイルとロジック）
- 検証結果（テストした項目と結果）
- 残課題（あれば）

### 設計判断記録 (`docs/decisions/`)
以下の場合、新しい判断記録（ADR）を作成してください:
- 複数の技術的選択肢から一つを選んだ場合
- 重大な技術的制約により機能を断念した場合
- 将来の開発方針に影響する決定をした場合

## 4. UI開発の鉄則 (UI Development Philosophy)

`docs/guides/gradio_notes.md` に詳述されている原則の要約です。違反すると重大なバグにつながります。

1.  **責務の完全分離**:
    - `nexus_ark.py`: 「設計図」（レイアウトとイベント配線）のみ。ロジックを書かない。
    - `ui_handlers.py`: 「ロジック」（処理と戻り値）のみ。UI定義を書かない。
    - `config_manager.py`: 「設定」（テーマや定数）を一元管理。

2.  **イベントハンドラの契約 (The Safety Contract)**:
    - **司令塔パターン**: 広範囲の更新には必ず単一の司令塔関数を使用してください。
    - **出力数ガード**: `_ensure_output_count` を使用して、戻り値の不整合によるクラッシュを未然に防いでください。
    - 詳細は `docs/guides/UI_IMPLEMENTATION_PATTERNS.md` の **"安全装置アーキテクチャ"** セクションを参照してください。

3.  **状態管理 (State Management)**:
    - グローバル変数に依存してはいけません。
    - 必ず `gr.State` を使用して、関数間でデータを安全に受け渡してください。
    - グローバル変数は「読み取り専用」の定数以外原則禁止です。

4.  **配線チェック (Wiring Validation)**:
    - UI変更後は必ず `python tools/validate_wiring.py` を実行してください。
    - 戻り値の数や `expected_count` の不整合をコミット前に検出できます。

5.  **HTML/Markdown**:
    - `gr.Chatbot` は `render_markdown=False` で運用されています。
    - 複雑な表示が必要な場合は、Python側で完全なHTMLを生成してください。GradioにMarkdown解析を・させないでください。

## 5. 変更履歴 (CHANGELOG)

- **ファイル:** `CHANGELOG.md`
- タスク完了時に必ず更新してください。
- カテゴリ: `Added`, `Fixed`, `Changed`, `Removed`
