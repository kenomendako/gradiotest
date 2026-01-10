---
description: 完了レポートを作成し、変更をコミットしてマージ準備を行う
---

# タスク報告ワークフロー

検証終了後、タスクを完了させるためのワークフローです。

1. **レポート作成**
   - 新しいファイル `docs/reports/YYYY-MM-DD_[TaskName].md` を作成します。
   - `docs/templates/report_template.md` のテンプレートを使用します（見つからない場合は標準的なフォーマットを使用）。
   - 内容: 概要、変更点、検証結果。
   - **UI変更がある場合:** `python tools/validate_wiring.py` を実行し、結果を報告に含めてください。


2. **変更のコミット**
   - Gitコマンドを実行して変更をコミットします。
   - `git add .`
   - `git commit -m "[prefix]: [message]"`

3. **変更履歴 (CHANGELOG) の更新**
   - `CHANGELOG.md` にエントリを追加します。

4. **タスクリストの更新**
   - `docs/plans/TASK_LIST.md` 内のタスクを `[x]` にマークします。
   - レポートファイルへのリンクを追記します。

5. **最終レビュー**
   - `notify_user` を呼び出し、レポートを提示して、マージ（または完了）の許可を求めます。

