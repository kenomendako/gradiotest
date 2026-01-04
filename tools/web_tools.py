# tools/web_tools.py (v7.0 - Tavily Integration & URL Reading)

from langchain_core.tools import tool
import google.genai as genai
from google.genai import types
import traceback
import config_manager
import constants
from ddgs import DDGS

# Tavilyのインポート（インストールされていない場合のフォールバック対応）
try:
    from langchain_tavily import TavilySearch, TavilyExtract
    TAVILY_AVAILABLE = True
except ImportError:
    TAVILY_AVAILABLE = False
    print("警告: langchain-tavilyがインストールされていません。Tavily機能は利用できません。")


def _search_with_tavily(query: str) -> str:
    """Tavily APIを使用して検索を実行する内部関数"""
    if not TAVILY_AVAILABLE:
        return "[エラー: Tavilyライブラリがインストールされていません。`pip install langchain-tavily` を実行してください]"
    
    api_key = config_manager.TAVILY_API_KEY
    if not api_key:
        return "[エラー: Tavily APIキーが設定されていません。共通設定 → APIキー管理 から設定してください]"
    
    try:
        tavily = TavilySearch(
            api_key=api_key,
            max_results=5,
            include_answer=True,  # AIが生成した回答も含める
            include_raw_content=False,  # 生コンテンツは不要（トークン節約）
        )
        results = tavily.invoke(query)
        
        if not results:
            return "[情報: Tavily検索で結果が見つかりませんでした]"
        
        # 結果を整形
        formatted_parts = []
        citations = []
        
        # Tavilyの回答がある場合は最初に表示
        if isinstance(results, dict):
            if results.get("answer"):
                formatted_parts.append(f"**AI要約:**\n{results['answer']}\n")
            
            for result in results.get("results", []):
                title = result.get("title", "No Title")
                url = result.get("url", "#")
                content = result.get("content", "")
                
                # コンテンツを適度な長さに切り詰め
                if len(content) > 500:
                    content = content[:500] + "..."
                
                formatted_parts.append(f"### {title}\n{content}")
                citations.append(f"- [{title}]({url})")
        elif isinstance(results, list):
            # リスト形式の場合
            for result in results:
                title = result.get("title", "No Title")
                url = result.get("url", "#")
                content = result.get("content", "")
                
                if len(content) > 500:
                    content = content[:500] + "..."
                
                formatted_parts.append(f"### {title}\n{content}")
                citations.append(f"- [{title}]({url})")
        
        final_response = "\n\n".join(formatted_parts)
        if citations:
            final_response += "\n\n**引用元 (Tavily):**\n" + "\n".join(citations)
        
        return final_response
        
    except Exception as e:
        print(f"  - Tavily検索でエラー: {e}")
        traceback.print_exc()
        return f"[エラー: Tavily検索中に問題が発生しました。詳細: {e}]"


def _search_with_ddg(query: str) -> str:
    """DuckDuckGoを使用して検索を実行する内部関数"""
    try:
        results = DDGS().text(query, max_results=5)
        if not results:
            return "[情報: DuckDuckGo検索で結果が見つかりませんでした]"
        
        formatted_results = []
        citations = []
        for i, res in enumerate(results):
            title = res.get('title', 'No Title')
            href = res.get('href', '#')
            body = res.get('body', '')
            formatted_results.append(f"### {title}\n{body}")
            citations.append(f"- [{title}]({href})")
        
        final_response = "\n\n".join(formatted_results)
        if citations:
            final_response += "\n\n**引用元 (DuckDuckGo):**\n" + "\n".join(citations)
        
        return final_response
        
    except Exception as e:
        print(f"  - DuckDuckGo検索でエラー: {e}")
        traceback.print_exc()
        return f"[エラー: DuckDuckGo検索中に問題が発生しました。詳細: {e}]"


def _search_with_google(query: str) -> str:
    """Google検索（Gemini Native）を使用して検索を実行する内部関数"""
    try:
        api_key_name = config_manager.initial_api_key_name_global
        api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)
        if not api_key or api_key.startswith("YOUR_API_KEY"):
            return f"[エラー: 有効なGoogle APIキー '{api_key_name}' が設定されていません]"

        client = genai.Client(api_key=api_key)

        # グラウンディングのための検索ツールを定義
        search_tool_for_api = types.Tool(
            google_search=types.GoogleSearch()
        )

        generation_config_with_tool = types.GenerateContentConfig(
            tools=[search_tool_for_api]
        )

        response = client.models.generate_content(
            model=f'models/{constants.SEARCH_MODEL}',
            contents=[query],
            config=generation_config_with_tool
        )

        # 応答からテキストと引用情報を抽出
        grounding_attributions = []
        text_parts = []

        if response and response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.text:
                    text_parts.append(part.text)

        if response and response.candidates and hasattr(response.candidates[0], 'grounding_attributions'):
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
def web_search_tool(query: str, room_name: str) -> str:
    """
    ユーザーからのクエリに基づいて、最新の情報を得るためにWeb検索を実行します。
    設定に応じて、Tavily、Google検索（Geminiネイティブ）、またはDuckDuckGo検索を使用します。
    """
    # 設定から検索プロバイダを取得
    provider = config_manager.CONFIG_GLOBAL.get("search_provider", constants.DEFAULT_SEARCH_PROVIDER)
    
    if provider == "disabled":
        return "[情報: Web検索機能は現在無効化されています]"

    print(f"--- Web検索ツール実行 (Provider: {provider}, Query: '{query}') ---")

    # プロバイダに応じて検索を実行
    if provider == "tavily":
        return _search_with_tavily(query)
    elif provider == "ddg":
        return _search_with_ddg(query)
    else:  # google (デフォルト)
        return _search_with_google(query)


