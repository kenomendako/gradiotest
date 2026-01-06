# 情景画像表示ロジック見直し

**完了日**: 2026-01-06  
**ブランチ**: `improve/scenery-image-time-priority`

## 問題概要
1. 情景画像のフォールバック検索で、「冬の昼」の画像がない場合に「冬の夜」が表示されてしまう
2. `get_time_of_day`が返す詳細な時間帯名（`late_morning`等）と画像ファイル名の簡略名（`morning`等）が不一致

## 修正内容

### 変更ファイル
- [utils.py](file:///c:/Users/baken/OneDrive/デスクトップ/gradio_github/gradiotest/utils.py) の `find_scenery_image` 関数 (v3 → v5)

### 変更後の検索優先順位
1. `場所_現在季節_時間帯.png` (完全一致)
2. `場所_現在季節_時間帯(簡略).png` (時間帯フォールバック)
3. `場所_[他の季節]_時間帯.png` (季節フォールバック)
4. `場所_時間帯.png` (時間帯のみ)
5. `場所_季節.png` (季節のみ)
6. `場所.png` (デフォルト)

### 季節フォールバック順序
現在季節から逆順に遡る: 冬 → 秋 → 夏 → 春

### 時間帯フォールバックマッピング
- `late_morning` → `morning`
- `early_morning` → `morning`
- `afternoon` → `noon`
- `evening` → `night`
- `midnight` → `night`

## 検証結果
- 構文チェック: ✅ 成功
- インポートテスト: ✅ 成功
- 動作テスト: ✅ 成功（`キッチン_autumn_morning.png`が正しく選択された）
- 構文チェック: ✅ 成功
- インポートテスト: ✅ 成功

## 今後の関連課題
INBOX項目「情景描写画像の切り替えチェック」もこの修正で解決される可能性あり。
