# tools/web_tools.py

import os
import traceback
from tavily import TavilyClient
from langchain_core.tools import tool

@tool
def read_url_tool(urls: list[str]) -> str:
    """指定されたURLリストの内容を読み取り、結合して単一の文字列として返すツール。""" # ★ この一行を追加
    if not urls:
        return "URLが指定されていません。"
    # ... (以降のコードは変更なし)
    return "URLの内容取得中に予期せぬシステムエラーが発生しました。URLが無効か、ページがアクセスできない可能性があります。"

# ★ ここに、agent/graph.pyから切り取った関数を貼り付ける
@tool
def web_search_tool(query: str) -> str:
    """ユーザーからのクエリに基づいて、最新の情報を得るためにWeb検索を実行します。"""
    print(f"--- Web検索ツール実行 (Query: '{query}') ---")
    tavily_api_key = os.getenv("TAVILY_API_KEY")
    if not tavily_api_key:
        return "[エラー：Tavily APIキーが環境変数に設定されていません]"
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=tavily_api_key)
        response = client.search(query=query, search_depth="advanced", max_results=3)
        if response and response.get('results'):
            return "\n\n".join([f"URL: {res['url']}\n内容: {res['content']}" for res in response['results']])
        else:
            return "[情報：Web検索で結果が見つかりませんでした]"
    except Exception as e:
        print(f"  - Web検索ツールでエラー: {e}")
        traceback.print_exc()
        return f"[エラー：Web検索中に問題が発生しました。詳細: {e}]"
