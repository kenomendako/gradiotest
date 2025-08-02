# audio_manager.py の内容を、このコードで完全に置き換えてください

import os
import uuid
from typing import Optional
import google.generativeai as genai
# 'types' はこの実装では不要になるため削除します

# 生成された音声ファイル（MP3）を一時的に保存するディレクトリ
AUDIO_CACHE_DIR = os.path.join("temp", "audio_cache")
os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)

def generate_audio_from_text(text: str, api_key: str, voice_id: str) -> Optional[str]:
    """
    指定されたテキストと声IDを使って音声を生成し、
    一時ファイルとして保存して、そのファイルパスを返す。
    【公式Colab準拠版】
    """
    # 安全のため、長すぎるテキストは250文字に丸める
    text_to_speak = (text[:250] + '...') if len(text) > 250 else text

    try:
        print(f"--- 音声生成開始 (Voice: {voice_id}) ---")

        # ★★★ ここからが公式Colabに準拠した、真の修正箇所です ★★★

        # 1. APIキーを設定
        genai.configure(api_key=api_key)

        # 2. 音声生成専用のモデルを'GenerativeModel'として初期化
        model = genai.GenerativeModel('models/text-to-speech-1')

        # 3. 'generate_content'メソッドを呼び出し、configで音声設定を渡す
        response = model.generate_content(
            text_to_speak,
            generation_config={
                "response_mime_type": "audio/mp3",
                "tts_voice": voice_id
            }
        )

        # 4. 正しい応答オブジェクトから音声データを取得
        if not response.candidates[0].content.parts[0].inline_data.data:
             print("--- エラー: API応答に音声データが含まれていません ---")
             return None

        audio_data = response.candidates[0].content.parts[0].inline_data.data

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
        traceback.print_exc() # より詳細なエラー情報をターミナルに出力
        return None
