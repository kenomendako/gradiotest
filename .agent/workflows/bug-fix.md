---
description: バグ修正の標準ワークフロー
---

# バグ修正ワークフロー

## 1. ブランチ作成
```bash
git checkout -b fix/[問題の簡潔な説明]
```

## 2. 指示書を確認
`docs/guides/` にある指示書ファイルを確認。

## 3. 修正を実装
指示書に従ってコードを修正。

## 4. テスト
アプリを起動して動作確認。

## 5. コミット
```bash
git add .
git commit -m "fix: [修正内容の簡潔な説明]"
```

## 6. レポート作成
`docs/reports/YYYY-MM-DD_[問題名].md` にレポートを作成。

## 7. マージ
```bash
git checkout main
git merge fix/[ブランチ名]
git push
```

## 8. ブランチ削除（任意）
```bash
git branch -d fix/[ブランチ名]
```
