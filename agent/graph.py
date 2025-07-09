# agent/graph.py

import os
import traceback
from typing import TypedDict, List
from typing_extensions import Annotated
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END, START, add_messages
from langchain_core.tools import tool

import gemini_api
import rag_manager
from tools.web_tools import read_url_tool
from tools.notepad_tools import add_to_notepad, update_notepad, delete_from_notepad, read_full_notepad # ★ 追加

class AgentState(TypedDict):
    """エージェントの状態を定義するクラス"""
    messages: Annotated[list, add_messages]
    character_name: str
    api_key: str
    final_model_name: str
    final_token_count: int  # 最終的な合計トークン数を格納するキーを追加

def get_configured_llm(model_name: str, api_key: str, bind_tools: List = None):
    llm = ChatGoogleGenerativeAI(model=model_name, google_api_key=api_key)
    if bind_tools:
        llm = llm.bind_tools(bind_tools)
        print(f"  - モデル '{model_name}' に道具: {[tool.name for tool in bind_tools]} をバインドしました。")
    else:
        print(f"  - モデル '{model_name}' は道具なしで初期化されました。")
    return llm

def tool_router_node(state: AgentState):
    print("--- ツールルーターノード (tool_router_node) 実行 ---")
    api_key = state['api_key']
    available_tools = [
        rag_manager.diary_search_tool,
        rag_manager.conversation_memory_search_tool,
        web_search_tool, # web_search_tool は直接定義されている
        read_url_tool,
        add_to_notepad,       # ★ 追加
        update_notepad,     # ★ 追加
        delete_from_notepad,  # ★ 追加
        read_full_notepad     # ★ 追加
    ]
    llm_flash_with_tools = get_configured_llm("gemini-2.5-flash", api_key, available_tools)
    response = llm_flash_with_tools.invoke(state['messages'])
    if hasattr(response, 'tool_calls') and response.tool_calls:
        print("  - Flashが道具の使用を決定。")
        return {"messages": [response]}
    else:
        print("  - Flashは道具を使用しないと判断。")
        return {}

def call_tool_node(state: AgentState):
    last_message = state['messages'][-1]
    if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
        return {}
    print(f"--- 道具実行ノード (call_tool_node) 実行 ---")
    tool_messages = []
    available_tools_map = {
        "diary_search_tool": rag_manager.diary_search_tool,
        "conversation_memory_search_tool": rag_manager.conversation_memory_search_tool,
        "web_search_tool": web_search_tool, # web_search_tool は直接定義されている
        "read_url_tool": read_url_tool,
        "add_to_notepad": add_to_notepad,             # ★ 追加
        "update_notepad": update_notepad,           # ★ 追加
        "delete_from_notepad": delete_from_notepad,   # ★ 追加
        "read_full_notepad": read_full_notepad        # ★ 追加
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
                # ★ character_name を渡す条件に notepad_tools を追加
                if tool_name in ["diary_search_tool", "conversation_memory_search_tool", "add_to_notepad", "update_notepad", "delete_from_notepad", "read_full_notepad"]:
                    tool_args.update({"character_name": state.get("character_name")})
                # RAGツールにはAPIキーも渡す
                if tool_name in ["diary_search_tool", "conversation_memory_search_tool"]:
                    tool_args.update({"api_key": state.get("api_key")})
                output = tool_to_call.invoke(tool_args)
            except Exception as e:
                output = f"[エラー：道具'{tool_name}'の実行に失敗しました。詳細: {e}]"
                traceback.print_exc()
        tool_messages.append(ToolMessage(content=str(output), tool_call_id=tool_call_id))
    return {"messages": tool_messages}

def final_response_node(state: AgentState):
    """【変更】最終応答生成。合計トークン数を計算し、Stateに保存する。"""
    print("--- 最終応答生成ノード (final_response_node) 実行 ---")
    api_key = state['api_key']
    final_model_to_use = state.get("final_model_name", "gemini-2.5-pro")

    # ツール実行後の全コンテキストを含んだ合計トークン数を計算
    total_tokens = gemini_api.count_tokens_from_lc_messages(
        state['messages'], final_model_to_use, api_key
    )
    print(f"  - 最終的な合計入力トークン数を計算しました: {total_tokens}")

    llm_final = get_configured_llm(final_model_to_use, api_key)

    print(f"  - {final_model_to_use}への入力メッセージ数: {len(state['messages'])}")
    try:
        response = llm_final.invoke(state['messages'])
        # 応答メッセージと、計算したトークン数をStateに返す
        return {"messages": [response], "final_token_count": total_tokens}
    except Exception as e:
        print(f"  - 最終応答生成ノードでエラー: {e}")
        return {"messages": [AIMessage(content=f"[エラー：最終応答の生成中に問題が発生しました。詳細: {e}]")], "final_token_count": 0}

def should_call_tool(state: AgentState):
    print("--- ルーティング判断 (should_call_tool) 実行 ---")
    last_message = state['messages'][-1] if state['messages'] else None
    if last_message and hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        print("  - 判断: ツール呼び出しあり。call_tool_node へ。")
        return "call_tool"
    else:
        print("  - 判断: ツール呼び出しなし。final_response_node へ。")
        return "final_response"

workflow = StateGraph(AgentState)
workflow.add_node("tool_router", tool_router_node)
workflow.add_node("call_tool", call_tool_node)
workflow.add_node("final_response", final_response_node)
workflow.set_entry_point("tool_router")
workflow.add_conditional_edges(
    "tool_router",
    should_call_tool,
    {"call_tool": "call_tool", "final_response": "final_response"}
)
workflow.add_edge("call_tool", "final_response")
workflow.add_edge("final_response", END)
app = workflow.compile()

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
