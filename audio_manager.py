# audio_manager.py の内容を、このコードで完全に置き換えてください

import os
import uuid
from typing import Optional
import google.genai as genai
from google.genai import types
import traceback

AUDIO_CACHE_DIR = os.path.join("temp", "audio_cache")
os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)

def generate_audio_from_text(text: str, api_key: str, voice_id: str) -> Optional[str]:
    """
    指定されたテキストと声IDを使って音声を生成し、
    一時ファイルとして保存して、そのファイルパスを返す。
    """
    text_to_speak = (text[:250] + '...') if len(text) > 250 else text

    try:
        # ★★★ voice_idは、サポートされているリスト内のものを指定する必要がある ★★★
        print(f"--- 音声生成開始 (Model: models/gemini-2.5-flash-preview-tts, Voice: {voice_id}) ---")

        client = genai.Client(api_key=api_key)
        model_name = "models/gemini-2.5-flash-preview-tts"

        generation_config_object = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice_id
                    )
                )
            )
        )

        response = client.models.generate_content(
            model=model_name,
            contents=[types.Content(parts=[types.Part(text=text_to_speak)])],
            config=generation_config_object
        )

        audio_data = response.candidates[0].content.parts[0].inline_data.data
        if not audio_data:
             print("--- エラー: API応答に音声データが含まれていません ---")
             return None

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
