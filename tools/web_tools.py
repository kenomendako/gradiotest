import os
from tavily import TavilyClient
from langchain_core.tools import tool

@tool
def read_url_tool(urls: list[str]) -> str:
    """
    指定されたURLリストの内容を読み取り、結合して単一の文字列として返すツール。
    Tavilyの'extract'メソッドを使用する。
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
        # 正しいメソッドは 'extract' です。URLのリストを渡します。
        results = client.extract(urls=urls, max_tokens=4000)

        # 'extract'は結果のリストを返すため、ループで処理します
        for result in results:
            content = result.get('content', 'このURLからはコンテンツを取得できませんでした。')
            url_source = result.get('url', '不明なURL')
            all_content.append(f"URL ({url_source}) の内容:\n---\n{content}\n---")

        if not all_content:
            return "指定された全てのURLから内容を抽出できませんでした。"

        return "\n\n".join(all_content)

    except Exception as e:
        # 開発者向けのデバッグ情報をコンソールに出力します
        error_message = f"TavilyClientの'extract'メソッド呼び出し中にエラーが発生: {type(e).__name__} - {e}"
        print(f"  - {error_message}")
        # AIモデルには、安全で分かりやすいエラーメッセージを返します
        return "URLの内容取得中にエラーが発生しました。URLが無効であるか、ページがアクセスできない可能性があります。"
