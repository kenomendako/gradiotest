import os
import traceback
from typing import TypedDict, List, Optional
from typing_extensions import Annotated # または from typing import Annotated (Python 3.9+)
import re # URL抽出のため

# LangChain/LangGraphに最適化された、正しい、ライブラリを、インポートする
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, BaseMessage # BaseMessage もインポート
from langchain_core.tools import tool

from langgraph.graph import StateGraph, END, START, add_messages # add_messages をインポート
from tavily import TavilyClient

import config_manager
import rag_manager

# --- 新しい、魂の、定義書 (State) ---
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages] # BaseMessage を使うことで柔軟性向上
    character_name: str
    api_key: str
    detected_urls: Optional[List[str]] # ユーザー入力から検出されたURL
    url_content: Optional[str]         # read_url_tool で読み込んだURLの内容

# --- ツールの定義 ---

TAVILY_API_KEY_ENV_VAR = "TAVILY_API_KEY" # 環境変数名を定義

@tool
def read_url_tool(urls: List[str]) -> str:
    """指定されたURLリストのコンテンツを読み取ります。各URLの内容を結合して返します。"""
    print(f"--- URL読み取りツール実行 (URLs: {urls}) ---")
    tavily_api_key = os.environ.get(TAVILY_API_KEY_ENV_VAR)
    if not tavily_api_key:
        return "[エラー：Tavily APIキーが環境変数に設定されていません]"
    if not urls:
        return "[情報：読み取るべきURLが指定されていませんでした]"

    client = TavilyClient(api_key=tavily_api_key)
    all_contents = []
    max_length_per_url = 4000 # 1URLあたりの最大文字数

    for url in urls:
        try:
            content = client.get_contents_of_url(url)
            if content:
                # コンテンツを指定長に丸める
                content_to_add = content[:max_length_per_url]
                if len(content) > max_length_per_url:
                    content_to_add += "... (コンテンツが長いため省略されました)"
                all_contents.append(f"URL '{url}' の内容:\n{content_to_add}")
            else:
                all_contents.append(f"URL '{url}' から内容を取得できませんでした。")
        except Exception as e:
            print(f"  - URL '{url}' の読み取り中にエラー: {e}")
            traceback.print_exc()
            all_contents.append(f"[エラー：URL '{url}' の読み取り中に問題が発生しました: {e}]")

    if not all_contents:
        return "[情報：指定されたURLから内容を取得できませんでした]"

    return "\n\n".join(all_contents)

@tool
def web_search_tool(query: str) -> str:
    """ユーザーからのクエリに基づいて、最新の情報を得るためにWeb検索を実行します。"""
    print(f"--- Web検索ツール実行 (Query: '{query}') ---")
    tavily_api_key = os.environ.get(TAVILY_API_KEY_ENV_VAR)
    if not tavily_api_key:
        return "[エラー：Tavily APIキーが環境変数に設定されていません]"
    try:
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

# 利用可能な全ツール (RAGツールは rag_manager からインポートして利用)
# read_url_tool は専用ノードで呼ばれるが、AIが明示的に再度呼び出す可能性も考慮してリストに含める
available_tools_list = [read_url_tool, web_search_tool]
if hasattr(rag_manager, 'search_tool'):
    available_tools_list.append(rag_manager.search_tool)

# --- ノードの定義 ---

def extract_url_node(state: AgentState):
    """ユーザー入力からURLを抽出し、detected_urls に格納するノード"""
    print("--- URL抽出ノード実行 ---")
    last_message = state['messages'][-1] if state['messages'] and isinstance(state['messages'][-1], HumanMessage) else None
    detected_urls = []
    if last_message and isinstance(last_message.content, str):
        # 簡単なURL正規表現（より堅牢なものが必要な場合あり）
        urls = re.findall(r'https?://\S+', last_message.content)
        if urls:
            detected_urls = list(set(urls)) # 重複除去
            print(f"  - 検出されたURL: {detected_urls}")
    return {"detected_urls": detected_urls}

