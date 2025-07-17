# tools/image_tools.py

import os
import io
import datetime
import traceback
from PIL import Image
import google.genai as genai
from langchain_core.tools import tool

# ★★★ 正しい画像生成モデルに修正 ★★★
IMAGE_GEN_MODEL = "gemini-2.0-flash-preview-image-generation"

@tool
def generate_image(prompt: str, character_name: str, api_key: str) -> str:
    """
    ユーザーの要望や会話の文脈に応じて、情景、キャラクター、アイテムなどのイラストを生成する。
    成功した場合は、UIに表示するための特別な画像タグを返す。
    prompt: 画像生成のための詳細な指示（英語が望ましい）。
    """
    print(f"--- 画像生成ツール実行 (Model: {IMAGE_GEN_MODEL}, Prompt: '{prompt}') ---")
    if not character_name or not api_key:
        return "【エラー】画像生成にはキャラクター名とAPIキーが必須です。"

    try:
        # 画像保存ディレクトリのパスを準備
        save_dir = os.path.join("characters", character_name, "generated_images")
        os.makedirs(save_dir, exist_ok=True)

        # Geminiクライアントを初期化
        client = genai.Client(api_key=api_key)

        # 画像生成APIを呼び出す
        response = client.models.generate_content(
            model=IMAGE_GEN_MODEL,
            contents=prompt,
        )

        # 応答から画像データを抽出
        image_data = None
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.mime_type.startswith("image/"):
                    image_data = io.BytesIO(part.data)
                    break

        if not image_data:
            return "【エラー】APIから画像データが返されませんでした。プロンプトが不適切か、安全フィルターにブロックされた可能性があります。"

        # 画像をファイルとして保存
        image = Image.open(image_data)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{character_name.lower()}_{timestamp}.png"
        save_path = os.path.join(save_dir, filename)

        image.save(save_path, "PNG")
        print(f"  - 画像を保存しました: {save_path}")

        # UIで解釈可能なタグを返す
        return f"[Generated Image: {save_path}]"

    except Exception as e:
        print(f"  - 画像生成ツールでエラー: {e}")
        traceback.print_exc()
        return f"[エラー：画像生成中に予期せぬ問題が発生しました。詳細: {e}]"
