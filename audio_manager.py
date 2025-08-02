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
    【プロジェクト規律準拠・最終確定版】
    """
    # 安全のため、長すぎるテキストは250文字に丸める
    text_to_speak = (text[:250] + '...') if len(text) > 250 else text

    try:
        print(f"--- 音声生成開始 (Voice: {voice_id}) ---")

        # プロジェクトの作法通り、Clientオブジェクトを初期化
        client = genai.Client(api_key=api_key)

        # ★★★ ここからがプロジェクトの作法に則った、真の修正箇所です ★★★

        # 1. 音声生成用のモデル名を指定。
        #    'text-to-speech-1' は別系統のAPI呼び出しを要求するため、
        #    Client経由で呼び出せるプレビュー版の 'gemini-2.5-flash-preview-tts' を使用します。
        model_name = "models/gemini-2.5-flash-preview-tts"

        # 2. 公式ドキュメントに準拠した、正しい設定オブジェクトを構築
        generation_config = types.GenerationConfig(
            response_mime_type="audio/mpeg", # mp3形式を指定
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    voice=voice_id # 正しいパラメータ名は 'voice'
                )
            )
        )

        # 3. プロジェクトの標準的なAPI呼び出しパターンを使用
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

        # 4. 正しい応答の階層から音声データを取得
        audio_part = response.candidates[0].content.parts[0]
        if not audio_part.inline_data or not audio_part.inline_data.data:
             print("--- エラー: API応答に音声データが含まれていません ---")
             return None

        audio_data = audio_part.inline_data.data
        # ★★★ 修正箇所ここまで ★★★

        # ユニークなファイル名を生成して、MP3として保存
        filename = f"{uuid.uuid4()}.mp3"
        filepath = os.path.join(AUDIO_CACHE_DIR, filename)

        with open(filepath, "wb") as f:
            f.write(audio_data)

        print(f"  - 音声ファイルを生成しました: {filepath}")
        return filepath

    except Exception as e:
        print(f"--- 音声生成中にエラーが発生しました: {e} ---")
        import traceback
        traceback.print_exc()
        return None