def call_read_url_tool_node(state: AgentState):
    """detected_urls に基づいて read_url_tool を呼び出し、結果を url_content に格納するノード"""
    print("--- URL読み取りツール呼び出しノード実行 ---")
    urls_to_read = state.get("detected_urls")
    if not urls_to_read:
        print("  - 読み込むURLがありません。スキップします。")
        return {"url_content": None, "messages": [AIMessage(content="[内部処理: 読み込むURLが検出されませんでした。]")]} # ユーザーには見せないメッセージ

    tool_output = read_url_tool.invoke({"urls": urls_to_read}) # tool自体を呼び出し

    # 読み取り結果を次のAI呼び出しのコンテキストとして追加
    # これはToolMessageではなく、システム情報として追加するイメージ
    # あるいは、url_content stateを更新し、次のノードのプロンプトで参照する
    summary_message_for_history = f"[システム情報: 以下のURLの内容を読み込みました。\n{tool_output}\nシステム情報ここまで]"
    return {"url_content": tool_output, "messages": [AIMessage(content=summary_message_for_history)]} # ユーザーには見せないメッセージ


def decide_tool_or_direct_answer_node(state: AgentState):
    """Gemini Flashを使用して、他のツールを使うか直接応答を生成するかを判断するノード"""
    print("--- ツール/直接応答判断ノード (Flash) 実行 ---")
    # TODO: safety_settings を config_manager から読み込んで適用する
    llm_flash = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash", # ツール呼び出し判断と初期応答試行
        google_api_key=state['api_key'],
        convert_system_message_to_human=True,
        # safety_settings=config_manager.SAFETY_CONFIG
    )

    # ツールをバインド
    tools_for_flash = [web_search_tool] # read_url_toolは既に実行済みなので含めない
    if hasattr(rag_manager, 'search_tool'):
        tools_for_flash.append(rag_manager.search_tool)

    llm_with_tools = llm_flash.bind_tools(tools_for_flash) if tools_for_flash else llm_flash
    print(f"  - Flash用利用可能ツール: {[tool.name for tool in tools_for_flash] if tools_for_flash else 'なし'}")

    # プロンプトの準備: 最新のメッセージに加え、読み込んだURLの内容もコンテキストに含める
    current_messages = list(state['messages']) # コピーを作成
    # url_content があれば、それをシステムメッセージ的なものとして追加
    # if state.get("url_content"):
    #     # ユーザーに見えない形で情報を付加する。AIMessageとして追加するのが適切か検討。
    #     # 既に call_read_url_tool_node でAIMessageとして追加されているので、ここでは不要。
    #     # current_messages.append(AIMessage(content=f"[システム情報: 読み込まれたURLの内容を参考にしてください。内容の要約:\n{state['url_content'][:500]}...]"))
    #     pass


    if not current_messages:
        print("  - 警告: メッセージ履歴が空です。")
        return {"messages": [AIMessage(content="[メッセージ履歴が空のため応答できません]")]}

    print(f"  - Flashへの入力メッセージ数: {len(current_messages)}")
    try:
        response_message = llm_with_tools.invoke(current_messages)
        return {"messages": [response_message]}
    except Exception as e:
        print(f"  - Flash判断ノードでエラー: {e}")
        traceback.print_exc()
        error_message = AIMessage(content=f"[エラー：Flash判断中に問題が発生しました。詳細: {e}]")
        return {"messages": [error_message]}

def execute_selected_tool_node(state: AgentState):
    """AI (Flash) が使用を決めたツールを呼び出すノード"""
    last_message = state['messages'][-1]
    if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
        print("  - ツール呼び出しなし (Flash判断)。スキップします。")
        return {"messages": []} # 何もせず次のノードへ

    print(f"--- 選択ツール実行ノード (Flash判断による) 実行 ---")
    tool_messages: List[ToolMessage] = []

    # Flashが利用できたツールのみを対象とする
    flash_tools_map = {
        "web_search_tool": web_search_tool,
    }
    # hasattr で search_tool の存在は確認済みだが、念のため name 属性も確認
    if hasattr(rag_manager, 'search_tool') and hasattr(rag_manager.search_tool, 'name') and rag_manager.search_tool.name:
        flash_tools_map[rag_manager.search_tool.name] = rag_manager.search_tool


    for tool_call in last_message.tool_calls:
        tool_name = tool_call.get("name")
        tool_args = tool_call.get("args", {})
        tool_call_id = tool_call.get("id")

        if not tool_call_id:
            print(f"  - 警告: tool_callにIDがありません。スキップ。 Tool call: {tool_call}")
            continue

        print(f"  - ツール: {tool_name} を使用 (ID: {tool_call_id}), 引数: {tool_args}")
        tool_to_call = flash_tools_map.get(tool_name)

        if not tool_to_call:
            print(f"  - 警告: Flashが判断したツール '{tool_name}' が不明です。")
            tool_messages.append(ToolMessage(content=f"Error: Unknown tool '{tool_name}' decided by Flash.", tool_call_id=tool_call_id))
            continue
        try:
            # RAGツールの場合の特別処理
            final_tool_args = tool_args
            # rag_manager.search_tool とその name 属性が存在するか再度確認
            if hasattr(rag_manager, 'search_tool') and hasattr(rag_manager.search_tool, 'name') and tool_name == rag_manager.search_tool.name:
                final_tool_args = {
                    **tool_args,
                    "character_name": state.get("character_name"),
                    "api_key": state.get("api_key")
                }
            observation = tool_to_call.invoke(final_tool_args)
            tool_messages.append(ToolMessage(content=str(observation), tool_call_id=tool_call_id))
        except Exception as e:
            print(f"  - ツール '{tool_name}' の実行中にエラー: {e}")
            traceback.print_exc()
            tool_messages.append(ToolMessage(content=f"[エラー：ツール'{tool_name}'の実行に失敗。詳細: {e}]", tool_call_id=tool_call_id))

    return {"messages": tool_messages}


