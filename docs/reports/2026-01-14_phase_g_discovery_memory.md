# Phase G: 知識欲求の拡張（発見記憶）

**日付:** 2026-01-14  
**ブランチ:** `feat/phase-g-discovery-memory`  
**ステータス:** ✅ 完了

---

## 問題の概要

Phase Bで解決済みの問いをFACT/INSIGHTに変換して保存していたが、「発見の喜び」自体は記録されていなかった。知識獲得の瞬間をエピソード記憶として刻み、RAG検索で「発見体験」として想起可能にする。

---

## 修正内容

`dreaming_manager.py` を拡張し、FACT/INSIGHT保存時に発見エピソード記憶を生成するようにした。

---

## 変更したファイル

- `dreaming_manager.py` - `EpisodicMemoryManager`のインポート追加、`_create_discovery_episode()`新規実装、FACT/INSIGHT保存時に発見エピソード生成
- `docs/specifications/MEMORY_SYSTEM_SPECIFICATION.md` - Phase Gセクション追加
- `docs/plans/TASK_LIST.md` - Phase Gタスクを追加

---

## 検証結果

- [x] 構文チェック (`python -m py_compile dreaming_manager.py`)
- [x] インポートテスト（venv環境）

---

## 残課題

- Phase F: 関係性維持欲求の実装（ペルソナ感情出力）
