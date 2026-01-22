# エピソード記憶注入バグ修正

**日付:** 2026-01-22  
**ブランチ:** `fix/episodic-memory-injection`  
**ステータス:** ✅ 完了

---

## 問題の概要

エピソード記憶の注入機能に複数のバグがあり、意図しない記憶が注入されていた。

1. **週次記憶の重複**: 同じ日付範囲（`2026-01-12~2026-01-18`）の週次記憶が3件重複
2. **週次記憶の誤注入**: 2日間のルックバック設定でも7日分の週次要約が混入
3. **日付計算のズレ**: 「過去2日」が1日ズレて18日と19日が表示（正しくは19日と20日）
4. **datetime.now()エラー**: インポート方法の不一致による実行時エラー
5. **表情アップロード配線バグ**: Gradioの引数配線ミス（起動時警告）

---

## 修正内容

### 1. 重複データの削除
- `characters/ルシアン/memory/episodic/2026-01.json` から重複した週次記憶を手動削除

### 2. フィルタリングロジックの改善
**ファイル:** `episodic_memory_manager.py`

ルックバック日数より長い範囲の記憶を除外するロジックを追加:
```python
# 記憶の日付範囲がルックバック期間より長い場合は除外
range_days = (item_end_date - item_start_date).days + 1
if range_days > lookback_days:
    continue  # 週次記憶（7日間）は2日のルックバックに含めない
```

### 3. ルックバック基準の変更
**ファイル:** `agent/graph.py`

「ログの最古日付」基準から「今日」基準に変更:
```python
# Before: oldest_log_date_str を基準（ログ内の最初の日付）
# After: today_str = datetime.now().strftime('%Y-%m-%d')
```

### 4. datetime.now() インポートエラー修正
**ファイル:** `agent/graph.py`

`from datetime import datetime` でインポートされているため:
```python
# Before: datetime.datetime.now()  # エラー
# After: datetime.now()  # 正しい
```

### 5. 表情ファイルアップロードの配線修正
**ファイル:** `nexus_ark.py`

Gradioの `.upload()` イベントの正しい引数配線:
```python
# Before: inputs=[current_room_name, new_expression_name]  # 2引数
# After: inputs=[expression_file_upload, current_room_name, new_expression_name]  # 3引数
```

---

## 変更したファイル

| ファイル | 変更内容 |
|----------|----------|
| `characters/ルシアン/memory/episodic/2026-01.json` | 重複した週次記憶を削除 |
| `episodic_memory_manager.py` | `get_episodic_context` に範囲フィルタリング追加 |
| `agent/graph.py` | ルックバック基準を「今日」に変更、datetime.now()修正 |
| `nexus_ark.py` | 表情アップロードの引数配線修正 |

---

## 検証結果

- [x] アプリ起動確認（警告なし）
- [x] Python検証スクリプトで正しい日付（19日・20日）が取得されることを確認
- [x] ユーザーによる動作確認完了

---

## 残課題

- **重複防止ロジックの追加**: `compress_old_episodes` に同じ日付範囲の圧縮記憶が既に存在する場合スキップするロジックを追加することで、将来の重複を防止できる（INBOXに追加済み）
