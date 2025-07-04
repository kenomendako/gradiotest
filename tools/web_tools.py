# tools/web_tools.py にこのコードを貼り付けてください

import os
from tavily import TavilyClient
from langchain_core.tools import tool

@tool
def read_url_tool(urls: list[str]) -> str:
    """
    指定されたURLリストの内容を読み取り、結合して単一の文字列として返すツール。
    Tavilyの'extract'メソッドを使用し、様々な返り値の形式に対応する。
    """
    if not urls:
        return "URLが指定されていません。"

    tavily_api_key = os.getenv("TAVILY_API_KEY")
    if not tavily_api_key:
        print("エラー: TAVILY_API_KEYが環境変数に設定されていません。")
        return "URL読み取りツールの設定に問題があります。管理者に連絡してください。"

    client = TavilyClient(api_key=tavily_api_key)
    all_content = []

    print(f"--- URL読み取りツール実行 (URLs: {urls}) ---")

    try:
        # サイトによっては異なる形式で結果を返すことがあるため、トークン数に余裕を持たせる
        results = client.extract(urls=urls, max_tokens=8000)

        for result in results:
            # ★★★ここが今回のエラーを解決する最重要修正点★★★
            # resultが期待通りの辞書形式か、それ以外の形式(エラー文字列など)かを判断
            if isinstance(result, dict):
                # 辞書の場合：正常に内容を抽出
                content = result.get('content', 'このURLからはコンテンツを取得できませんでした。')
                url_source = result.get('url', '不明なURL')
                all_content.append(f"URL ({url_source}) の内容:\n---\n{content}\n---")
            else:
                # 辞書でない場合(文字列など)は、その情報をそのままAIへの情報として追加
                all_content.append(f"指定されたURLからの情報:\n---\n{str(result)}\n---")

        if not all_content:
            return "指定された全てのURLから内容を抽出できませんでした。"

        return "\n\n".join(all_content)

    except Exception as e:
        # 予期せぬエラーが発生した場合の最終防衛ライン
        error_message = f"TavilyClientの'extract'メソッド呼び出し中に予期せぬエラー: {type(e).__name__} - {e}"
        print(f"  - {error_message}")
        return "URLの内容取得中に予期せぬシステムエラーが発生しました。URLが無効か、ページがアクセスできない可能性があります。"
