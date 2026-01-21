# チャット支援のログ修正で思考ログが消失・修正されない問題の修正 (2026-01-21)

## 概要

チャット支援ツールの「読点修正（ログ修正）」機能および「チャット編集」機能で、思考ログ（`[THOUGHT]...[/THOUGHT]` タグ）が消失・修正されない問題を修正しました。

## 原因

`ui_handlers.py` の以下2つの関数が、古い `【Thoughts】` タグ形式のみに対応しており、現行の `[THOUGHT]` タグ形式を認識しなかったため、思考ログが本文の一部として誤処理されていました。

- `handle_log_punctuation_correction`
- `handle_chatbot_edit`

## 修正内容

### `ui_handlers.py`

1. **`handle_log_punctuation_correction` 関数**
   - 思考ログ検出パターンを拡張し、新形式 `[THOUGHT]` と旧形式 `【Thoughts】` の両方に対応
   - タグ除去パターンも両形式に対応
   - 再組立時に元のタグ形式を維持（新形式なら新形式、旧形式なら旧形式）

2. **`handle_chatbot_edit` 関数**
   - 元のログから思考ログのタグ形式を検出
   - UI編集後の再組立時に元のタグ形式を維持

### `tests/verify_timestamp_fix.py`

- 新形式 `[THOUGHT]` のテストケースを3件追加
- テスト結果の視認性を向上（成功/失敗のカウントとアイコン表示）

## 検証結果

```
============================================================
思考ログ・タイムスタンプ分離テスト (新形式対応版)
============================================================
結果: 8 passed, 0 failed
============================================================
```

## 関連ファイル

- [ui_handlers.py](file:///home/baken/nexus_ark/ui_handlers.py)
- [tests/verify_timestamp_fix.py](file:///home/baken/nexus_ark/tests/verify_timestamp_fix.py)
