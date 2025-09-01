# tools/web_tools.py (v3.0 - Gemini Native Grounding Edition)

from langchain_core.tools import tool
import google.genai as genai
from google.genai.types import Tool
import traceback
import config_manager

@tool
def web_search_tool(query: str) -> str:
    """
    ユーザーからのクエリに基づいて、最新の情報を得るためにGoogle検索を実行します。
    このツールは、Geminiモデル自身の思考プロセスに、Google検索の結果を直接統合（グラウンディング）させます。
    """
    print(f"--- Geminiネイティブ検索ツール実行 (Query: '{query}') ---")
    try:
        # 1. APIキーを取得
        api_key_name = config_manager.initial_api_key_name_global
        api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)
        if not api_key or api_key.startswith("YOUR_API_KEY"):
            return "[エラー: 有効なGoogle APIキーが設定されていません]"

        # 2. Geminiクライアントを初期化
        genai.configure(api_key=api_key)

        # 3. グラウンディングのための「検索ツール」を定義
        #    これはLangChainのツールとは別物で、Gemini APIに直接渡すためのものです。
        search_tool = Tool(google_search=genai.types.GoogleSearch())

        # 4. 検索を実行するために、専用の高速モデル(gemini-2.5-flash)を使用
        model = genai.GenerativeModel(
            model_name='gemini-2.5-flash',
            tools=[search_tool],
        )

        # 5. 検索を実行し、結果をテキストとして取得
        response = model.generate_content(query)

        # 応答に検索結果が含まれているか確認
        # 最新のSDKでは、`citation_metadata`や`grounding_attributions`で確認できるが、
        # ここではシンプルにテキスト応答をそのまま返す
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
    # (この関数の内容は変更ありません)
    if not urls:
        return "URLが指定されていません。"
    # ...
    return "URLの内容取得中に予期せぬシステムエラーが発生しました。URLが無効か、ページがアクセスできない可能性があります。"
