# audio_manager.py (真の確定版)

import os
import uuid
from typing import Optional
import google.genai as genai
from google.genai import types

# 生成された音声ファイル（MP3）を一時的に保存するディレクトリ
AUDIO_CACHE_DIR = os.path.join("temp", "audio_cache")
os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)

def generate_audio_from_text(text: str, api_key: str, voice_id: str) -> Optional[str]:
    """
    指定されたテキストと声IDを使って音声を生成し、
    一時ファイルとして保存して、そのファイルパスを返す。
    公式サンプルコードに準拠した generate_content 方式を使用。
    """
    # 安全のため、長すぎるテキストは250文字に丸める
    text_to_speak = (text[:250] + '...') if len(text) > 250 else text

    try:
        print(f"--- 音声生成開始 (Voice: {voice_id}) ---")

        # プロジェクト標準の作法でクライアントを初期化
        client = genai.Client(api_key=api_key)

        # ★★★ 公式サンプルコードに準拠したAPI呼び出し ★★★
        response = client.models.generate_content(
            model="models/gemini-2.5-flash-preview-tts", # 正しいモデル名
            contents=[
                types.Content(
                    parts=[
                        types.Part(text=text_to_speak),
                    ]
                )
            ],
            generation_config=types.GenerationConfig(
                response_mime_type="audio/mpeg",
                tts_voice=voice_id
            )
        )

        # ★★★ 公式サンプルコードに準拠した応答の解析 ★★★
        audio_part = response.candidates[0].content.parts[0]
        if not audio_part.inline_data or not audio_part.inline_data.data:
             print("--- エラー: API応答に音声データが含まれていません ---")
             return None

        # ユニークなファイル名を生成して、MP3として保存
        filename = f"{uuid.uuid4()}.mp3"
        filepath = os.path.join(AUDIO_CACHE_DIR, filename)

        with open(filepath, "wb") as f:
            f.write(audio_part.inline_data.data)

        print(f"  - 音声ファイルを生成しました: {filepath}")
        return filepath

    except Exception as e:
        print(f"--- 音声生成中にエラーが発生しました: {e} ---")
        return None
