# get_room_files_paths 6変数化 技術レポート

> 作成日: 2026-01-05
> ブランチ: `feature/phase3-research-notes`

---

## 概要

Phase 3「文脈分析・統合エンジン」の基盤整備として、`room_manager.get_room_files_paths()` の戻り値を **5変数から6変数に拡張** しました。

---

## 変更内容

### 変更前（5変数）
```python
log_file, system_prompt_file, profile_image_path, memory_main_path, notepad_path = get_room_files_paths(room_name)
```

### 変更後（6変数）
```python
log_file, system_prompt_file, profile_image_path, memory_main_path, notepad_path, research_notes_path = get_room_files_paths(room_name)
```

### 新規追加された戻り値

| 位置 | 変数名 | パス | 用途 |
|------|--------|------|------|
| 6番目 | `research_notes_path` | `characters/{room}/research_notes.md` | Phase 3 研究・分析ノート |

---

## 関連ファイル

### 定数定義
- **`constants.py`**: `RESEARCH_NOTES_FILENAME = "research_notes.md"` を追加

### 関数定義
- **`room_manager.py`**: `get_room_files_paths()` を6変数返却に変更

### 呼び出し元（修正済み: 20+箇所）
| ファイル | 箇所数 |
|----------|--------|
| `ui_handlers.py` | 10+ |
| `gemini_api.py` | 3 |
| `alarm_manager.py` | 2 |
| `utils.py` | 1 |
| `timers.py` | 1 |
| `dreaming_manager.py` | 1 |
| `memory_manager.py` | 1 |
| `agent/graph.py` | 1 |
| `tools/memory_tools.py` | 2 |
| `tools/notepad_tools.py` | 2 |
| `tools/notification_tools.py` | 1 |

---

## 今後の開発における注意事項

### 新規に `get_room_files_paths` を呼び出す場合

必ず **6変数** でアンパックしてください：

```python
# ✅ 正しい（6変数）
log_f, sys_prompt, img, mem, notepad, research = get_room_files_paths(room_name)

# ✅ 使わない変数は _ で受ける
log_f, _, _, _, _, _ = get_room_files_paths(room_name)

# ❌ 誤り（5変数 - ValueError発生）
log_f, _, _, _, _ = get_room_files_paths(room_name)
```

### 戻り値を追加する場合

将来さらに戻り値を追加する場合は、このドキュメントを更新し、全ての呼び出し元を漏れなく修正してください。

---

## Phase 3 今後の予定

- [ ] **Step 4**: UI・ハンドラの追加（研究ノートの表示・編集）
- [ ] **Step 5**: 分析ツールと即時分析フローの実装
