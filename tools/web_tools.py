# tools/web_tools.py

import os
import traceback
from langchain_core.tools import tool

@tool
def read_url_tool(urls: list[str]) -> str:
    """指定されたURLリストの内容を読み取り、結合して単一の文字列として返すツール。"""
    if not urls:
        return "URLが指定されていません。"

    all_content = ""
    for url in urls:
        try:
            # ここでは requests や beautifulsoup4 を使ってURLの内容を取得する実装を想定
            # このサンプルでは、簡略化のためダミーの処理を記述
            print(f"Reading content from {url}...")
            # response = requests.get(url)
            # response.raise_for_status() # エラーがあれば例外を発生させる
            # soup = BeautifulSoup(response.text, 'html.parser')
            # content = soup.get_text()
            # all_content += f"--- URL: {url} ---\n{content}\n\n"
            # NOTE: For now, this is a placeholder. A real implementation would go here.
            all_content += f"Content from {url} would be read here.\n"

        except Exception as e:
            error_message = f"An error occurred while reading {url}: {e}\n{traceback.format_exc()}"
            print(error_message)
            all_content += f"--- URL: {url} ---\nError: Could not read content.\n\n"

    if not all_content:
        return "どのURLからもコンテンツを読み取れませんでした。"

    return all_content
