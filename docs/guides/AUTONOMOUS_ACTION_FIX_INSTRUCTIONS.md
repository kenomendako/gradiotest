# エディター向け指示書: 自律行動の重複発火バグ修正

## 問題

自律行動が30秒ごとのチェックで何度も発火してしまう。原因は「静観」ログにタイムスタンプがないため。

## 修正方針: ハイブリッド方式

1. **タイムスタンプを追加** → 活動履歴として残る + 再発火防止
2. **メモリ内フラグ** → 二重の安全装置

## 修正箇所

### 1. `alarm_manager.py` - グローバル変数追加 (L28付近)

```python
# 既存
alarms_data_global = []
alarm_thread_stop_event = threading.Event()

# 追加
_last_autonomous_trigger_time = {}  # 重複発火防止用
```

### 2. `alarm_manager.py` - `trigger_autonomous_action` (L358付近)

**変更前:**
```python
utils.save_message_to_log(log_f, "## SYSTEM:autonomous_status", "（AIは静観を選択しました）")
```

**変更後:**
```python
timestamp = f"\n\n{datetime.datetime.now().strftime('%Y-%m-%d (%a) %H:%M:%S')}"
utils.save_message_to_log(log_f, "## SYSTEM:autonomous_status", f"（AIは静観を選択しました）{timestamp}")
```

### 3. `alarm_manager.py` - `trigger_autonomous_action` 関数の最初 (L266付近)

**追加:**
```python
# 発火時刻を記録（重複防止）
global _last_autonomous_trigger_time
_last_autonomous_trigger_time[room_name] = datetime.datetime.now()
```

### 4. `alarm_manager.py` - `check_autonomous_actions` (L444付近)

**変更前:**
```python
if elapsed_minutes >= inactivity_limit:
    quiet_start = ...
```

**変更後:**
```python
if elapsed_minutes >= inactivity_limit:
    # 重複発火防止チェック
    last_trigger = _last_autonomous_trigger_time.get(room_folder)
    if last_trigger:
        minutes_since_trigger = (now - last_trigger).total_seconds() / 60
        if minutes_since_trigger < inactivity_limit:
            continue  # まだ間隔が空いていないのでスキップ
    
    quiet_start = ...
```

## 注意

- 新しいブランチを作成してから作業すること
- `docs/guides/gradio_notes.md` を参照すること

## テスト

1. 修正後、自律行動を有効にして待機
2. 発火が1回のみであることを確認
3. 設定した時間経過後にのみ再発火することを確認
