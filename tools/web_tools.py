# tools/web_tools.py (v4.0 - Project Genesis Aligned)

from langchain_core.tools import tool
import google.genai as genai
from google.genai import types
import traceback
import config_manager

@tool
def web_search_tool(query: str, room_name: str) -> str:
    """
    ユーザーからのクエリに基づいて、最新の情報を得るためにGoogle検索を実行します。
    このツールは、Geminiモデル自身の思考プロセスに、Google検索の結果を直接統合（グラウンディング）させます。
    room_name引数は、ツール呼び出しの統一性のために存在しますが、このツールでは直接使用されません。
    """
    print(f"--- Geminiネイティブ検索ツール実行 (Query: '{query}') ---")
    try:
        # 1. APIキーを取得 (変更なし)
        api_key_name = config_manager.initial_api_key_name_global
        api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)
        if not api_key or api_key.startswith("YOUR_API_KEY"):
            return f"[エラー: 有効なGoogle APIキー '{api_key_name}' が設定されていません]"

        # 2. クライアントを初期化 (プロジェクト規約に準拠)
        client = genai.Client(api_key=api_key)

        # 3. グラウンディングのための「検索ツール」を定義
        search_tool_for_api = types.Tool(google_search=types.GoogleSearch())

        # 4. ツール設定を持つGenerateContentConfigを作成
        generation_config = types.GenerateContentConfig(tools=[search_tool_for_api])

        # 5. 検索を実行するために、専用の高速モデルでコンテンツを生成
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=query,
            config=generation_config
        )

        # 6. 結果を返す
        return response.text if response.text else "[情報：Web検索で結果が見つかりませんでした]"

    except Exception as e:
        print(f"  - Geminiネイティブ検索ツールでエラー: {e}")
        traceback.print_exc()
        return f"[エラー：Web検索中に問題が発生しました。詳細: {e}]"

@tool
def read_url_tool(urls: list[str]) -> str:
    """
    指定されたURLリストの内容を読み取り、結合して単一の文字列として返すツール。
    """
    if not urls:
        return "URLが指定されていません。"
    try:
        # (この関数の内容は変更ありません)
        # ... 実際の読み取りロジック ...
        return "URLの内容を読み取りました。（この機能は現在スタブです）"
    except Exception as e:
        return f"URLの内容取得中に予期せぬシステムエラーが発生しました。URLが無効か、ページがアクセスできない可能性があります。詳細: {e}"
