# 📥 タスク・インボックス

思いついたタスクや気づいたバグをここにメモしてください。  
Antigravityが定期的に確認し、優先順位をつけてタスクリストに整理します。

---

## 未整理タスク

- [ ] 現在地連動背景表示機能で、AIが現在地を変更した時や現在地画像を新規生成したり登録したりして変更された時も、背景画像を更新するようにしたい。

- [ ] 新規ルーム作成時に「個別設定を保存しました」通知が2回表示される問題
  - UI体験改善（クリティカルではない）

### 整理済み（2025-12-24）
- [x] ルーム削除バグ: delete_room関数がなかった → room_manager.pyに追加済み

### 整理済み（2025-12-23）
- [x] 優先度高。新規ルーム作成時、情景画像生成をオフにする。 → TASK_LIST へ移動
- [x] 優先度高。APIコンテキスト設定の初期状態変更。 → TASK_LIST へ移動
- [x] モデルリスト「(Slow Response)」除去。 → TASK_LIST へ移動

### 整理済み（2025-12-22）
- [x]「話題クラスタ」をAPI送信コンテキストに含めるかどうかを選択できるようにする。 → TASK_LIST へ移動
- [x]共通設定のデバッグモードの虫の絵文字削除 → TASK_LIST へ移動
- [x]送信後トータルトークン数表示 → TASK_LIST へ移動



---

## 📝 新規タスク追加（コピペ用）

```markdown
- [ ] [タスク名/問題の説明]
  - 詳細: 
  - 優先度: 🔴高 / 🟡中 / 🟢低
```

---

## 関連リンク

- **ステータス**: [docs/STATUS.md](file:///c:/Users/baken/OneDrive/デスクトップ/gradio_github/gradiotest/docs/STATUS.md)
- **タスクリスト**: [docs/plans/TASK_LIST.md](file:///c:/Users/baken/OneDrive/デスクトップ/gradio_github/gradiotest/docs/plans/TASK_LIST.md)
- **開発サイクル**: `.agent/workflows/dev-cycle.md`

---

*最終更新: 2025-12-24*
