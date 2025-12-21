---
description: 新しいタスクの開始手順
---

# 新規タスク開始ワークフロー

## 1. インボックス確認
`docs/INBOX.md` で未整理タスクを確認。

## 2. 指示書作成
Antigravityに依頼して `docs/guides/[TASK_NAME]_INSTRUCTIONS.md` を作成。

## 3. ブランチ作成
// turbo
```bash
git checkout -b [prefix]/[task-name]
```

## 4. 実装
指示書に従って実装。

## 5. レポート作成
完了後、`docs/reports/YYYY-MM-DD_[task_name].md` を作成。

## 6. マージ & プッシュ
```bash
git checkout main
git merge [ブランチ名]
git push
```
