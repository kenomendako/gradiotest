# Phase F: 関係性維持欲求（Relatedness Drive）

**日付:** 2026-01-15  
**ブランチ:** `feat/phase-f-relatedness-drive`  
**ステータス:** ✅ 完了

---

## 問題の概要

従来の「奉仕欲（Devotion Drive）」はユーザーの感情をLLMで分析して計算していたが、これをペルソナ自身の感情出力に基づく「関係性維持欲求（Relatedness Drive）」に置き換える。APIコスト削減と、よりペルソナ主体の動機システムへの移行が目的。

---

## 修正内容

### 1. ペルソナ感情出力システム
- プロンプトを変更し、`<persona_emotion category="..." intensity="..."/>` タグを出力させる
- 7つの感情カテゴリ: joy, contentment, protective, anxious, sadness, anger, neutral
- 強度（0.0〜1.0）を併せて出力

### 2. Relatedness Drive の実装
- `set_persona_emotion()` メソッドを新規実装
- `calculate_relatedness()` メソッドを新規実装
- 感情カテゴリと強度から関係性維持欲求レベルを計算

### 3. 絆確認エピソード記憶
- 不安/庇護欲 → 安心/喜びへの感情シフト時に自動生成
- `type: "bonding"` のエピソード記憶として保存

### 4. Devotion の完全廃止
- ユーザー感情分析LLM呼び出しを廃止（APIコスト削減）
- `get_dominant_drive()` からdevotionを削除
- UIラベルを「関係性維持（Relatedness）」に統一

---

## 変更したファイル

| ファイル | 変更内容 |
|----------|----------|
| `agent/prompts.py` | ペルソナ感情タグ出力プロンプトに変更 |
| `ui_handlers.py` | 感情タグ抽出パターン、ログ出力、UI表示を更新 |
| `motivation_manager.py` | `set_persona_emotion`, `calculate_relatedness`, 絆確認エピソード生成を追加 |
| `arousal_calculator.py` | ペルソナ感情（カテゴリ＋強度）を使用したArousal計算に変更 |
| `agent/graph.py` | ユーザー感情分析呼び出しを廃止、ドライブ計算からdevotionを削除 |
| `nexus_ark.py` | UIスライダーラベルを「関係性維持」に変更 |
| `docs/specifications/MEMORY_SYSTEM_SPECIFICATION.md` | Phase F仕様を追記 |

---

## 検証結果

- [x] アプリ起動確認
- [x] 構文チェック（全ファイルパス）
- [x] インポートテスト
- [x] 「内的状態を読み込む」で「💞 関係性維持（Relatedness）」表示確認
- [x] ペルソナ感情タグ（`<persona_emotion>`）の抽出動作確認

---

## 残課題

- なし（UIドライブ表示の改善は Phase H で対応予定）
