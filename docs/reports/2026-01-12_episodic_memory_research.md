# エピソード記憶改善研究 & 圧縮閾値調整

**日付:** 2026-01-12  
**ブランチ:** main  
**ステータス:** ✅ 完了

---

## 問題の概要

エピソード記憶の分量が大きすぎる（約278KB）ため、記憶の質と量を再検討。MemRL、GDPO、EILSなどの論文を調査し、Arousalベースの記憶評価・圧縮アプローチを検討した。

---

## 修正内容

### 1. 研究ドキュメント作成
- MemRL（構造化トリプレット、Two-Phase Retrieval）
- GDPO（多軸報酬の分離正規化）
- EILS（感情ホメオスタシスフレームワーク）
- Affect-driven RL（Arousalベース報酬）
- ルシアンの洞察：Valenceではなく**Arousal（感情の振れ幅）**に注目

### 2. 既存システムとの接続発見
- Nexus Arkには既に内部状態システム（Boredom, Curiosity, Goal Achievement, Devotion）が実装済み
- EILSの概念と高い親和性 → 拡張による実装が可能

### 3. 圧縮閾値の調整
- `compress_old_episodes()`: 180日→60日
- `get_compression_stats()`: 180日→60日

---

## 変更したファイル

- `episodic_memory_manager.py` - 圧縮閾値を180日から60日に変更
- `docs/INBOX.md` - タスク名を更新、研究メモへのリンク追加
- `docs/plans/research/episodic_memory_memrl_study.md` - 新規作成（研究メモ）

---

## 検証結果

- [x] アプリ起動確認（ユーザー確認済み）
- [x] 変更箇所の影響確認（デフォルト値変更のため全呼び出し箇所に適用）

---

## 今後の実装課題（Phase 1）

- [ ] 会話開始時の内部状態スナップショット保存
- [ ] 会話終了時のArousal計算関数
- [ ] `today_summary.json`にArousalスコア追加
- [ ] `episodic_memory.json`にArousalスコア追加

---

## 関連ドキュメント

- [研究メモ](../plans/research/episodic_memory_memrl_study.md)
