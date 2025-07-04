# agent/graph.py の内容を、このコードブロックで完全に置き換えてください

import os
import traceback
from typing import TypedDict, List
from typing_extensions import Annotated
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END, START, add_messages
from langchain_core.tools import tool

# 外部モジュールとツールのインポート
import config_manager
import rag_manager
from tools.web_tools import read_url_tool

# --- 1. AgentStateの定義 (変更なし) ---
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    character_name: str
    api_key: str

# --- 2. ユーティリティ関数: LLMの初期化 (変更なし) ---
def get_configured_llm(model_name: str, api_key: str, bind_tools: List = None):
    llm = ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=api_key,
        convert_system_message_to_human=True,
    )
    if bind_tools:
        llm = llm.bind_tools(bind_tools)
        print(f"  - モデル '{model_name}' に道具: {[tool.name for tool in bind_tools]} をバインドしました。")
    else:
        print(f"  - モデル '{model_name}' は道具なしで初期化されました。")
    return llm

# --- 3. 新しいノードの定義 ---

# ★★★ ここからが抜本的な変更点 ★★★

def tool_router_node(state: AgentState):
    """【役割分離①：ツールルーター】Flashモデルを使い、ツールを呼び出すか最終応答に進むかだけを判断する。"""
    print("--- ツールルーターノード (tool_router_node) 実行 ---")
    api_key = state['api_key']

    # 思考をシンプルにするため、利用可能なツールをリストで定義
    available_tools = [rag_manager.search_tool, web_search_tool, read_url_tool]

    # Flashモデルにツールをバインド
    llm_flash_with_tools = get_configured_llm("gemini-2.5-flash", api_key, available_tools)

    # Flashモデルに現在のメッセージを渡して、ツール呼び出しを試みさせる
    # このノードでは、Flashモデルがおしゃべりしても、その応答は使われない。tool_callsがあるかないかだけが重要。
    response = llm_flash_with_tools.invoke(state['messages'])

    # 新しいメッセージとして、Flashの応答（tool_callsを含む可能性がある）を追加して返す
    return {"messages": [response]}

def call_tool_node(state: AgentState):
    """【役割分離②：ツール実行役】指定されたツールを実際に実行する（ほぼ変更なし）"""
    last_message = state['messages'][-1]
    if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
        return {"messages": []} # ツール呼び出しがなければ何もしない

    print(f"--- 道具実行ノード (call_tool_node) 実行 ---")
    tool_messages = []
    available_tools_map = {
        "search_tool": rag_manager.search_tool,
        "web_search_tool": web_search_tool,
        "read_url_tool": read_url_tool
    }

    for tool_call in last_message.tool_calls:
        tool_name = tool_call.get("name")
        tool_args = tool_call.get("args", {})
        tool_call_id = tool_call.get("id")

        print(f"  - 道具: {tool_name} を使用 (ID: {tool_call_id}), 引数: {tool_args}")
        tool_to_call = available_tools_map.get(tool_name)

        if not tool_to_call:
            output = f"エラー: 不明な道具 '{tool_name}' が指定されました。"
        else:
            try:
                # RAGツールの場合のみ追加引数を渡す
                if tool_name == "search_tool":
                    tool_args.update({"character_name": state.get("character_name"), "api_key": state.get("api_key")})
                output = tool_to_call.invoke(tool_args)
            except Exception as e:
                print(f"  - 道具 '{tool_name}' の実行中にエラー: {e}")
                traceback.print_exc()
                output = f"[エラー：道具'{tool_name}'の実行に失敗しました。詳細: {e}]"

        tool_messages.append(ToolMessage(content=str(output), tool_call_id=tool_call_id))

    return {"messages": tool_messages}

def final_response_node(state: AgentState):
    """【役割分離③：最終応答役】Proモデルを使い、最終的な応答だけを生成する。"""
    print("--- 最終応答生成ノード (final_response_node) 実行 ---")
    api_key = state['api_key']

    # Proモデルはツールをバインドせずに初期化
    llm_pro = get_configured_llm("gemini-2.5-pro", api_key)

    print(f"  - Proモデルへの入力メッセージ数: {len(state['messages'])}")
    try:
        response = llm_pro.invoke(state['messages'])
        return {"messages": [response]}
    except Exception as e:
        print(f"  - 最終応答生成ノードでエラー: {e}")
        traceback.print_exc()
        # エラーが発生した場合も、エラーメッセージをStateに入れてグラフを正常に終了させる
        error_message = AIMessage(content=f"[エラー：最終応答の生成中に問題が発生しました。詳細: {e}]")
        return {"messages": [error_message]}


# --- 4. 新しいルーティングロジック ---
def should_call_tool(state: AgentState):
    """ツールルーターの実行後、ツールを呼び出すべきか、それとも最終応答に進むべきかを判断する。"""
    last_message = state['messages'][-1]
    if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        # Flashモデルがツール呼び出しを返した場合
        print("  - ルーティング判断: ツール呼び出しあり。call_tool_node へ。")
        return "call_tool"
    else:
        # Flashモデルが通常の応答を返した場合 (その応答は使わず)、最終応答生成に進む
        print("  - ルーティング判断: ツール呼び出しなし。final_response_node へ。")
        return "final_response"

# --- 5. 新しいグラフの構築 ---
workflow = StateGraph(AgentState)

# ノードを登録
workflow.add_node("tool_router", tool_router_node)
workflow.add_node("call_tool", call_tool_node)
workflow.add_node("final_response", final_response_node)

# エントリーポイントを設定
workflow.set_entry_point("tool_router")

# 条件付きエッジ: ツールルーターからの分岐
workflow.add_conditional_edges(
    "tool_router",
    should_call_tool,
    {
        "call_tool": "call_tool",
        "final_response": "final_response" # ツールを使わない場合は直接最終応答へ
    }
)

# ツール実行後は、必ず最終応答生成へ
workflow.add_edge("call_tool", "final_response")

# 最終応答生成後はグラフを終了
workflow.add_edge("final_response", END)

# グラフをコンパイル
app = workflow.compile()

# --- web_search_tool の定義 (古いコードにあったもの、グラフのグローバルスコープに必要) ---
@tool
def web_search_tool(query: str) -> str:
    """ユーザーからのクエリに基づいて、最新の情報を得るためにWeb検索を実行します。"""
    print(f"--- Web検索ツール実行 (Query: '{query}') ---")
    tavily_api_key = os.environ.get("TAVILY_API_KEY")
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
        return f"[エラー：Web検索中に問題が発生しました。詳細: {e}]"
