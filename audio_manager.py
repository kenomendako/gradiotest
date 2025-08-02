# audio_manager.py の内容を、このコードで完全に置き換えてください

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
    """
    # 安全のため、長すぎるテキストは250文字に丸める
    text_to_speak = (text[:250] + '...') if len(text) > 250 else text

    try:
        print(f"--- 音声生成開始 (Voice: {voice_id}) ---")

        client = genai.Client(api_key=api_key)

        # ★★★ ここからが修正箇所 ★★★
        # tts_voice を GenerationConfig の外に出し、
        # 正しいモデル名 ('text-to-speech-1') と共に、
        # 正しいメソッド (generate_speech_content) を呼び出すように変更します。
        # このモデルは音声生成に特化しており、より安定しています。
        response = client.generate_speech_content(
            model="models/text-to-speech-1",
            content=text_to_speak,
            voice=voice_id,
            # 必要に応じて他のオプションも追加可能
            # output_format="mp3" # デフォルトはMP3
        )
        # ★★★ 修正箇所ここまで ★★★

        if not response.audio_data:
             print("--- エラー: API応答に音声データが含まれていません ---")
             return None

        # ユニークなファイル名を生成して、MP3として保存
        filename = f"{uuid.uuid4()}.mp3"
        filepath = os.path.join(AUDIO_CACHE_DIR, filename)

        with open(filepath, "wb") as f:
            f.write(response.audio_data)

        print(f"  - 音声ファイルを生成しました: {filepath}")
        return filepath

    except Exception as e:
        print(f"--- 音声生成中にエラーが発生しました: {e} ---")
        return None
