# tools/web_tools.py (v2.0 - Google Native Search Edition)

from langchain_core.tools import tool
# LangChainが提供する、Gemini APIネイティブ検索のための専用ツールをインポート
from langchain_google_genai import GoogleSearchRun
import traceback
import config_manager # APIキーを取得するためにインポート

@tool
def web_search_tool(query: str) -> str:
    """
    ユーザーからのクエリに基づいて、最新の情報を得るためにGoogle検索を実行します。
    このツールは、Geminiモデルに内蔵されたネイティブな検索機能を利用します。
    """
    print(f"--- Googleネイティブ検索ツール実行 (Query: '{query}') ---")
    try:
        # LangChainツールがAPIキーを自動で参照できるよう、環境変数を設定する
        # これは、このツールの実行中のみ有効な、安全な方法です
        import os
        api_key_name = config_manager.initial_api_key_name_global
        api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)
        if not api_key or api_key.startswith("YOUR_API_KEY"):
            return "[エラー: 有効なGoogle APIキーが設定されていません]"

        os.environ["GOOGLE_API_KEY"] = api_key

        search = GoogleSearchRun()
        results = search.run(query)

        # 使用後に環境変数をクリーンアップするのが良い作法です
        del os.environ['GOOGLE_API_KEY']

        return results if results else "[情報：Web検索で結果が見つかりませんでした]"
    except Exception as e:
        print(f"  - Googleネイティブ検索ツールでエラー: {e}")
        traceback.print_exc()
        return f"[エラー：Web検索中に問題が発生しました。詳細: {e}]"

@tool
def read_url_tool(urls: list[str]) -> str:
    """
    指定されたURLリストの内容を読み取り、結合して単一の文字列として返すツール。
    """
    # (この関数の内容は、あなたのmainブランチのコードパックに含まれていたものであり、変更はありません)
    if not urls:
        return "URLが指定されていません。"
    # ... (以降のコードは変更なし) ...
    return "URLの内容取得中に予期せぬシステムエラーが発生しました。URLが無効か、ページがアクセスできない可能性があります。"
