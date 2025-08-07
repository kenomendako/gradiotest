# audio_manager.py の内容を、このコードで完全に置き換えてください

import os
import uuid
from typing import Optional
import google.genai as genai
from google.genai import types
import traceback
import wave

AUDIO_CACHE_DIR = os.path.join("temp", "audio_cache")
os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)
# ★★★ テキスト長の制限を大幅に緩和 ★★★
MAX_TEXT_LENGTH = 8000

def generate_audio_from_text(text: str, api_key: str, voice_id: str, style_prompt: str = None) -> Optional[str]:
    """
    指定されたテキストと声ID、スタイルプロンプトを使って音声を生成し、
    再生可能なWAVファイルとして保存して、そのファイルパスを返す。
    【v3: 堅牢化対応版】
    """
    if len(text) > MAX_TEXT_LENGTH:
        text_to_speak = text[:MAX_TEXT_LENGTH] + "..."
        print(f"  - 警告: テキストが長すぎるため、{MAX_TEXT_LENGTH}文字に切り詰めました。")
    else:
        text_to_speak = text

    final_prompt = f"{style_prompt.strip()}: {text_to_speak}" if style_prompt and style_prompt.strip() else text_to_speak

    try:
        print(f"--- 音声生成開始 (Voice: {voice_id}) ---")
        print(f"  - 最終プロンプト: {final_prompt[:100]}...")

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
            contents=[types.Content(parts=[types.Part(text=final_prompt)])],
            config=generation_config_object
        )

        # ▼▼▼ 修正の核心：API応答を慎重にチェックする ▼▼▼
        if (response and response.candidates and
            response.candidates[0].content and
            response.candidates[0].content.parts and
            response.candidates[0].content.parts[0].inline_data):

            audio_data = response.candidates[0].content.parts[0].inline_data.data
            if not audio_data:
                print("--- エラー: API応答のインラインデータが空です ---")
                return None
        else:
            # 応答が期待通りでない場合、デバッグ情報を出力して安全に終了
            print("--- エラー: API応答に予期した音声データが含まれていませんでした。セーフティフィルターによるブロックの可能性があります。 ---")
            if response and response.candidates:
                candidate = response.candidates[0]
                finish_reason = candidate.finish_reason.name if hasattr(candidate, 'finish_reason') and hasattr(candidate.finish_reason, 'name') else '不明'
                safety_ratings = candidate.safety_ratings if hasattr(candidate, 'safety_ratings') else '取得不能'
                print(f"  - 終了理由: {finish_reason}")
                print(f"  - 安全性評価: {safety_ratings}")
            return None
        # ▲▲▲ 修正ここまで ▲▲▲

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
        print(f"--- 音声生成中に予期せぬエラーが発生しました: {e} ---")
        traceback.print_exc()
        return None
