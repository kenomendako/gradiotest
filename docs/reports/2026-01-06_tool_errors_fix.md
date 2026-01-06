# ツールバグ3件修正レポート

**日付:** 2026-01-06  
**ブランチ:** `bugfix/tool-errors`  
**ステータス:** ✅ 完了

---

## 問題の概要

3件のツール関連バグを修正:
1. `research_notes` バックアップタイプ未登録エラー
2. Tavily Extract バリデーションエラー
3. 情景画像送信時の Base64 パディングエラー（Incorrect padding）

---

## 修正内容

### 1. `research_notes` バックアップタイプ未登録

**原因:** `room_manager.py` の `create_backup` 関数内の `file_map` と `folder_map` に `research_notes` が登録されていなかった。

**修正:** `research_notes` を両マップと `ensure_room_files` のバックアップサブディレクトリ作成リストに追加。

### 2. Tavily Extract バリデーションエラー

**原因:** `langchain_tavily.TavilyExtract.invoke()` に渡す引数が、ライブラリ側の期待する形式と異なっていた。リスト `[url]` を渡していたが、辞書 `{"urls": [url]}` を期待していた。

**修正:** `watchlist_tools.py` の `_fetch_url_content` 関数で、`extractor.invoke([url])` を `extractor.invoke({"urls": [url]})` に変更。

### 3. 情景画像送信時の Base64 パディングエラー

**原因:** `utils.resize_image_for_api()` はタプル `(base64_string, format)` を返すが、`ui_handlers.py` の情景画像送信処理（1874行目付近）ではこれを単一変数として受け取っていた。結果として、`"data:image/png;base64,('SGVsbG8...', 'png')"` のような不正な文字列が生成されていた。

**修正:** 戻り値を正しくタプル展開し、適切な MIME タイプも設定するように修正。

---

## 変更したファイル

- `room_manager.py` - `research_notes` をバックアップタイプに追加
- `tools/watchlist_tools.py` - Tavily Extract の入力形式を辞書に変更
- `ui_handlers.py` - `resize_image_for_api` 戻り値のタプル展開を修正

---

## 検証結果

- [x] アプリ起動確認
- [x] 情景画像送信（リサイズ成功ログ確認）
- [x] 研究ノート編集（バックアップ作成成功）
- [x] ウォッチリストチェック（エラーなし）
- [x] 構文検証（`python -m py_compile`）パス

---

## 残課題

なし
