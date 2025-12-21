# 自律行動の重複発火バグ修正レポート

**日付**: 2025-12-21  
**関連ブランチ**: `fix/autonomous-action-duplicate-trigger`  
**ステータス**: ✅ 完了・観察中

---

## 概要

自律行動が30秒ごとのチェックで何度も発火してしまう問題を修正しました。

---

## 問題の現象

自律行動モードを有効にすると、設定した無操作時間（例：5分）経過後に自律行動が発火するが、その後も30秒ごとのチェックで**繰り返し発火**してしまう。

期待動作：無操作時間経過後に**1回だけ**発火し、次は再度無操作時間が経過するまで待機する。

---

## 根本原因

「静観」を選択した場合のログエントリにタイムスタンプがなく、ログの「最終更新時刻」が更新されないため、次のチェック時も無操作時間を超過していると判定されてしまっていた。

---

## 修正方針（ハイブリッド方式）

指示書 `docs/guides/AUTONOMOUS_ACTION_FIX_INSTRUCTIONS.md` に基づき、二重の安全装置を導入。

### 1. 静観ログへのタイムスタンプ追加

```python
# alarm_manager.py L365
timestamp = f"\n\n{datetime.datetime.now().strftime('%Y-%m-%d (%a) %H:%M:%S')}"
utils.save_message_to_log(log_f, "## SYSTEM:autonomous_status", f"（AIは静観を選択しました）{timestamp}")
```

→ ログの「最終更新時刻」が更新され、次回チェック時に再発火しなくなる。

### 2. メモリ内フラグによる二重発火防止

```python
# グローバル変数（L30）
_last_autonomous_trigger_time = {}  # ルーム名 -> 最後の発火時刻

# trigger_autonomous_action関数の冒頭（L267-270）
global _last_autonomous_trigger_time
_last_autonomous_trigger_time[room_name] = datetime.datetime.now()

# check_autonomous_actions関数内（L445-451）
last_trigger = _last_autonomous_trigger_time.get(room_folder)
if last_trigger:
    minutes_since_trigger = (now - last_trigger).total_seconds() / 60
    if minutes_since_trigger < inactivity_limit:
        continue  # まだ間隔が空いていないのでスキップ
```

→ ログに依存せず、メモリ上で発火間隔を管理。

---

## 修正ファイル

| ファイル | 箇所 | 修正内容 |
|----------|------|----------|
| `alarm_manager.py` | L30 | グローバル変数 `_last_autonomous_trigger_time` を追加 |
| `alarm_manager.py` | L267-270 | `trigger_autonomous_action` 関数で発火時刻を記録 |
| `alarm_manager.py` | L365 | 静観ログにタイムスタンプを追加 |
| `alarm_manager.py` | L445-451 | `check_autonomous_actions` で重複発火防止チェック |

---

## テスト手順

1. 自律行動を有効にして待機
2. 無操作時間経過後、発火が1回のみであることを確認
3. 設定した時間経過後にのみ再発火することを確認

---

## コミット

- `8610bfe` - fix: 自律行動の重複発火バグを修正

---

## 備考

- 多重発火の別パターンについては引き続き観察が必要
- メモリ内フラグはアプリ再起動でリセットされるが、ログのタイムスタンプが主な防御線となるため実用上問題なし
