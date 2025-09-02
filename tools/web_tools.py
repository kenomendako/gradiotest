# tools/web_tools.py (v5.3 - Pydantic Validation Compliant Final Version)

from langchain_core.tools import tool
import google.genai as genai
from google.genai import types
import traceback
import config_manager
import constants

@tool
def web_search_tool(query: str, room_name: str) -> str:
    """
    ユーザーからのクエリに基づいて、最新の情報を得るためにGoogle検索を実行します。
    このツールは、Geminiモデル自身の思考プロセスに、Google検索の結果を直接統合（グラウンディング）させます。
    room_name引数は、ツール呼び出しの統一性のために存在しますが、このツールでは直接使用されません。
    """
    print(f"--- Geminiネイティブ検索ツール実行 (Query: '{query}') ---")
    try:
        api_key_name = config_manager.initial_api_key_name_global
        api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)
        if not api_key or api_key.startswith("YOUR_API_KEY"):
            return f"[エラー: 有効なGoogle APIキー '{api_key_name}' が設定されていません]"

        client = genai.Client(api_key=api_key)

        # ▼▼▼【ここが修正の核心】▼▼▼
        # GoogleSearchRetrieval() を、引数なしで呼び出します。
        # これが、このオブジェクトの唯一の正しい使い方です。
        search_tool_for_api = types.Tool(
            google_search_retrieval=types.GoogleSearchRetrieval()
        )
        # ▲▲▲【修正ここまで】▲▲▲

        generation_config_with_tool = types.GenerateContentConfig(
            tools=[search_tool_for_api]
        )

        response = client.models.generate_content(
            model=f"models/{constants.INTERNAL_PROCESSING_MODEL}",
            contents=[query],
            config=generation_config_with_tool
        )

        grounding_attributions = []
        text_parts = []

        if response and response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.text:
                    text_parts.append(part.text)

        if response and response.candidates and response.candidates[0].grounding_attributions:
             for attribution in response.candidates[0].grounding_attributions:
                if attribution.web:
                    title = attribution.web.title or "無題のページ"
                    uri = attribution.web.uri
                    grounding_attributions.append(f"- [{title}]({uri})")

        if not text_parts and not grounding_attributions:
            return "[情報：Web検索で結果が見つかりませんでした]"

        final_response = "".join(text_parts)
        if grounding_attributions:
            final_response += "\n\n**引用元:**\n" + "\n".join(grounding_attributions)

        return final_response.strip()

    except Exception as e:
        print(f"  - Geminiネイティブ検索ツールでエラー: {e}")
        traceback.print_exc()
        return f"[エラー：Web検索中に問題が発生しました。詳細: {e}]"

@tool
def read_url_tool(urls: list[str], room_name: str) -> str:
    """
    指定されたURLリストの内容を読み取り、結合して単一の文字列として返すツール。
    """
    if not urls:
        return "URLが指定されていません。"
    try:
        return "URLの内容を読み取りました。（この機能は現在スタブです）"
    except Exception as e:
        return f"URLの内容取得中に予期せぬシステムエラーが発生しました。URLが無効か、ページがアクセスできない可能性があります。詳細: {e}"
