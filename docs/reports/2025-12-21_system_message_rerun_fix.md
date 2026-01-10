# システムメッセージ再生成修正レポート

**日付**: 2025-12-21  
**ブランチ**: `fix/system-message-rerun`  
**ステータス**: ✅ 完了・マージ済み

---

## 問題

チャット履歴でシステムメッセージ（空応答通知、ツール結果など）を選択して「🔄 再生成」ボタンを押すと、システムメッセージの内容がユーザーメッセージとして再送信されてしまっていた。

## 原因

`handle_rerun_button_click`関数の条件分岐で、`SYSTEM`ロールが考慮されていなかった：

```python
# 修正前
is_ai_message = selected_message.get("role") == "AGENT"
if is_ai_message:  # SYSTEMはここに入らない
    ...
else:  # SYSTEMはここに入り、ユーザーメッセージとして扱われる
    ...
```

## 修正内容

`SYSTEM`メッセージも`AGENT`と同様に扱い、直前のユーザーメッセージを再送信するように変更：

```python
# 修正後
is_ai_or_system_message = selected_message.get("role") in ("AGENT", "SYSTEM")
if is_ai_or_system_message:
    restored_input_text = utils.delete_and_get_previous_user_input(...)
else:  # ユーザー発言の場合のみ
    restored_input_text = utils.delete_user_message_and_after(...)
```

## 変更ファイル

| ファイル | 変更内容 |
|----------|----------|
| [ui_handlers.py](../../ui_handlers.py#L1520-L1529) | `handle_rerun_button_click`の条件分岐修正 |

## 検証

- アプリ再起動後にSYSTEMメッセージから再生成を試行し、直前のユーザーメッセージが再送信されることを確認する（ユーザーによる手動検証を推奨）
