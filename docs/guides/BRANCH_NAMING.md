# ブランチ命名規則

## プレフィックス

| プレフィックス | 用途 | 例 |
|---------------|------|-----|
| `fix/` | バグ修正 | `fix/autonomous-action-duplicate` |
| `feat/` | 新機能追加 | `feat/mp4-video-support` |
| `refactor/` | リファクタリング | `refactor/clean-up-handlers` |
| `docs/` | ドキュメントのみ | `docs/update-readme` |
| `test/` | テスト追加・修正 | `test/add-unit-tests` |

## ルール

1. **小文字とハイフン**を使う（アンダースコアは使わない）
2. **簡潔で説明的**な名前にする
3. **日本語は避ける**（GitHubでの表示問題を防ぐ）

## マージ後

- ブランチは削除してOK
- `main` ブランチが常に最新の安定版
