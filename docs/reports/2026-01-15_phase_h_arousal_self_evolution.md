# Phase H: 記憶共鳴フィードバック機構（Arousal Phase 3）

**日付:** 2026-01-15  
**ブランチ:** `feat/phase-h-arousal-self-evolution`  
**ステータス:** ✅ 完了

---

## 問題の概要

記憶の重要度（Arousal）を静的な値のままにせず、ペルソナが実際に記憶を「使った」際にフィードバックを受けて自己更新する仕組みを導入。MAGMA論文の知見を適用。

---

## 修正内容

### 1. 記憶ID自動生成
- エピソード記憶保存時にIDを自動付与（`episode_2026-01-15_001`形式）
- 既存記憶129件へのマイグレーション実施

### 2. 共鳴フィードバック機構
- ペルソナが `<memory_trace id="..." resonance="..."/>` タグで共鳴度を報告
- 共鳴度に基づいてArousalを更新: `arousal_new = arousal_old + α(resonance - arousal_old)`

### 3. 共鳴度（resonance）基準
| 値 | 名称 | 意味 |
|----|------|------|
| 1.0 | 決定的共鳴 | この記憶なしでは応答が生まれなかった |
| 0.7 | 強い共鳴 | 応答の方向性に明確な影響 |
| 0.4 | 間接的共鳴 | 思考の背景として微かに響いた |
| 0.0 | 不協和音 | 提示されたが全く反応しなかった |

---

## 変更したファイル

- `episodic_memory_manager.py` - ID生成、update_arousal、get_episode_by_id、get_episodic_context修正
- `agent/prompts.py` - memory_traceタグ出力指示を追加
- `ui_handlers.py` - memory_traceタグ抽出とArousal更新呼び出し
- `tools/migrate_episode_ids.py` - 既存記憶IDマイグレーションスクリプト（新規）

---

## 検証結果

- [x] アプリ起動確認
- [x] 構文チェック成功
- [x] 共鳴フィードバック動作確認（ターミナルに `[MemoryTrace] 1件の記憶共鳴を処理` 表示）

---

## 残課題

- Salience-Based Token Budgeting（将来の拡張として検討中）
- RAG検索結果への共鳴フィードバックは対象外（エピソード記憶のみ対応）
