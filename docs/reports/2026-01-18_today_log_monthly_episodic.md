# 本日分ログフィルタの月別エピソード記憶対応

**日付:** 2026-01-18  
**ブランチ:** `fix/today-log-monthly-episodic`  
**ステータス:** ✅ 完了

---

## 問題の概要

送信過去ログを「本日分」に設定しても、チャット欄に昨日（2026-01-17）のログが表示される問題が発生。

**原因:** `_get_effective_today_cutoff`関数が旧形式の`episodic_memory.json`を参照していたが、2026-01-17の階層的圧縮アップデートで新形式`memory/episodic/YYYY-MM.json`に移行済みだった。メインファイルが存在しないため「昨日のエピソード記憶なし」と判定され、cutoff_dateが昨日に設定されていた。

---

## 修正内容

### [gemini_api.py](file:///home/baken/nexus_ark/gemini_api.py)

`_get_effective_today_cutoff`関数を修正:

1. まず新形式 `memory/episodic/YYYY-MM.json` から昨日のエピソードを検索
2. 見つからなければ後方互換のため旧形式 `episodic_memory.json` にフォールバック
3. 重複ロジックを`check_episodes_for_date`ヘルパー関数に抽出

---

## 検証結果

- [x] 構文チェック（OK）
- [x] アプリ起動確認（ユーザー確認済み）
- [x] 「本日分」設定でチャット欄が2026-01-18以降のログのみ表示

---

## 残課題

なし
