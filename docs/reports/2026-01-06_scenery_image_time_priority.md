# 情景画像表示ロジック見直し

**完了日**: 2026-01-06  
**ブランチ**: `improve/scenery-image-time-priority`

## 問題概要
1. 画像検索で「冬の昼」がない場合に「冬の夜」が表示される（季節優先になっていた）
2. `get_time_of_day`の詳細名（`late_morning`等）と画像ファイル名の簡略名（`morning`等）が不一致
3. 昼間に夜の画像が表示される違和感

## 修正内容

### 変更ファイル
- `utils.py` の `find_scenery_image` 関数 (v3 → v6)

### 新機能

#### 1. 季節フォールバック
同じ時間帯で季節を遡る: 冬 → 秋 → 夏 → 春

#### 2. 明るさベースの時間帯フォールバック
昼間時間帯は最終的に`morning`までフォールバック:
```
afternoon → noon → late_morning → morning
```

夜間時間帯は`night`にフォールバック:
```
evening → night
midnight → night
```

## 検証結果
| ケース | 結果 |
|--------|------|
| `late_morning` + `winter` | ✅ `キッチン_autumn_morning.png` |
| `afternoon` + `winter` | ✅ `キッチン_autumn_morning.png` |

## 効果
少ない画像枚数でも違和感のない表示を実現。画像生成コストの削減に貢献。
