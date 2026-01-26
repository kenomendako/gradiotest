# エディター向け指示書: マルチモーダル添付機能の修正

> **✅ 解決済み (2025-12-20)**: このドキュメントに記載された問題は全て解決されました。
> 詳細は `docs/guides/gradio_notes.md` のレッスン38, 39を参照してください。

## 問題の概要

1. **音声/動画**: ~~送信はされるがAIが内容を認識できない~~ → **解決**: `type="file", source_type="base64"`形式で送信するよう修正済み
2. **複数画像**: ~~1枚しか認識されない~~ → **解決**: `file_count="multiple"`を追加して複数添付を許可

## 背景

現在のコードでは、画像以外のファイルを全てテキストファイルとして読み込もうとしており、バイナリファイル（音声/動画）では正しく送信できない。

## 修正すべきファイル

`ui_handlers.py` の `handle_message_submission` 関数

## 修正箇所と変更内容

**L1426-1437** の `if mime_type.startswith('image/'):` ブロックを以下に置き換え：

```python
if mime_type.startswith('image/'):
    # 画像: image_url形式でBase64エンコード
    with open(file_path, "rb") as f:
        encoded_string = base64.b64encode(f.read()).decode("utf-8")
    user_prompt_parts_for_api.append({
        "type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded_string}"}
    })
elif mime_type.startswith('audio/') or mime_type.startswith('video/'):
    # 音声/動画: media形式でBase64エンコード
    with open(file_path, "rb") as f:
        encoded_string = base64.b64encode(f.read()).decode("utf-8")
    user_prompt_parts_for_api.append({
        "type": "media",
        "mime_type": mime_type,
        "data": encoded_string
    })
else:
    # テキスト系ファイル: 内容を読み込んでテキストとして送信
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        user_prompt_parts_for_api.append({"type": "text", "text": f"添付ファイル「{file_basename}」の内容:\n---\n{content}\n---"})
    except Exception as read_e:
        user_prompt_parts_for_api.append({"type": "text", "text": f"（ファイル「{file_basename}」の読み込み中にエラーが発生しました: {read_e}）"})
```

## 同様の修正が必要な箇所

`gemini_api.py` の `invoke_nexus_agent_stream` 関数 (L307-319) でも、`active_attachments` の処理で同じ問題がある：

```python
# L312-319付近: active_attachmentsの処理
if kind and kind.mime.startswith('image/'):
    # 画像のみ処理 ✅
else:
    # それ以外はテキストとして読み込み ❌
```

こちらも音声/動画の場合は `media` タイプで処理するよう修正が必要。

## 複数画像の問題について

ループ処理（L1408-1441）は正しく複数ファイルを処理しているように見えるため、問題は:
1. LangChainがマルチパートメッセージを正しく処理していない可能性
2. APIへの送信時に何かが失われている可能性

**追加調査ポイント:**
- 修正後に複数画像を送信してテストし、問題が解消されるか確認
- 問題が続く場合は、デバッグログを追加して `user_prompt_parts_for_api` の中身を確認

```python
# デバッグ用（問題が続く場合に追加）
print(f"--- [DEBUG] user_prompt_parts_for_api count: {len(user_prompt_parts_for_api)} ---")
for i, part in enumerate(user_prompt_parts_for_api):
    print(f"  Part {i}: type={part.get('type')}")
```

## 注意事項

- `docs/guides/gradio_notes.md` と `docs/journals/UI_LOGIC_INTEGRATION_LESSONS.md` を参照してから作業すること
- 新しいブランチを作成してから作業すること
- AIモデルのバージョンは変更しないこと

## テスト方法

1. **音声テスト**: 短い音声ファイル（MP3等）を添付して送信。AIが音声の内容について言及するか確認
2. **複数画像テスト**: 画像2枚を添付して送信。AIが両方の画像について言及するか確認
3. エラーログの有無を確認
