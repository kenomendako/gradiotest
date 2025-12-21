# 添付ファイルのBase64戦略

**日付**: 2025-12-20  
**ステータス**: 承認済み

## 背景

音声・動画ファイルをAIに送信する際、どの方式を使うべきか。

## 選択肢

1. **File Upload API**: Google AI Files APIで事前アップロード
2. **Base64 Embedding**: ファイルをBase64エンコードしてメッセージに埋め込む

## 決定

**Base64 Embedding** を採用。

理由:
- LangChainがFile Upload APIを十分にサポートしていない
- `langchain-google-genai` のバージョン問題を回避できる
- シンプルで依存関係が少ない

## 影響

- 大きなファイル（動画等）はAPI制限に引っかかる可能性
- 将来的にFile Upload APIへの移行も検討

## 参照

- `docs/journals/MEDIA_ATTACHMENT_WAR_DIARY.md`
