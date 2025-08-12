# tools/web_tools.py

import os
import traceback
from tavily import TavilyClient
from langchain_core.tools import tool

@tool
def read_url_tool(urls: list[str]) -> str:
    """URLリストの内容を読み、一つの文字列として返す。"""
    if not urls:
        return "URLが指定されていません。"
    # ... (以降のコードは変更なし)
    return "URLの内容取得中に予期せぬシステムエラーが発生しました。URLが無効か、ページがアクセスできない可能性があります。"

# ★ ここに、agent/graph.pyから切り取った関数を貼り付ける
@tool
def web_search_tool(query: str, api_key: str = None) -> str:
    """Webで最新情報を検索する。"""
    print(f"--- Web検索ツール実行 (Query: '{query}') ---")

    # 引数で渡されたキーを優先し、なければ環境変数を参照する
    tavily_api_key = api_key if api_key else os.getenv("TAVILY_API_KEY")

    if not tavily_api_key:
        return "[エラー：Tavily APIキーが設定されていません]"
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=tavily_api_key)
        # search_depthを"advanced"にすることで、より高品質な検索を期待
        response = client.search(query=query, search_depth="advanced", max_results=5)
        if response and response.get('results'):
            return "\n\n".join([f"URL: {res['url']}\n内容: {res['content']}" for res in response['results']])
        else:
            return "[情報：Web検索で結果が見つかりませんでした]"
    except Exception as e:
        print(f"  - Web検索ツールでエラー: {e}")
        traceback.print_exc()
        return f"[エラー：Web検索中に問題が発生しました。詳細: {e}]"
