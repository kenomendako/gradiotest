# 情景画像 時間帯優先ロジック再修正

**完了日**: 2026-01-09  
**ブランチ**: `main` (直接コミット)
**関連レポート**: [2026-01-06_scenery_image_time_priority.md](2026-01-06_scenery_image_time_priority.md)

## 問題概要

2026-01-06の修正後、再度「昼間に夜の画像が表示される」問題が発生。

**報告内容**: ルシアンの書斎で12:40（昼）に `書斎_winter_midnight.png` が表示される。`書斎_summer_daytime.png` が存在するのになぜ？

## 原因分析

`find_scenery_image`関数のワイルドカード検索で、「季節のみ」パターン（`{location_id}_{season}_`）が**時間帯を無視してマッチ**していた。

### 問題のあったコード

```python
# 季節のみパターン
search_prefixes.append(f"{location_id}_{effective_season}_")
```

このコードが `書斎_winter_` というプレフィックスで検索し、`書斎_winter_midnight.png` がマッチしてしまっていた。

## 修正内容

### 変更ファイル
- `utils.py` の `find_scenery_image` 関数

### 修正点

1. **「季節のみ」パターンを削除**
   - ワイルドカード検索から `{location_id}_{effective_season}_` パターンを完全削除

2. **「場所のみ」パターンに時間帯除外フィルタを追加**
   - `{location_id}_` パターンでマッチする際、ファイル名に既知の時間帯名（`morning`, `night`, `midnight`等）が含まれる場合は除外
   - これにより `書斎_winter_midnight.png` のようなファイルが誤って選ばれることを防止

## 検証結果

| ケース | 修正前 | 修正後 |
|--------|--------|--------|
| `afternoon` + `winter` | ❌ `書斎_winter_midnight.png` | ✅ `None`（正しく除外） |
| `daytime` + `summer` | ✅ `書斎_summer_daytime.png` | ✅ `書斎_summer_daytime.png` |
