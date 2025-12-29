# 文字置き換え機能による思考ログ表示崩れ修正レポート

**日付**: 2025-12-29  
**ブランチ**: `fix/redaction-thought-log-display`

---

## 問題の概要

「🛠️ チャット支援ツール」の文字置き換え機能（スクリーンショットモード）を使用すると、思考ログの文字や行間が大きくなり表示が崩れる問題。

## 原因分析

`ui_handlers.py` の `format_history_for_gradio` 関数で、文字置き換え処理（`<span style="background-color: ...">` タグを挿入）した後、思考ログ（コードブロック）内のテキストがHTMLエスケープされていなかったため、Markdown記法（`**太字**`、`1.`など）がGradioによって解釈されていた。

### 参照した過去の知見

- `gradio_notes.md` レッスン17：`render_markdown`の二重解釈問題
- `gradio_notes.md` レッスン24：「完全な模倣」アーキテクチャ
- `THINKING_LOG_RENDERING_WAR.md`：思考ログCSSの詳細

## 修正内容

### 変更ファイル

#### [ui_handlers.py](file:///c:/Users/baken/OneDrive/デスクトップ/gradio_github/gradiotest/ui_handlers.py)

**コードブロック処理（L2745-2765）**:
- `<span>` タグを一時的にプレースホルダーに置換
- 残りのテキストを `html.escape()` でエスケープ（Markdown記法を無効化）
- プレースホルダーを元の `<span>` タグに戻す
- 改行を `<br>` に変換

**通常テキスト処理（L2768-2790）**:
- 同様のプレースホルダー方式でHTMLエスケープ

## 検証結果

| 項目 | 結果 |
|------|------|
| 思考ログの文字サイズ | ✅ 正常 |
| 思考ログの行間 | ✅ 正常 |
| 背景色付き置き換え表示 | ✅ 正常 |
| 通常テキストの表示 | ✅ 正常 |

## 既知の制限事項

**コピー機能の制限**:
- スクリーンショットモード有効時、コピーボタンを使用するとHTMLタグ（`<div>`, `<br>`, `<span>`など）がそのままコピーされる
- これはGradioの内部動作に起因する制限
- **回避策**: コピーが必要な場合はスクリーンショットモードをOFFにする

この制限はスクリーンショットモードの設計判断として許容する。スクリーンショットモードは画面キャプチャ目的であり、コピー機能はOFF時に使用できるため影響は限定的である。

## 関連ドキュメント

- [gradio_notes.md](file:///c:/Users/baken/OneDrive/デスクトップ/gradio_github/gradiotest/docs/guides/gradio_notes.md) - レッスン36として追記
