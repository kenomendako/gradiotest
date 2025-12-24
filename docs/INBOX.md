# 📥 タスク・インボックス

思いついたタスクや気づいたバグをここにメモしてください。  
Antigravityが定期的に確認し、優先順位をつけてタスクリストに整理します。

---

## 未整理タスク

- [ ] 現在地連動背景表示機能で、AIが現在地を変更した時や現在地画像を新規生成したり登録したりして変更された時も、背景画像を更新するようにしたい。

- [ ] UIからルーム削除を実行しても削除されないバグ。
--- ルーム削除実行: G3テスト2 ---
Traceback (most recent call last):
  File "C:\Users\baken\OneDrive\デスクトップ\gradio_github\gradiotest\ui_handlers.py", line 4131, in handle_delete_room
    room_manager.delete_room(room_name)
    ^^^^^^^^^^^^^^^^^^^^^^^^
AttributeError: module 'room_manager' has no attribute 'delete_room'
C:\Users\baken\OneDrive\デスクトップ\gradio_github\gradiotest\venv\Lib\site-packages\gradio\blocks.py:1886: UserWarning: The 'tuples' format for chatbot messages is deprecated and will be removed in a future version of Gradio. Please set type='messages' instead, which uses openai-style 'role' and 'content' keys.
  state[block._id] = block.__class__(**kwargs)

### 整理済み（2025-12-23）
- [x] 優先度高。新規ルーム作成時、情景画像生成をオフにする。 → TASK_LIST へ移動
- [x] 優先度高。APIコンテキスト設定の初期状態変更。 → TASK_LIST へ移動
- [x] モデルリスト「(Slow Response)」除去。 → TASK_LIST へ移動

### 整理済み（2025-12-22）
- [x]「話題クラスタ」をAPI送信コンテキストに含めるかどうかを選択できるようにする。 → TASK_LIST へ移動
- [x]共通設定のデバッグモードの虫の絵文字削除 → TASK_LIST へ移動
- [x]送信後トータルトークン数表示 → TASK_LIST へ移動



---

## メモの書き方

```markdown
- [ ] やりたいこと / 問題の説明
  - 詳細があれば追記
  - スクリーンショットがあればパスを記載
```

---

## 関連リンク

- **タスクリスト**: [docs/plans/TASK_LIST.md](file:///c:/Users/baken/OneDrive/%E3%83%87%E3%82%B9%E3%82%AF%E3%83%88%E3%83%83%E3%83%97/gradio_github/gradiotest/docs/plans/TASK_LIST.md)
- **開発サイクル**: `.agent/workflows/dev-cycle.md`

---

*最終更新: 2025-12-22*
