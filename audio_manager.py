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

def generate_audio_from_text(text: str, api_key: str, voice_id: str, tone_prompt: Optional[str] = None) -> Optional[str]:
    """
    【トーン制御・文字数緩和版】
    指定されたテキスト、声ID、トーン指示を使って音声を生成し、
    再生可能なWAVファイルとして保存して、そのファイルパスを返す。
    """
    # ★★★ 文字数制限を大幅に緩和 ★★★
    # 念のため、極端に長いテキストを防ぐ上限は設ける
    MAX_CHARS = 8000
    text_to_speak = (text[:MAX_CHARS] + '...') if len(text) > MAX_CHARS else text

    try:
        print(f"--- 音声生成開始 (Voice: {voice_id}) ---")
        if tone_prompt and tone_prompt != "（デフォルトのトーン）":
            print(f"  - トーン指示: {tone_prompt}")
            # ★★★ トーン指示をテキストの前に付与 ★★★
            contents = [
                types.Part(text=tone_prompt),
                types.Part(text=text_to_speak)
            ]
        else:
            contents = [types.Part(text=text_to_speak)]

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
            contents=contents, # ★★★ 変更点 ★★★
            config=generation_config_object
        )

        audio_data = response.candidates[0].content.parts[0].inline_data.data
        if not audio_data:
             print("--- エラー: API応答に音声データが含まれていません ---")
             return None

        filename = f"{uuid.uuid4()}.wav"
        filepath = os.path.join(AUDIO_CACHE_DIR, filename)

        with wave.open(filepath, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(audio_data)

        print(f"  - 音声ファイル(WAV)を生成しました: {filepath}")
        return filepath

    except Exception as e:
        print(f"--- 音声生成中にエラーが発生しました: {e} ---")
        traceback.print_exc()
        return None
