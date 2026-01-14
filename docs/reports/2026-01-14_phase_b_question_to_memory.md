# Phase B: 解決済み質問→記憶変換

**日付:** 2026-01-14  
**ブランチ:** `feat/phase-b-question-to-memory`  
**ステータス:** ✅ 完了

---

## 問題の概要

睡眠時の記憶整理で、解決済みの問いを単に削除していたため、AIが得た学びが永続化されていなかった。

---

## 修正内容

- 解決済みの問いをLLMで分析し、FACT（事実）はエンティティ記憶に、INSIGHT（洞察）は夢日記に自動変換する機能を実装
- 変換済みフラグにより再処理を防止

---

## 変更したファイル

- `motivation_manager.py` - `get_resolved_questions_for_conversion()`, `mark_question_converted()` 追加
- `dreaming_manager.py` - `_convert_resolved_questions_to_memory()` 追加、`dream()` から呼び出し
- `docs/specifications/MEMORY_SYSTEM_SPECIFICATION.md` - Phase B仕様を追加

---

## 検証結果

- [x] 構文チェック OK
- [x] アプリ起動確認 OK  
- [x] 手動での睡眠時整理を実行
  - 解決済み質問1件を正しく検出
  - 回答詳細がないためSKIPと判定（設計通り）
  - 変換済みマークが正常に付与

---

## 残課題

なし
