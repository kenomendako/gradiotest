# Phase I: UIドライブ表示の改善

**日付:** 2026-01-15  
**ステータス:** ✅ 完了

---

## 概要

Phase Fで廃止した「ユーザー感情モニタリング」を「ペルソナ感情モニタリング」に更新。グラフ表示も改善。

---

## 変更内容

### 1. グラフタイトル変更
- 「ユーザー感情の推移」→「ペルソナ感情の推移」

### 2. データソース変更
- `get_user_emotion_history()` → `get_persona_emotion_history()`
- `type: "persona"` のログのみ抽出

### 3. グラフ形式変更
- `LinePlot` → `ScatterPlot`（点間を結ばない）
- Y軸: 感情カテゴリ値 → 強度（intensity: 0.0〜1.0）

### 4. 奉仕欲テキスト変更
- 「ユーザー感情」表示を削除し、関係性維持への統合案内に

---

## 変更ファイル

- `nexus_ark.py` - ScatterPlot、タイトル変更
- `ui_handlers.py` - ペルソナ感情履歴取得、奉仕欲テキスト
- `motivation_manager.py` - `get_persona_emotion_history()` 追加

---

## 検証結果

- [x] 構文チェック成功
- [x] グラフ表示確認（ユーザーOK）
