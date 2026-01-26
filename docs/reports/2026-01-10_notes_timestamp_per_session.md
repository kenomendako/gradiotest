# ノート編集時のタイムスタンプ重複修正

**日付**: 2026-01-10
**ブランチ**: `fix/notes-timestamp-per-session`
**ステータス**: ✅ 完了

---

## 問題の概要

研究ノートと創作ノートで、AIが複数行の内容を「1行ごとに別々の編集指示」として送信した場合、各指示ごとにタイムスタンプが追加され、以下のような不要な重複が発生していた：

```
---
[2026-01-10 19:30] 研究記録
### 概要

---
[2026-01-10 19:30] 研究記録
本文の1行目...

---
[2026-01-10 19:30] 研究記録
本文の2行目...
```

---

## 原因

`_apply_research_notes_edits` と `_apply_creative_notes_edits` 関数内で、各編集指示（`insert_after` / `replace`）に対して無条件にタイムスタンプを付与していた。

---

## 修正内容

### 変更したファイル

| ファイル | 変更内容 |
|----------|----------|
| `tools/research_tools.py` | `timestamp_added` フラグを追加し、セッション内で最初の編集のみにタイムスタンプを付与 |
| `tools/creative_tools.py` | 同上 |

### 修正ロジック

```python
# セッション単位で一度だけタイムスタンプを付与するためのフラグ
timestamp_added = False

for inst in instructions:
    # ...
    if op in ["replace", "insert_after"] and str(final_content).strip():
        # 最初のコンテンツ追加時のみタイムスタンプヘッダーを付与
        if not timestamp_added:
            final_content = f"\n---\n{timestamp} 研究記録\n{final_content}\n"
            timestamp_added = True
```

---

## 期待される結果

修正後は、1回の編集操作で以下のように1つのタイムスタンプのみが付与される：

```
---
[2026-01-10 19:30] 研究記録
### 概要
本文の1行目...
本文の2行目...
```

---

*作成日: 2026-01-10*
