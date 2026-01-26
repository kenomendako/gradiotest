# Intent-Aware Retrieval 実装レポート

**日付:** 2026-01-16  
**ブランチ:** `feat/intent-aware-retrieval`  
**ステータス:** ✅ 完了

---

## 問題の概要

記憶検索で時間減衰を一律に廃止していたが、技術的情報は古いと価値が下がる一方、感情的な思い出は古くても大切。クエリの意図に応じて動的に重み付けを調整する仕組みが必要だった。

---

## 修正内容

**Intent-Aware Retrieval**を実装し、以下の機能を追加：

1. **Intent分類器**: LLMでクエリを5種類（emotional/factual/technical/temporal/relational）に分類
2. **時間減衰計算**: 記憶の日付から指数減衰スコア（約14日で半減）を計算
3. **3項式複合スコアリング**: Intent別に重み付けを動的調整
   - 感情的質問 → 古い記憶も優先（γ=0.1）
   - 技術的質問 → 新しい情報優先（γ=0.6）

---

## 変更したファイル

- `constants.py` - INTENT_WEIGHTS, TIME_DECAY_RATE, DEFAULT_INTENT 追加
- `rag_manager.py` - `classify_query_intent()`, `calculate_time_decay()` 追加、`search()` を3項式に拡張
- `docs/plans/research/arousal_aware_time_decay_study.md` - 研究メモ更新
- `docs/specifications/MEMORY_SYSTEM_SPECIFICATION.md` - 仕様書更新

---

## 検証結果

- [x] 構文チェック通過
- [x] 技術的質問の分類テスト: `'記憶システム RAG...'` → `technical (γ=0.6)`
- [x] 感情的質問の分類テスト: `'娘 歯磨き 育児...'` → `emotional (γ=0.1)`

---

## 残課題

- Phase 4-5（チューニング、評価）は今後のタスクとして継続
- ルールベースフォールバック（LLMコスト削減）は将来検討
