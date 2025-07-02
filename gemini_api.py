import google.genai as genai
from google.ai.generativelanguage import Content, Part # type: ignore
import os
import json
import traceback
from typing import Optional, List
from PIL import Image

import config_manager
from utils import save_message_to_log, load_chat_log
from character_manager import get_character_files_paths

# グローバルなクライアントやセッション管理は、Gradioのプロセス分離と相性が悪いため廃止
# _chat_sessions = {}

def send_multimodal_to_gemini(character_name: str, model_name: str, parts: list, api_history_limit_option: str):
    """
    テキストと画像のリストを受け取り、Geminiに送信する。
    APIキーは環境変数から自動的に読み込まれることを前提とする。
    """
    try:
        # モデルを動的に指定してGenerativeModelインスタンスを取得
        # この時点で、os.environ['GOOGLE_API_KEY']が自動的に使われる
        model_to_use = genai.GenerativeModel(model_name)

        # --- 履歴の準備 ---
        log_file, sys_prompt_file, _, _ = get_character_files_paths(character_name)

        history = load_chat_log(log_file, character_name) # load_chat_logはDictのリストを返す

        # LangChainの'ai'/'assistant'ロールをGeminiの'model'ロールに変換する処理をここに入れる
        formatted_history_for_sdk = []
        for msg_dict in history:
            role = msg_dict.get("role", "user")
            if role.lower() in ["ai", "assistant", "model"]:
                role = "model"
            else:
                role = "user"

            text_content = msg_dict.get("content", "")
            if text_content: # コンテンツが空でない場合のみ追加
                formatted_history_for_sdk.append(Content(role=role, parts=[Part(text=text_content)]))

        if api_history_limit_option.isdigit():
            limit = int(api_history_limit_option)
            if len(formatted_history_for_sdk) > limit * 2: # 往復なので *2
                formatted_history_for_sdk = formatted_history_for_sdk[-(limit*2):]

        # --- システムプロンプトと最新のプロンプトを結合 ---
        system_instruction = ""
        if sys_prompt_file and os.path.exists(sys_prompt_file):
            with open(sys_prompt_file, 'r', encoding='utf-8') as f:
                system_instruction = f.read().strip() # strip() を追加

        # generate_contentに渡す最終的なリストを作成
        final_contents = []

        # システムプロンプトを履歴の先頭に追加 (generate_contentの場合)
        if system_instruction:
            final_contents.append(Content(role='user', parts=[Part(text=system_instruction)]))
            final_contents.append(Content(role='model', parts=[Part(text="承知いたしました。")])) # AIの応答を模倣

        final_contents.extend(formatted_history_for_sdk)

        # 現在のユーザー入力をpartsに変換して追加
        # parts はテキスト(str)とPIL.Imageの混在リストなので、適切にSDKのPartオブジェクトに変換する
        current_input_sdk_parts = []
        for p_item in parts:
            if isinstance(p_item, str):
                current_input_sdk_parts.append(Part(text=p_item))
            elif isinstance(p_item, Image.Image):
                current_input_sdk_parts.append(p_item)
            else:
                print(f"警告: 不明な型のパーツが含まれています: {type(p_item)}")

        if not current_input_sdk_parts:
             # UI側でチェックしているので基本ここには来ないはずだが念のため
             return "エラー: ユーザーからの入力コンテンツがありません。", None

        final_contents.append(Content(role='user', parts=current_input_sdk_parts))

        # 履歴を管理するChatSessionを使わず、毎回完全なコンテキストを渡す
        response = model_to_use.generate_content(final_contents)

        return response.text, None

    except Exception as e:
        traceback.print_exc()
        # エラーメッセージに、どのモデルで問題が起きたかを含めると、デバッグが容易になる
        return f"エラー: モデル '{model_name}' との通信中に予期しないエラーが発生しました: {e}", None
