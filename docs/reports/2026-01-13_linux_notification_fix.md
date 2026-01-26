# Linuxデスクトップ通知エラー修正

**日付:** 2026-01-13  
**ブランチ:** `fix/linux-desktop-notification`  
**ステータス:** ✅ 完了

---

## 問題の概要

Linux環境でPushover通知成功後にplyerライブラリがデスクトップ通知を送信しようとして、`dbus`パッケージや`notify-send`コマンドが見つからず警告・エラーが表示されていた。

---

## 修正内容

`sys.platform.startswith('linux')` でOS判定を行い、Linux環境では `PLYER_AVAILABLE = False` としてデスクトップ通知をスキップするように変更。

---

## 変更したファイル

- `alarm_manager.py` - アラーム発火時のデスクトップ通知でLinux判定を追加
- `timers.py` - タイマー完了時のデスクトップ通知でLinux判定を追加

---

## 検証結果

- [x] 変更後のコードにシンタックスエラーがないことを確認
- [x] Pushover/Discord通知への影響なし（コードパスが分離されている）

---

## 残課題

なし
