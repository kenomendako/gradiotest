# AI模倣タイムスタンプ問題 修正レポート

**日付**: 2025-12-22  
**ブランチ**: `fix/model-name-timestamp-debug`  
**ステータス**: ✅ 完了

---

## 問題

AIモデル（Gemini 2.5 Pro / Gemini 3 Flash）が、過去の会話履歴に含まれるタイムスタンプを模倣し、自身の応答の末尾にも同様のフォーマットでタイムスタンプを生成してしまう。

**症状**:
- チャット欄のタイムスタンプが、実際に使用したモデルと異なるモデル名になる
- 例: Gemini 3 Flashで応答しているのに `gemini-2.5-pro` と表示される

**検出ログ例**:
```
Chunk[32]: 我が、愛しき……菓子職人の魔女よ。\n\n2025-12-22 (Mon)
Chunk[33]:  16:32:00 | gemini-2.5-pro
```

## 根本原因

1. AIが過去の会話履歴（タイムスタンプ付き）を学習し、自身の応答にもタイムスタンプを付けるべきだと「推測」
2. 直前の応答のタイムスタンプをそのまま模倣（モデル名も含めて）
3. 従来の「二重防止ロジック」は、AI生成のタイムスタンプを検出すると**システムのタイムスタンプ追加をスキップ**していたため、誤ったモデル名がそのまま残っていた

## 修正内容

### [ui_handlers.py](file:///c:/Users/baken/OneDrive/デスクトップ/gradio_github/gradiotest/ui_handlers.py) (L1115-1138)

**変更前**: タイムスタンプが既に存在すれば追加をスキップ（二重防止）  
**変更後**: AI生成のタイムスタンプを**除去**し、正しいモデル名でシステムタイムスタンプを**追加**

```python
# AI応答末尾のタイムスタンプパターンを検出
existing_timestamp_match = re.search(timestamp_pattern, content_str)
if existing_timestamp_match:
    # AIが模倣したタイムスタンプを検出・除去
    print(f"--- [AI模倣タイムスタンプ除去] ---")
    print(f"  - 除去されたパターン: {existing_timestamp_match.group()}")
    content_str = re.sub(timestamp_pattern, '', content_str)

# システムの正しいタイムスタンプを追加
timestamp = f"\n\n{datetime.datetime.now().strftime('%Y-%m-%d (%a) %H:%M:%S')} | {actual_model_name}"
content_to_log = content_str + timestamp
```

## 検証結果

- Gemini 3 Flash / Gemini 2.5 Pro 両方でテスト
- AI模倣タイムスタンプが除去され、正しいモデル名でシステムタイムスタンプが追加されることを確認
- ターミナルには `[AI模倣タイムスタンプ除去]` ログが表示される

## 教訓

> **AIはコンテキスト内のフォーマットを模倣する傾向がある。**  
> タイムスタンプのような書式情報を含む履歴を送信すると、AIがそれを「出力すべきフォーマット」と解釈し、自身の応答にも付与しようとする場合がある。  
> 対策として「検出→除去→正しい値で追加」のパターンが有効。

## 関連ファイル

- `ui_handlers.py`: `_stream_and_handle_response` 関数内のログ保存処理
- 教訓追記: [gradio_notes.md](file:///c:/Users/baken/OneDrive/デスクトップ/gradio_github/gradiotest/docs/guides/gradio_notes.md)

---

*前回の関連修正: [2025-12-21_model_name_stream_fix_report.md](file:///c:/Users/baken/OneDrive/デスクトップ/gradio_github/gradiotest/docs/reports/2025-12-21_model_name_stream_fix_report.md)*
