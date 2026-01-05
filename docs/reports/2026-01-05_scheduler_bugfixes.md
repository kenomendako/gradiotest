# スケジューラ関連バグ修正レポート

**日付:** 2026-01-05  
**ブランチ:** `fix/watchlist-scheduled-daily`  
**ステータス:** ✅ 完了

---

## 問題の概要

スケジューラに関連する2つのバグを修正しました。

1. **ウォッチリスト「毎日指定時刻」巡回が発火しない問題**
2. **自律行動クールダウンが通常会話でリセットされない問題**

---

## 修正内容

### 1. ウォッチリスト定時巡回

**原因分析:**
`watchlist_manager.py` の `get_due_entries()` メソッドで誤った条件式を使用していました。

```python
# 誤ったロジック（修正前）
if (now - last_dt).total_seconds() >= 24 * 3600:  # 24時間経過
    if abs(self._time_diff_minutes(scheduled_time, current_time)) <= 30:  # 時刻一致
```

**問題:**
- 例: `07:00` 指定、最終チェック `昨日 23:15`
- 翌朝 `07:00` 時点では経過時間 ≈ 8時間（24時間未満）
- → 最初の条件を満たさず、発火しない

**修正:**
```python
# 正しいロジック（修正後）
today_scheduled_dt = now.replace(hour=scheduled_hour, minute=scheduled_minute)
if now >= today_scheduled_dt and last_dt < today_scheduled_dt:
    due_entries.append(entry)
```

### 2. 自律行動クールダウンリセット

**2箇所の問題を発見・修正:**

#### 問題1: 呼び出しの欠落
`MotivationManager.update_last_interaction()` が通常会話処理から呼び出されていなかった。

**修正:** `ui_handlers.py` の `_stream_and_handle_response` の finally ブロックで呼び出しを追加。

#### 問題2: メモリキャッシュの優先
`alarm_manager.py` の `check_autonomous_actions()` がメモリ上の `_last_autonomous_trigger_time` を優先して参照していた。永続化ファイルを更新しても、古いキャッシュが使われ続けていた。

**修正:** 常に永続化データから最新値を読むように変更。

```python
# 修正前
last_trigger = _last_autonomous_trigger_time.get(room_folder)
if not last_trigger:
    last_trigger = mm.get_last_autonomous_trigger()

# 修正後
last_trigger = mm.get_last_autonomous_trigger()  # 常に永続化データを参照
```

---

## 変更したファイル

| ファイル | 変更内容 |
|----------|----------|
| `watchlist_manager.py` | `get_due_entries()` の daily_HH:MM 判定ロジック修正 |
| `ui_handlers.py` | `MotivationManager` インポート追加、クールダウンリセット呼び出し追加 |
| `alarm_manager.py` | メモリキャッシュ優先を廃止、常に永続化データを参照 |
| `CHANGELOG.md` | 修正内容を記録 |
| `docs/INBOX.md` | タスク完了マーク、新規タスク追加 |

---

## 検証結果

- [x] アプリ起動確認
- [x] ウォッチリスト発火確認（13:00設定 → 13:15発火）
- [x] クールダウンリセット確認（会話後 1分/320分 に正常リセット）
- [x] 副作用チェック（他機能への影響なし）

---

## 教訓

1. **キャッシュとSingle Source of Truthの乖離に注意**: メモリキャッシュを使う場合、他モジュールからの更新が反映されない可能性がある。
2. **関数呼び出しの追加漏れ**: 関数を実装しても、適切な場所から呼び出されていなければ機能しない。
3. **スケジューラのデバッグ**: 時刻条件のデバッグは実時間を待つ必要があるため、ログ出力を充実させることが重要。

---

## 残課題

- **Tavily Extractエラー**: URLをリストではなく辞書形式で渡す必要がある（INBOX追加済み）
- **ウォッチリスト巡回時刻の一括設定機能**: 各エントリごとに設定するのが手間（INBOX追加済み）
