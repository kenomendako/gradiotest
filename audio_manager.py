# audio_manager.py の内容を、このコードで完全に置き換えてください

import os
import uuid
from typing import Optional
import google.genai as genai
from google.genai import types
import traceback

# 生成された音声ファイル（MP3）を一時的に保存するディレクトリ
AUDIO_CACHE_DIR = os.path.join("temp", "audio_cache")
os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)

def generate_audio_from_text(text: str, api_key: str, voice_id: str) -> Optional[str]:
    """
    指定されたテキストと声IDを使って音声を生成し、
    一時ファイルとして保存して、そのファイルパスを返す。
    【公式サンプル準拠・最終確定版】
    """
    # 安全のため、長すぎるテキストは250文字に丸める
    text_to_speak = (text[:250] + '...') if len(text) > 250 else text

    try:
        print(f"--- 音声生成開始 (Voice: {voice_id}) ---")

        client = genai.Client(api_key=api_key)
        # Client経由で呼び出せるプレビューモデルを指定
        model_name = "models/gemini-2.5-flash-preview-tts"

        # ★★★ ここが公式サンプルに準拠した、真の修正箇所です ★★★
        generation_config = types.GenerationConfig(
            response_mime_type="audio/mpeg", # mp3形式を要求
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    # 正しい構造: VoiceConfig -> prebuilt_voice_config -> PrebuiltVoiceConfig
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        # 正しいパラメータ名は 'voice_name'
                        voice_name=voice_id
                    )
                )
            )
        )
        # ★★★ 修正箇所ここまで ★★★

        response = client.models.generate_content(
            model=model_name,
            contents=[
                types.Content(
                    parts=[
                        types.Part(text=text_to_speak),
                    ]
                )
            ],
            generation_config=generation_config
        )

        audio_part = response.candidates[0].content.parts[0]
        if not audio_part.inline_data or not audio_part.inline_data.data:
             print("--- エラー: API応答に音声データが含まれていません ---")
             return None

        audio_data = audio_part.inline_data.data

        filename = f"{uuid.uuid4()}.mp3"
        filepath = os.path.join(AUDIO_CACHE_DIR, filename)

        with open(filepath, "wb") as f:
            f.write(audio_data)

        print(f"  - 音声ファイルを生成しました: {filepath}")
        return filepath

    except Exception as e:
        print(f"--- 音声生成中にエラーが発生しました: {e} ---")
        traceback.print_exc()
        return None
