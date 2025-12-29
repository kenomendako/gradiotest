# 情景画像毎ターン送信バグ修正レポート

**日付**: 2025-12-29  
**ブランチ**: `fix/scenery-image-every-turn-bug`

---

## 問題の概要

情景画像送信機能で、「変更時のみ」モードに設定していても、毎ターン画像がAIに送信されていた。

## 原因

`last_sent_scenery_image`（最後に送信した画像パス）の保存と読み込みに不整合があった：

- **保存側** (`room_manager.update_room_config`): `override_settings`配下に保存されていた
- **読み込み側** (`ui_handlers.py`): `room_config`のルート直下から読み込んでいた

結果として、読み込み時に常に`None`が返され、毎回「新しい景色を検出」と判断されていた。

## 修正内容

### 変更ファイル

#### [MODIFY] [room_manager.py](file:///c:/Users/baken/OneDrive/デスクトップ/gradio_github/gradiotest/room_manager.py)

```diff
- root_keys = ["room_name", "user_display_name", "description", "version"]
+ root_keys = ["room_name", "user_display_name", "description", "version", "last_sent_scenery_image"]
```

`last_sent_scenery_image`をルート直下に保存されるキーリストに追加。

## 検証結果

1. 1回目のメッセージ送信: `✅ 新しい景色を検出！画像をAIに送信します`
2. 2回目以降: `⏭️ 前回と同じ景色のためスキップ`

期待通りの動作を確認。
