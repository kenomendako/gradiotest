# 内的状態システム改善レポート

**完了日**: 2026-01-13  
**ブランチ**: `feat/internal-state-improvement`  
**関連タスク**: 🧠 内的状態 (Internal State)のブラッシュアップ

---

## 概要

AIペルソナの内的状態システムにおける以下の問題を修正しました：

1. **好奇心が常に0になる問題** - 全ての質問に`asked_at`がセットされていたため
2. **目標達成判定が機能しない問題** - LLMが目標IDを知らなかったため

---

## 変更点

### Phase A: 質問ライフサイクル修正

| ファイル | 変更内容 |
|---------|---------|
| `motivation_manager.py` | `calculate_curiosity()` を改善（回答待ち質問も計算に含める） |
| `motivation_manager.py` | `mark_question_resolved()` メソッド追加 |
| `motivation_manager.py` | `cleanup_resolved_questions()` メソッド追加 |
| `motivation_manager.py` | `auto_resolve_questions()` で `resolved_at` を使用 |

**修正前の計算ロジック:**
- `asked_at` がセットされた質問 → 計算から除外 → 好奇心=0

**修正後の計算ロジック:**
- 未質問（asked_at=None）: フル重み
- 回答待ち（asked_atあり、resolved_atなし）: 0.5倍の重み
- 解決済み（resolved_atあり）: 計算から除外

### Phase D: 目標ライフサイクル改善

| ファイル | 変更内容 |
|---------|---------|
| `goal_manager.py` | `get_goals_for_reflection()` メソッド追加（ID付き目標一覧） |
| `dreaming_manager.py` | 省察プロンプトで新メソッドを使用 |
| `dreaming_manager.py` | 睡眠時に質問クリーンアップを実行 |

---

## 検証結果

- ✅ 構文チェック（py_compile）通過
- ✅ アプリ正常起動
- ✅ `auto_resolve_questions()` で4件の質問が正しく解決済みにマーク
- ✅ 全質問解決済み時、好奇心=0（正常動作）

---

## 今後の拡張予定

- **Phase B**: 解決済み質問をエンティティ記憶/夢日記に変換
- **Phase C**: 感情検出カテゴリの統一（Devotion計算との整合性）
