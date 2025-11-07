# tools/image_tools.py

import os
import io
import datetime
import traceback
from PIL import Image
import google.genai as genai
import httpx
from langchain_core.tools import tool
from google.genai import types
import config_manager 

# IMAGE_GEN_MODEL = "gemini-2.5-flash-image" # 定数は廃止。モードに応じて動的に選択します。

@tool
def generate_image(prompt: str, room_name: str, api_key: str, api_key_name: str = None) -> str:
    """
    ユーザーの要望や会話の文脈に応じて、情景、キャラクター、アイテムなどのイラストを生成する。
    成功した場合は、UIに表示するための特別な画像タグを返す。
    prompt: 画像生成のための詳細な指示（英語が望ましい）。
    """
    # --- Just-In-Time: 常に最新の設定をファイルから読み込む ---
    latest_config = config_manager.load_config_file()
    image_gen_mode = latest_config.get("image_generation_mode", "new")
    paid_key_names = latest_config.get("paid_api_key_names", [])

    # 二重防御: 新モデルが選択されている場合は、api_key_name が有料キーとして登録されているか確認する
    if image_gen_mode == "new" and (not api_key_name or api_key_name not in paid_key_names):
        return f"【エラー】画像生成(新モデル)には有料プランのAPIキーが必要です。選択中のキー「{api_key_name}」は有料プランとして登録されていません。"

    if image_gen_mode == "new":
        model_to_use = "gemini-2.5-flash-image"
    elif image_gen_mode == "old":
        model_to_use = "gemini-2.0-flash-preview-image-generation"
    else: # disabled or invalid
        return "【エラー】画像生成機能は現在、設定で無効化されています。"

    print(f"--- 画像生成ツール実行 (Model: {model_to_use}, Prompt: '{prompt[:100]}...') ---")
    if not room_name or not api_key:
        return "【エラー】画像生成にはルーム名とAPIキーが必須です。"

    try:
        save_dir = os.path.join("characters", room_name, "generated_images")
        os.makedirs(save_dir, exist_ok=True)

        client = genai.Client(api_key=api_key)

        # 新旧モデルでAPI呼び出しを分岐
        if image_gen_mode == "old":
            # 旧モデル用の呼び出し
            generation_config = types.GenerateContentConfig(
                response_modalities=['IMAGE', 'TEXT']
            )
            response = client.models.generate_content(
                model=model_to_use,
                contents=prompt,
                config=generation_config
            )
        else: # "new" model
            # 新モデル用の呼び出し（特別なconfigは一切不要な、シンプルな形式）
            response = client.models.generate_content(
                model=model_to_use,
                contents=prompt,
            )
    
        # --- レスポンス処理 (共通化) ---
        image_data = None
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.text:
                    print(f"  - APIからのテキスト応答: {part.text}")
                if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                    image_data = io.BytesIO(part.inline_data.data)
                    break

        if not image_data:
            return "【エラー】APIから画像データが返されませんでした。プロンプトが不適切か、安全フィルターにブロックされた可能性があります。"

        image = Image.open(image_data)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{room_name.lower()}_{timestamp}.png"
        save_path = os.path.join(save_dir, filename)

        image.save(save_path, "PNG")
        print(f"  - 画像を保存しました: {save_path}")

        return f"[Generated Image: {save_path}]\nSuccess: 画像が生成され、指定されたパスに保存されました。**このタスクは完了です。これから絵を描くといった前置きは不要です。**この画像タグ `[Generated Image: {save_path}]` を使って、生成された画像をユーザーに提示し、コメントを添えてください。"

    except httpx.RemoteProtocolError as e:
        print(f"  - 画像生成ツールでサーバー切断エラー: {e}")
        return "【エラー】Googleのサーバーが応答せずに接続を切断しました。プロンプトが複雑すぎるか、サーバーが一時的に不安定な可能性があります。プロンプトを簡潔にして、もう一度試してみてください。"
    except genai.errors.ServerError as e:
        print(f"  - 画像生成ツールでサーバーエラー(500番台): {e}")
        return "【エラー】Googleのサーバー側で内部エラー(500)が発生しました。プロンプトが安全フィルターに抵触したか、一時的な問題の可能性があります。プロンプトをよりシンプルにして、もう一度試してみてください。"
    except genai.errors.ClientError as e:
        print(f"  - 画像生成ツールでクライアントエラー(400番台): {e}")
        return f"【エラー】APIリクエストが無効です(400番台)。詳細: {e}"
    except Exception as e:
        print(f"  - 画像生成ツールで予期せぬエラー: {e}")
        traceback.print_exc()
        return f"【エラー】画像生成中に予期せぬ問題が発生しました。詳細: {e}"