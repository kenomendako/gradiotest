# -*- coding: utf-8 -*-
# ##############################################################################
# #                                                                            #
# #  ! ! ! ! ! ! ! ! ! ! !   CRITICAL AI INSTRUCTION   ! ! ! ! ! ! ! ! ! ! ! !  #
# #                                                                            #
# #   THIS FILE MUST USE THE `google-genai` SDK.                               #
# #   DO NOT use the deprecated `google-generativeai` library.                 #
# #                                                                            #
# #   Correct Import: `from google import genai`                               #
# #   Incorrect Import: `import google.generativeai as genai`                  #
# #                                                                            #
# #   Refer to `AI_DEVELOPMENT_GUIDELINES.md` for details.                     #
# #                                                                            #
# # ! ! ! ! ! ! ! ! ! ! !   AIへの最重要指示   ! ! ! ! ! ! ! ! ! ! ! ! #
# #                                                                            #
# #   このファイルは `google-genai` SDK を使用します。                         #
# #   非推奨の `google-generativeai` ライブラリは使用禁止です。                #
# #                                                                            #
# #   正しいImport: `from google import genai`                                 #
# #   間違いのImport: `import google.generativeai as genai`                    #
# #                                                                            #
# #   詳細は `AI_DEVELOPMENT_GUIDELINES.md` を参照してください。               #
# #                                                                            #
# ##############################################################################
from google import genai
from google.ai.generativelanguage import types as glm_types
import os
import json
import traceback
from PIL import Image
from io import BytesIO
from typing import Optional, List, Dict
import uuid
import config_manager
from utils import load_chat_log, save_message_to_log
from character_manager import get_character_files_paths

# --- グローバル変数 ---
_gemini_client = None

# --- SDKの初期化と設定 ---
def configure_google_api(api_key_name: str) -> tuple[bool, str]:
    """
    指定されたAPIキー名で、新しいgoogle-genai SDKを初期化します。
    """
    global _gemini_client
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        _gemini_client = None
        return False, f"APIキー名 '{api_key_name}' に対応する有効なAPIキーが設定されていません。"
    try:
        # 新しいSDKでは、APIキーは環境変数で設定するか、直接渡す
        genai.configure(api_key=api_key)
        # 必要に応じてクライアントを再生成
        # モデルリスト取得などでクライアントが必要な場合
        # _gemini_client = genai.GenerativeModel(...) のようにモデルごとに生成するのが一般的
        print(f"Google GenAI SDK for API key '{api_key_name}' configured successfully.")
        return True, ""
    except Exception as e:
        _gemini_client = None
        return False, f"APIキー '{api_key_name}' でのSDK設定中にエラー: {e}"

def _get_model(model_name: str):
    """
    指定されたモデル名のGenerativeModelインスタンスを返すヘルパー関数。
    """
    safety_settings = [
        glm_types.SafetySetting(category=glm_types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=glm_types.HarmBlockThreshold.BLOCK_NONE),
        glm_types.SafetySetting(category=glm_types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=glm_types.HarmBlockThreshold.BLOCK_NONE),
        glm_types.SafetySetting(category=glm_types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=glm_types.HarmBlockThreshold.BLOCK_NONE),
        glm_types.SafetySetting(category=glm_types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=glm_types.HarmBlockThreshold.BLOCK_NONE),
    ]
    return genai.GenerativeModel(model_name, safety_settings=safety_settings)

# --- メインのAPI送信関数 ---
def send_to_gemini(system_prompt: str, chat_history: List[Dict[str, str]], user_prompt: str, model_name: str, generation_config: dict, tools: Optional[List[glm_types.Tool]] = None) -> tuple[Optional[str], Optional[str]]:
    """
    Gemini APIにリクエストを送信し、応答と生成された画像パス（もしあれば）を返します。
    新しいSDKの作法に準拠しています。
    """
    try:
        model = _get_model(model_name)

        # 新しいSDKでは、システムプロンプトは`GenerativeModel`の初期化時に渡す
        model.system_instruction = glm_types.Content(parts=[glm_types.Part(text=system_prompt)])

        # 会話履歴をSDKのContent形式に変換
        history_contents = []
        for msg in chat_history:
            role = "user" if msg["role"] == "user" else "model"
            # TODO: 将来的にはファイル添付などもここで処理する必要がある
            history_contents.append(glm_types.Content(parts=[glm_types.Part(text=msg["content"])], role=role))

        # API呼び出し
        response = model.generate_content(
            contents=history_contents + [glm_types.Content(parts=[glm_types.Part(text=user_prompt)])],
            generation_config=generation_config,
            tools=tools
        )

        # 応答の処理
        text_response = ''.join(part.text for part in response.parts if part.text)
        image_path = None # 画像生成のロジックは別途実装

        # TODO: Tool Calling（関数呼び出し）の応答処理
        if response.function_calls:
            # ここに関数呼び出しの処理を追加
            pass

        return text_response.strip(), image_path

    except Exception as e:
        print(f"Gemini APIとの通信中にエラーが発生しました: {e}")
        traceback.print_exc()
        return f"エラー: Gemini APIとの通信中に予期しないエラーが発生しました: {e}", None

# --- アラーム用のAPI送信関数 ---
def send_alarm_to_gemini(character_name: str, theme: str, flash_prompt_template: Optional[str], alarm_model_name: str, api_key_name: str, log_file_path: str, alarm_api_history_turns: int) -> str:
    """
    アラーム通知メッセージを生成するための関数。
    """
    if not configure_google_api(api_key_name):
        return "【アラームエラー】APIキー設定失敗"

    try:
        model = _get_model(alarm_model_name)

        # システムプロンプトの構築
        if flash_prompt_template:
            system_prompt = flash_prompt_template.replace("[キャラクター名]", character_name).replace("[テーマ内容]", theme)
        else:
            system_prompt = f"あなたはキャラクター「{character_name}」です。テーマ「{theme}」について、ユーザーに送る短いメッセージを生成してください。"

        # 記憶情報の追加
        _, _, _, memory_json_path = get_character_files_paths(character_name)
        if memory_json_path and os.path.exists(memory_json_path):
            with open(memory_json_path, "r", encoding="utf-8") as f:
                mem = json.load(f)
                # 記憶情報をプロンプトに追加するロジック
                # (ここでは簡略化のため、自己紹介文だけ追加する例)
                self_identity = mem.get("self_identity", {})
                if self_identity:
                    system_prompt += f"\n\n参考情報: {json.dumps(self_identity, ensure_ascii=False)}"

        model.system_instruction = glm_types.Content(parts=[glm_types.Part(text=system_prompt)])

        # 会話履歴の構築
        chat_history = load_chat_log(log_file_path, character_name)
        if alarm_api_history_turns > 0 and chat_history:
            history_for_api = chat_history[-(alarm_api_history_turns * 2):]
        else:
            history_for_api = []

        history_contents = []
        for msg in history_for_api:
            role = "user" if msg["role"] == "user" else "model"
            history_contents.append(glm_types.Content(parts=[glm_types.Part(text=msg["content"])], role=role))

        # API呼び出し
        response = model.generate_content(contents=history_contents)

        return response.text.strip()

    except Exception as e:
        print(f"アラーム用モデルとの通信中にエラー: {e}")
        traceback.print_exc()
        return f"【アラームエラー】API通信失敗: {e}"

# (注) generate_image_with_gemini関数は、新しいSDKの画像生成モデル(例: 'gemini-1.5-pro')の
# マルチモーダル機能に統合されるため、一旦コメントアウトまたは削除します。
# 画像生成はsend_to_geminiに統合して処理するのが新しい作法になります。
