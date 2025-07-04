# agent/graph.py の内容を、このコードブロックで完全に置き換えてください

import os
import traceback
from typing import TypedDict, List
from typing_extensions import Annotated
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END, START, add_messages
from langchain_core.tools import tool

import config_manager
import rag_manager
from tools.web_tools import read_url_tool, web_search_tool # web_search_toolもインポート

# --- AgentState定義 (変更なし) ---
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    character_name: str
    api_key: str

# --- LLM初期化関数 (変更なし) ---
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

# ★★★ ここからが最後の、そして真の、修正点です ★★★

def tool_router_node(state: AgentState):
    """【役割修正①】Flashを使い、ツール呼び出しを返すか、何も返さないかのどちらかを行う。"""
    print("--- ツールルーターノード (tool_router_node) 実行 ---")
    api_key = state['api_key']

    available_tools = [rag_manager.search_tool, web_search_tool, read_url_tool]
    llm_flash_with_tools = get_configured_llm("gemini-2.5-flash", api_key, available_tools)

    response = llm_flash_with_tools.invoke(state['messages'])

    # ★★★ 最重要修正点 ★★★
    # Flashがツール呼び出しを返した場合「のみ」、そのメッセージを履歴に追加する。
    # 通常のおしゃべり応答は、完全に無視する。
    if hasattr(response, 'tool_calls') and response.tool_calls:
        print("  - Flashが道具の使用を決定。")
        return {"messages": [response]}
    else:
        # おしゃべりな応答は無視し、Stateを更新しない
        print("  - Flashは道具を使用しないと判断。")
        return {} # 空の辞書を返すことで、messagesは変更されない

def call_tool_node(state: AgentState):
    """【変更なし】ツールを実行する役目。"""
    last_message = state['messages'][-1]
    # このチェックは念のため残す
    if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
        return {}

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
                if tool_name == "search_tool":
                    tool_args.update({"character_name": state.get("character_name"), "api_key": state.get("api_key")})
                output = tool_to_call.invoke(tool_args)
            except Exception as e:
                output = f"[エラー：道具'{tool_name}'の実行に失敗しました。詳細: {e}]"

        tool_messages.append(ToolMessage(content=str(output), tool_call_id=tool_call_id))

    return {"messages": tool_messages}

def final_response_node(state: AgentState):
    """【変更なし】Proモデルで最終応答を生成する役目。"""
    print("--- 最終応答生成ノード (final_response_node) 実行 ---")
    api_key = state['api_key']
    llm_pro = get_configured_llm("gemini-2.5-pro", api_key)

    print(f"  - Proモデルへの入力メッセージ数: {len(state['messages'])}")
    try:
        response = llm_pro.invoke(state['messages'])
        return {"messages": [response]}
    except Exception as e:
        print(f"  - 最終応答生成ノードでエラー: {e}")
        # traceback.print_exc() # トレースバックはログが長くなるので一旦コメントアウト
        return {"messages": [AIMessage(content=f"[エラー：最終応答の生成中に問題が発生しました。詳細: {e}]")]}


def should_call_tool(state: AgentState):
    """【役割修正②】最後のメッセージにツール呼び出しがあるか「だけ」をチェックする。"""
    print("--- ルーティング判断 (should_call_tool) 実行 ---")
    last_message = state['messages'][-1] if state['messages'] else None

    # tool_router_nodeがツール呼び出しメッセージを追加した場合のみ、last_messageはtool_callsを持つ
    if last_message and hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        print("  - 判断: ツール呼び出しあり。call_tool_node へ。")
        return "call_tool"
    else:
        # それ以外（ツール呼び出しがなかった）場合は、最終応答へ
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
