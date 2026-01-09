# 修正レポート: Web巡回ツールのTavily Extractエラー

## 概要
Web巡回ツールやURL読み込みツールで使用している `TavilyExtract` クラスの初期化時にエラーが発生し、コンテンツ要約が正しく行われない問題を修正しました。

## 問題の原因
`TavilyExtract` ライブラリの仕様変更または誤解により、APIキーを渡すための引数名が誤っていました。
- **誤**: `api_key=...`
- **正**: `tavily_api_key=...`

このため、ライブラリ側でAPIキーを受け取れず、環境変数 `TAVILY_API_KEY` を探しに行き、それも設定されていないために `ValidationError` が発生していました。

## 修正内容
以下の2つのファイルにおいて、`TavilyExtract` インスタンス化時の引数名を修正しました。

1.  `tools/watchlist_tools.py`
2.  `tools/web_tools.py`

```python
# 修正前
extractor = TavilyExtract(
    api_key=config_manager.TAVILY_API_KEY,
    extract_depth="basic"
)

# 修正後
extractor = TavilyExtract(
    tavily_api_key=config_manager.TAVILY_API_KEY,
    extract_depth="basic"
)
```

## 検証結果
- 修正後の引数名 (`tavily_api_key`) で `TavilyExtract` が正常に初期化されることを確認しました（再現スクリプトによる検証）。
- コードの構文チェックを行い、エラーがないことを確認しました。

## 残課題
なし
