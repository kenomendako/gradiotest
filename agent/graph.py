# agent/graph.py

import os
import traceback
from typing import TypedDict, List
from typing_extensions import Annotated
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END, START, add_messages
from langchain_core.tools import tool

# ★★★ 修正箇所 ★★★
# 正しいツールをインポートします
import rag_manager
from tools.web_tools import read_url_tool
# from agent.graph_tools import web_search_tool # web_search_toolのインポート元を修正 -> 既存の末尾定義を活かす

# --- AgentState定義 (変更なし) ---
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    character_name: str
    api_key: str
    final_model_name: str # ★★★ この行を追加 ★★★

# --- LLM初期化関数 (変更なし) ---
def get_configured_llm(model_name: str, api_key: str, bind_tools: List = None):
    llm = ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=api_key,
    )
    if bind_tools:
        llm = llm.bind_tools(bind_tools)
        print(f"  - モデル '{model_name}' に道具: {[tool.name for tool in bind_tools]} をバインドしました。")
    else:
        print(f"  - モデル '{model_name}' は道具なしで初期化されました。")
    return llm

# --- ノード定義 ---

def tool_router_node(state: AgentState):
    """【役割修正】Flashモデルを使い、ツール呼び出しを返すか、何も返さないかのどちらかを行う。"""
    print("--- ツールルーターノード (tool_router_node) 実行 ---")
    api_key = state['api_key']

    # ★★★ 修正箇所 ★★★
    # 正しい2つの記憶ツールと、ウェブ検索ツールをリストに追加します
    available_tools = [
        rag_manager.diary_search_tool,
        rag_manager.conversation_memory_search_tool,
        web_search_tool, # 末尾で定義されているものを参照
        read_url_tool
    ]

    # ★★★ 最重要修正箇所 ★★★
    # モデル名を指定通りの 'gemini-2.5-flash' に修正します
    llm_flash_with_tools = get_configured_llm("gemini-2.5-flash", api_key, available_tools)

    response = llm_flash_with_tools.invoke(state['messages'])

    if hasattr(response, 'tool_calls') and response.tool_calls:
        print("  - Flashが道具の使用を決定。")
        return {"messages": [response]}
    else:
        print("  - Flashは道具を使用しないと判断。")
        return {} # Stateを更新しない

def call_tool_node(state: AgentState):
    """【変更なし】ツールを実行する役目。"""
    last_message = state['messages'][-1]
    if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
        return {}

    print(f"--- 道具実行ノード (call_tool_node) 実行 ---")
    tool_messages = []

    # ★★★ 修正箇所 ★★★
    # 正しいツール名と関数のマッピングに更新します
    available_tools_map = {
        "diary_search_tool": rag_manager.diary_search_tool,
        "conversation_memory_search_tool": rag_manager.conversation_memory_search_tool,
        "web_search_tool": web_search_tool, # 末尾で定義されているものを参照
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
                # ★★★ 修正箇所 ★★★
                # diary_search_toolとconversation_memory_search_toolにcharacter_nameとapi_keyを渡す
                if tool_name in ["diary_search_tool", "conversation_memory_search_tool"]:
                    tool_args.update({"character_name": state.get("character_name"), "api_key": state.get("api_key")})

                output = tool_to_call.invoke(tool_args)
            except Exception as e:
                output = f"[エラー：道具'{tool_name}'の実行に失敗しました。詳細: {e}]"
                traceback.print_exc() # エラー詳細を表示

        tool_messages.append(ToolMessage(content=str(output), tool_call_id=tool_call_id))

    return {"messages": tool_messages}

def final_response_node(state: AgentState):
    """【変更なし】Proモデルで最終応答を生成する役目。"""
    print("--- 最終応答生成ノード (final_response_node) 実行 ---")
    api_key = state['api_key']

    # ★★★ ここからが修正箇所 ★★★
    # stateからユーザーが選択したモデル名を取得。指定がなければProをデフォルトにする。
    final_model_to_use = state.get("final_model_name", "gemini-2.5-pro")
    print(f"  - ユーザー指定の最終応答モデル: '{final_model_to_use}' を使用します。")

    # 取得したモデル名でLLMを初期化
    llm_final = get_configured_llm(final_model_to_use, api_key)
    # ★★★ 修正ここまで ★★★

    print(f"  - {final_model_to_use}への入力メッセージ数: {len(state['messages'])}")
    try:
        response = llm_final.invoke(state['messages']) # 修正したllm_finalを使用
        return {"messages": [response]}
    except Exception as e:
        print(f"  - 最終応答生成ノードでエラー: {e}")
        return {"messages": [AIMessage(content=f"[エラー：最終応答の生成中に問題が発生しました。詳細: {e}]")]}


def should_call_tool(state: AgentState):
    """【変更なし】最後のメッセージにツール呼び出しがあるか「だけ」をチェックする。"""
    print("--- ルーティング判断 (should_call_tool) 実行 ---")
    last_message = state['messages'][-1] if state['messages'] else None

    if last_message and hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        print("  - 判断: ツール呼び出しあり。call_tool_node へ。")
        return "call_tool"
    else:
        print("  - 判断: ツール呼び出しなし。final_response_node へ。")
        return "final_response"

# --- グラフ構築 (変更なし) ---
workflow = StateGraph(AgentState)

workflow.add_node("tool_router", tool_router_node)
workflow.add_node("call_tool", call_tool_node)
workflow.add_node("final_response", final_response_node)

workflow.set_entry_point("tool_router")

workflow.add_conditional_edges(
    "tool_router",
    should_call_tool,
    {
        "call_tool": "call_tool",
        "final_response": "final_response"
    }
)

workflow.add_edge("call_tool", "final_response")
workflow.add_edge("final_response", END)

app = workflow.compile()

# agent/graph.py の一番下に、このコードブロックを貼り付けてください
# (既存の web_search_tool 定義がここにあるはずなので、それは維持する)
from tavily import TavilyClient # tavilyのインポートが必要な場合があるので念のため

@tool
def web_search_tool(query: str) -> str:
    """ユーザーからのクエリに基づいて、最新の情報を得るためにWeb検索を実行します。"""
    print(f"--- Web検索ツール実行 (Query: '{query}') ---")
    # 環境変数のTAVILY_API_KEYを直接参照するように修正
    tavily_api_key = os.getenv("TAVILY_API_KEY")
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
        # 実行時のエラーをより詳細に補足
        print(f"  - Web検索ツールでエラー: {e}")
        traceback.print_exc()
        return f"[エラー：Web検索中に問題が発生しました。詳細: {e}]"
