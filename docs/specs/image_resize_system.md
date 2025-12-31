# 共通画像リサイズ処理の仕様

## 概要

API送信前に画像をリサイズすることで、トークン消費を削減する共通ユーティリティ。

---

## 関数: `utils.resize_image_for_api()`

### シグネチャ

```python
def resize_image_for_api(
    image_source: Union[str, Image.Image], 
    max_size: int = 512,
    return_image: bool = False
) -> Optional[Union[str, Tuple[str, str], Image.Image]]:
```

### 引数

| 引数 | 型 | 説明 |
|------|------|------|
| `image_source` | `str` or `PIL.Image` | 画像ファイルのパス または PIL Imageオブジェクト |
| `max_size` | `int` | 最大辺のピクセル数（デフォルト512） |
| `return_image` | `bool` | `True`: PIL Imageを返す / `False`: Base64文字列を返す |

### 戻り値

| `return_image` | 戻り値 |
|----------------|--------|
| `True` | リサイズ済みのPIL Imageオブジェクト |
| `False` | タプル `(base64_string, format)` （例: `("iVBORw0...", "jpeg")`） |
| 失敗時 | `None` |

---

## 使用箇所

### 1. 情景画像（`ui_handlers.py`のscenery送信部分）
- **max_size**: 512
- 場所の雰囲気を伝えるだけなので低解像度でOK

### 2. ユーザー添付画像（`ui_handlers.py` L1735付近）
- **max_size**: 768
- ユーザーが見せたい詳細がある可能性があるため、少し高めに設定

### 3. トークン計算用（`gemini_api.py` L737付近）
- **max_size**: 768
- `return_image=True`でPIL Imageを取得し、既存のエンコード処理に渡す

---

## 動作仕様

1. **リサイズ判定**: 画像の長辺が`max_size`を超える場合のみリサイズ
2. **アスペクト比**: 維持（`thumbnail`メソッドを使用）
3. **形式維持**: 元のJPEG/PNG形式をそのまま保持
4. **RGBA変換**: RGBA画像はRGBに変換（白背景で合成）
5. **ログ出力**: リサイズ実行時に `[Image Resize] 1024px -> 768px` のログを出力

---

## 注意事項

> [!WARNING]
> **`return_image=False`の戻り値が変更されています**
> 
> 以前: `str`（Base64文字列のみ）
> 現在: `Tuple[str, str]`（Base64文字列とフォーマット名のタプル）
> 
> 呼び出し側で `encoded_string, output_format = resize_result` のようにアンパックが必要です。

> [!NOTE]
> **768pxの根拠**
> - Geminiの推奨画像サイズは512~1024px
> - 768pxは詳細認識とコストのバランスが良い
> - 必要に応じて調整可能（将来的にユーザー設定化も検討）

---

## 関連ファイル

| ファイル | 変更内容 |
|----------|----------|
| [utils.py](file:///c:/Users/baken/OneDrive/デスクトップ/gradio_github/gradiotest/utils.py) | `resize_image_for_api`関数の定義 |
| [ui_handlers.py](file:///c:/Users/baken/OneDrive/デスクトップ/gradio_github/gradiotest/ui_handlers.py) | ユーザー添付画像・情景画像のリサイズ適用 |
| [gemini_api.py](file:///c:/Users/baken/OneDrive/デスクトップ/gradio_github/gradiotest/gemini_api.py) | トークン計算用のリサイズ適用 |

---

*作成日: 2025-12-31*
