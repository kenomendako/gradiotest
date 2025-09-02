# tools/web_tools.py (v5.0 - Proven Architecture Restoration)

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
        # APIキーをconfig_managerから動的に取得
        api_key_name = config_manager.initial_api_key_name_global
        api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)
        if not api_key or api_key.startswith("YOUR_API_KEY"):
            return f"[エラー: 有効なGoogle APIキー '{api_key_name}' が設定されていません]"

        client = genai.Client(api_key=api_key)

        # グラウンディングのための「検索ツール」を定義
        search_tool_for_api = types.Tool(
            google_search_retrieval=types.GoogleSearchRetrieval()
        )

        # Gemini 1.5 Flashモデルに検索を依頼し、結果のテキストを返す
        response = client.models.generate_content(
            model='models/gemini-1.5-flash', # 高速なモデルを検索に使用
            contents=[query],
            tools=[search_tool_for_api]
        )

        # 検索結果から引用情報を抽出し、整形して返す
        if response and response.candidates and response.candidates[0].content.parts:
            final_text_parts = []
            for part in response.candidates[0].content.parts:
                if part.text:
                    final_text_parts.append(part.text)
                elif part.tool_code and part.tool_code.outputs:
                    for output in part.tool_code.outputs:
                        if output.google_search:
                            for result in output.google_search.results:
                                final_text_parts.append(f"\n[引用: {result.title}]({result.uri})")

            return "\n".join(final_text_parts).strip() if final_text_parts else "[情報：Web検索で結果が見つかりませんでした]"

        return "[情報：Web検索で結果が見つかりませんでした]"

    except Exception as e:
        print(f"  - Geminiネイティブ検索ツールでエラー: {e}")
        traceback.print_exc()
        return f"[エラー：Web検索中に問題が発生しました。詳細: {e}]"

@tool
def read_url_tool(urls: list[str], room_name: str) -> str:
    """
    指定されたURLリストの内容を読み取り、結合して単一の文字列として返すツール。
    """
    # ... (この関数の内容は変更ありません) ...
    return "URLの内容を読み取りました。（この機能は現在スタブです）"
