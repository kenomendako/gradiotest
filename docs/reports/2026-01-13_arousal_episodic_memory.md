# Arousalベース エピソード記憶 Phase 1 実装レポート

**完了日**: 2026-01-13  
**ブランチ**: `feat/arousal-episodic-memory`

---

## 概要

会話の「感情的重要度（Arousal）」をリアルタイムで計算・記録する機能を実装しました。
Arousalは内部状態の変化から算出され、将来的にエピソード記憶の取捨選択に活用されます。

---

## 変更点

### 新規ファイル

| ファイル | 説明 |
|---------|------|
| `arousal_calculator.py` | Arousal計算ロジック（0.0〜1.0スコア化） |

### 変更ファイル

| ファイル | 変更内容 |
|---------|---------|
| `motivation_manager.py` | `get_state_snapshot()` メソッド追加 |
| `summary_manager.py` | `save_today_summary()` に arousal 引数追加 |
| `ui_handlers.py` | 会話開始/終了時のArousal計算・ログ出力 |

---

## Arousal計算式

```
Arousal = (好奇心変化 × 0.30) + (感情変化 × 0.40) + (奉仕欲変化 × 0.30)
```

### レベル区分

| スコア | レベル |
|-------|-------|
| 0.00〜0.25 | low |
| 0.25〜0.50 | medium |
| 0.50〜0.75 | high |
| 0.75〜1.00 | very_high |

---

## 検証結果

```
✅ 構文チェック通過
✅ アプリ正常起動
✅ Arousal計算確認:
   - スコア: 0.750 (very_high)
   - 奉仕欲変化: +0.600
   - 感情変化: happy → anxious
```

---

## 今後の展開（Phase 2以降）

- Arousalをtoday_summary.jsonに永続保存
- エピソード記憶圧縮時にArousal重み付け
- 検索ランキングへのArousal適用