def generate_final_response_node(state: AgentState):
    """Gemini Proを使用して最終的な応答を生成するノード"""
    print("--- 最終応答生成ノード (Pro) 実行 ---")
    # TODO: safety_settings を config_manager から読み込んで適用する
    llm_pro = ChatGoogleGenerativeAI(
        model="gemini-2.5-pro", # 最終応答生成
        google_api_key=state['api_key'],
        convert_system_message_to_human=True,
        # safety_settings=config_manager.SAFETY_CONFIG
    )
    # Proモデルにはツールをバインドしない（既にツール実行は終わっている想定）

    current_messages = list(state['messages']) # コピー
    # url_content があり、かつFlashが直接応答を生成していて、その応答にURL内容がまだ十分反映されていない場合、
    # ここで再度情報を付加することを検討できるが、基本的にはFlash判断後のメッセージ群で十分なはず。
    # 最後のメッセージがToolMessageの場合、その結果をProモデルが解釈して応答する。
    # 最後のメッセージがAIMessage(Flashによる直接応答)の場合、それをProが清書・拡張するイメージ。

    if not current_messages:
        print("  - 警告: Proモデルへのメッセージ履歴が空です。")
        # このケースは通常発生しないはず
        return {"messages": [AIMessage(content="[最終応答生成エラー: メッセージ履歴が空です]")]}

    print(f"  - Proへの入力メッセージ数: {len(current_messages)}")
    try:
        response_message = llm_pro.invoke(current_messages)
        # 最終応答なので、tool_callsは期待しない
        if hasattr(response_message, 'tool_calls') and response_message.tool_calls:
            print("  - 警告: Proモデルがツール呼び出しを返しました。これは想定外です。ツール呼び出しを無視します。")
            response_message.tool_calls = None # 強制的にクリア
        return {"messages": [response_message]}
    except Exception as e:
        print(f"  - Pro応答生成ノードでエラー: {e}")
        traceback.print_exc()
        error_message = AIMessage(content=f"[エラー：最終応答の生成中に問題が発生しました。詳細: {e}]")
        return {"messages": [error_message]}

# --- ルーティングロジック ---

def agent_router_logic(state: AgentState):
    """URLが検出されたかどうかに基づいてルーティング"""
    if state.get("detected_urls"):
        print("  - Agentルーター: URL検出あり。URL読み取りツール呼び出しノードへ。")
        return "call_read_url_tool"
    else:
        print("  - Agentルーター: URL検出なし。ツール/直接応答判断ノードへ。")
        return "decide_tool_or_direct_answer"

def routing_after_flash_decision_logic(state: AgentState):
    """Flashの判断結果に基づいてルーティング"""
    last_message = state['messages'][-1] if state['messages'] else None
    if last_message and hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        print("  - Flash後ルーター: ツール呼び出しあり。選択ツール実行ノードへ。")
        return "execute_selected_tool"
    else:
        # Flashが直接応答を生成したか、エラーが発生した場合
        print("  - Flash後ルーター: ツール呼び出しなし。最終応答生成ノードへ。")
        return "generate_final_response"


# --- グラフの構築 ---
workflow = StateGraph(AgentState)