@tool
def read_url_tool(urls: list[str], room_name: str) -> str:
    """
    指定されたURLリストの内容を読み取り、結合して単一の文字列として返すツール。
    Tavilyが設定されている場合はTavily Extractを使用し、そうでない場合は基本的なHTTP取得を試みます。
    """
    if not urls:
        return "URLが指定されていません。"
    
    # URLを5件に制限
    urls_to_fetch = urls[:5]
    
    # Tavilyが利用可能で、APIキーが設定されている場合はTavily Extractを使用
    if TAVILY_AVAILABLE and config_manager.TAVILY_API_KEY:
        try:
            extractor = TavilyExtract(
                api_key=config_manager.TAVILY_API_KEY,
                extract_depth="basic"  # 基本的な抽出（コスト節約）
            )
            results = extractor.invoke(urls_to_fetch)
            
            if not results:
                return "[情報: URLからコンテンツを抽出できませんでした]"
            
            formatted_parts = []
            
            if isinstance(results, dict) and "results" in results:
                for result in results["results"]:
                    url = result.get("url", "Unknown URL")
                    content = result.get("raw_content", result.get("content", ""))
                    
                    # コンテンツを適度な長さに切り詰め
                    if len(content) > 2000:
                        content = content[:2000] + "\n...(省略)..."
                    
                    formatted_parts.append(f"## {url}\n\n{content}")
            elif isinstance(results, list):
                for result in results:
                    url = result.get("url", "Unknown URL")
                    content = result.get("raw_content", result.get("content", ""))
                    
                    if len(content) > 2000:
                        content = content[:2000] + "\n...(省略)..."
                    
                    formatted_parts.append(f"## {url}\n\n{content}")
            
            if not formatted_parts:
                return "[情報: URLからコンテンツを抽出できませんでした]"
            
            final_response = "\n\n---\n\n".join(formatted_parts)
            return f"**取得完了 ({len(formatted_parts)}件)**\n\n{final_response}\n\n**このタスクは完了しました。これから読むというような前置きはせず、**読み取った情報を元に会話を続けてください。"
            
        except Exception as e:
            print(f"  - Tavily Extractでエラー: {e}")
            traceback.print_exc()
            return f"[エラー: URL内容の取得中に問題が発生しました。詳細: {e}]"
    
    # Tavilyが利用できない場合は基本的なHTTP取得を試みる
    try:
        import requests
        from bs4 import BeautifulSoup
        
        formatted_parts = []
        for url in urls_to_fetch:
            try:
                response = requests.get(url, timeout=10, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                })
                response.raise_for_status()
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # スクリプトとスタイルを除去
                for script in soup(["script", "style"]):
                    script.decompose()
                
                # テキストを抽出
                text = soup.get_text(separator='\n', strip=True)
                
                # テキストを適度な長さに切り詰め
                if len(text) > 2000:
                    text = text[:2000] + "\n...(省略)..."
                
                formatted_parts.append(f"## {url}\n\n{text}")
                
            except Exception as e:
                formatted_parts.append(f"## {url}\n\n[取得失敗: {e}]")
        
        if not formatted_parts:
            return "[情報: URLからコンテンツを取得できませんでした]"
        
        final_response = "\n\n---\n\n".join(formatted_parts)
        return f"**取得完了 ({len(formatted_parts)}件)**\n\n{final_response}\n\n**このタスクは完了しました。これから読むというような前置きはせず、**読み取った情報を元に会話を続けてください。"
        
    except ImportError:
        return "[エラー: requests/beautifulsoup4がインストールされていません。Tavilyを設定するか、`pip install requests beautifulsoup4` を実行してください]"
    except Exception as e:
        print(f"  - URL取得でエラー: {e}")
        traceback.print_exc()
        return f"[エラー: URL内容の取得中に問題が発生しました。詳細: {e}]"
