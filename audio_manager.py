# audio_manager.py の内容を、このコードで完全に置き換えてください

import os
import uuid
from typing import Optional
import google.genai as genai
from google.genai import types
import traceback
import wave # ★★★ 全ての答えであった、waveライブラリをインポート ★★★

AUDIO_CACHE_DIR = os.path.join("temp", "audio_cache")
os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)

def generate_audio_from_text(text: str, api_key: str, voice_id: str) -> Optional[str]:
    """
    指定されたテキストと声IDを使って音声を生成し、
    再生可能なWAVファイルとして保存して、そのファイルパスを返す。
    【ファイル破損問題解決・真の最終確定版】
    """
    text_to_speak = (text[:250] + '...') if len(text) > 250 else text

    try:
        print(f"--- 音声生成開始 (Voice: {voice_id}) ---")

        client = genai.Client(api_key=api_key)
        model_name = "models/gemini-2.5-flash-preview-tts"

        # configオブジェクトの構造は、前回のもので正しかった
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

        # ★★★ ここからが、ファイル破損を解決する、真の修正箇所です ★★★
        # 1. ファイル名を .wav に変更
        filename = f"{uuid.uuid4()}.wav"
        filepath = os.path.join(AUDIO_CACHE_DIR, filename)

        # 2. waveライブラリを使い、正しいWAVファイルとして書き込む
        with wave.open(filepath, "wb") as wf:
            wf.setnchannels(1)       # モノラル
            wf.setsampwidth(2)       # 16-bit
            wf.setframerate(24000)   # サンプリングレート (モデルの仕様)
            wf.writeframes(audio_data)
        # ★★★ 修正箇所ここまで ★★★

        print(f"  - 音声ファイル(WAV)を生成しました: {filepath}")
        return filepath

    except Exception as e:
        print(f"--- 音声生成中にエラーが発生しました: {e} ---")
        traceback.print_exc()
        return None