workflow.add_node("extract_url", extract_url_node)
workflow.add_node("call_read_url_tool", call_read_url_tool_node)
workflow.add_node("decide_tool_or_direct_answer", decide_tool_or_direct_answer_node)
workflow.add_node("execute_selected_tool", execute_selected_tool_node)
workflow.add_node("generate_final_response", generate_final_response_node)

# エントリーポイント
workflow.set_entry_point("extract_url")

# エッジ定義
workflow.add_conditional_edges(
    "extract_url",
    agent_router_logic,
    {
        "call_read_url_tool": "call_read_url_tool",
        "decide_tool_or_direct_answer": "decide_tool_or_direct_answer"
    }
)
workflow.add_edge("call_read_url_tool", "decide_tool_or_direct_answer")

workflow.add_conditional_edges(
    "decide_tool_or_direct_answer",
    routing_after_flash_decision_logic,
    {
        "execute_selected_tool": "execute_selected_tool",
        "generate_final_response": "generate_final_response" # Flashが直接応答した場合
    }
)
workflow.add_edge("execute_selected_tool", "generate_final_response") # ツール実行後は最終応答生成へ
workflow.add_edge("generate_final_response", END)


app = workflow.compile()

# --- テスト用のダミー main (開発中のみ) ---
if __name__ == '__main__':
    # 環境変数 TAVILY_API_KEY と GOOGLE_API_KEY を設定してテストしてください
    print("--- LangGraph Agent Test ---")
    # Tavily APIキーを環境変数から取得、なければダミーを設定
    tavily_api_key = os.environ.get(TAVILY_API_KEY_ENV_VAR)
    if not tavily_api_key:
        os.environ[TAVILY_API_KEY_ENV_VAR] = "YOUR_TAVILY_API_KEY_HERE" # ダミーキー
        print(f"警告: 環境変数 {TAVILY_API_KEY_ENV_VAR} が設定されていません。ダミーキーを使用します。")

    # Google APIキーを環境変数から取得、なければダミーを設定
    google_api_key = os.environ.get('GOOGLE_API_KEY')
    if not google_api_key:
        google_api_key = "YOUR_GOOGLE_API_KEY_HERE" # ダミーキー
        print(f"警告: 環境変数 GOOGLE_API_KEY が設定されていません。ダミーキーを使用します。")


    # テストケース1: URLを含む入力
    print("\n--- Test Case 1: Input with URL ---")
    initial_state_1 = {
        "messages": [HumanMessage(content="こんにちは！このページを見てください: https://www.google.com")],
        "character_name": "TestChar",
        "api_key": google_api_key,
        "detected_urls": None,
        "url_content": None
    }
    try:
        final_state_1 = app.invoke(initial_state_1)
        print("--- Final State 1 (URL) ---")
        for msg in final_state_1['messages']:
            print(f"  [{msg.type}] {msg.content}")
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                print(f"    Tool Calls: {msg.tool_calls}")
    except Exception as e:
        print(f"Error in Test Case 1: {e}")
        traceback.print_exc()


    # テストケース2: URLを含まない、Web検索が必要そうな入力
    print("\n--- Test Case 2: Input requiring web search ---")
    initial_state_2 = {
        "messages": [HumanMessage(content="今日の東京の天気は？")],
        "character_name": "TestChar",
        "api_key": google_api_key,
        "detected_urls": None,
        "url_content": None
    }
    try:
        final_state_2 = app.invoke(initial_state_2)
        print("--- Final State 2 (Web Search) ---")
        for msg in final_state_2['messages']:
            print(f"  [{msg.type}] {msg.content}")
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                print(f"    Tool Calls: {msg.tool_calls}")
    except Exception as e:
        print(f"Error in Test Case 2: {e}")
        traceback.print_exc()

    # テストケース3: 単純な挨拶
    print("\n--- Test Case 3: Simple greeting ---")
    initial_state_3 = {
        "messages": [HumanMessage(content="やあ！元気？")],
        "character_name": "TestChar",
        "api_key": google_api_key,
        "detected_urls": None,
        "url_content": None
    }
    try:
        final_state_3 = app.invoke(initial_state_3)
        print("--- Final State 3 (Greeting) ---")
        for msg in final_state_3['messages']:
            print(f"  [{msg.type}] {msg.content}")
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                print(f"    Tool Calls: {msg.tool_calls}")
    except Exception as e:
        print(f"Error in Test Case 3: {e}")
        traceback.print_exc()
