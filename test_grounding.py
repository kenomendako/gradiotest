# -*- coding: utf-8 -*-
import sys
import os

# Add the parent directory to sys.path to allow imports from other modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gemini_api import send_to_gemini, configure_google_api
from character_manager import get_character_files_paths, ensure_character_files # Renamed function
from config_manager import load_config, API_KEYS

def run_grounding_test():
    # Load config to check API Keys
    load_config()
    api_key_name = "your_key_name_1"

    if api_key_name not in API_KEYS or API_KEYS[api_key_name] == "YOUR_API_KEY_HERE":
        print(f"エラー: APIキー '{api_key_name}' が config.json に設定されていないか、プレースホルダーのままです。")
        print("テストを実行する前に、有効なAPIキーを設定してください。")
        return

    # Configure API
    configured, error_msg = configure_google_api(api_key_name)
    if not configured:
        print(f"API設定エラー: {error_msg}")
        return

    character_name = "Default"
    # Ensure character files exist, especially for a clean environment
    try:
        if not ensure_character_files(character_name): # Use renamed function and check return
            print(f"キャラクター '{character_name}' のファイル準備に失敗しました。")
            return
        print(f"キャラクター '{character_name}' のファイルを確認/作成しました。")
    except Exception as e:
        print(f"キャラクターファイル準備中にエラー: {e}")
        return

    # In get_character_files_paths, system_prompt is the second arg, log_file is the first.
    log_file_path, system_prompt_path, _, memory_json_path = get_character_files_paths(character_name)

    print(f"システムプロンプトパス: {system_prompt_path}")
    print(f"ログファイルパス: {log_file_path}")
    print(f"メモリJSONパス: {memory_json_path}")


    # Call send_to_gemini
    print("send_to_gemini を呼び出します...")
    response, _ = send_to_gemini(
        system_prompt_path=system_prompt_path,
        log_file_path=log_file_path,
        user_prompt="TEST_GROUNDING_PROMPT_2.5", # New specific prompt for 2.5 testing
        selected_model="gemini-2.5-flash-preview-05-20", # New 2.5 model
        character_name=character_name,
        send_thoughts_to_api=False,
        api_history_limit_option="10",
        image_path=None,
        memory_json_path=memory_json_path
    )

    if isinstance(response, str) and response.startswith("エラー:") :
        print(f"Gemini API呼び出しでエラーが発生しました: {response}")
        return

    # Check for grounding_metadata
    if hasattr(response, 'grounding_metadata'):
        print("grounding_metadata 属性が存在します。")
        if response.grounding_metadata:
            print(f"grounding_metadata の内容: {response.grounding_metadata}")
            if response.grounding_metadata.web_search_queries:
                 print(f"Web search queries: {response.grounding_metadata.web_search_queries}")
            else:
                print("Web search queries は空です。")
            if hasattr(response.grounding_metadata, 'retrieval_queries') and response.grounding_metadata.retrieval_queries: # Gemini 1.5 Pro API change
                print(f"Retrieval queries: {response.grounding_metadata.retrieval_queries}")

        else:
            print("grounding_metadata は存在しますが、空です (None または falsy)。")
    else:
        print("grounding_metadata 属性は存在しません。")
        print(f"受信したレスポンスの型: {type(response)}")
        if hasattr(response, 'text'):
            print(f"レスポンスのテキスト内容: {response.text[:200]}...") # Print first 200 chars
        else:
            print(f"レスポンスオブジェクトの内容: {response}")


if __name__ == "__main__":
    run_grounding_test()
