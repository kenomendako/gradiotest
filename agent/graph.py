# agent/graph.py

import os
import traceback
from typing import TypedDict, List
from typing_extensions import Annotated
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END, START, add_messages
from langchain_core.tools import tool

import config_manager
import gemini_api
import rag_manager
from tools.web_tools import read_url_tool # web_tools から read_url_tool をインポートするよう修正
from tools.notepad_tools import add_to_notepad, update_notepad, delete_from_notepad, read_full_notepad

# ▼▼▼【重要】ここに、参照されていた定数の定義を追加します▼▼▼
TOOL_ROUTER_PROMPT_STRICT = """あなたは、ユーザーの指示やこれまでの実行結果を分析し、次に実行すべきツールを判断することに特化した、高度なAIルーターです。
あなたの唯一の仕事は、ツールを呼び出すためのJSON形式の指示を出力するか、これ以上のツール実行は不要と判断した場合に沈黙（ツール呼び出しをしない）することです。
絶対に、あなた自身の言葉で応答メッセージを生成してはいけません。思考や挨拶、相槌も一切不要です。

【思考プロセス】
1.  ユーザーの最新のメッセージと、直前のツールの実行結果（もしあれば）を注意深く観察する。
2.  ユーザーの最終的な目的を達成するために、次に実行すべきツールが何かを判断する。
3.  もし実行すべきツールがあれば、そのツールを呼び出すためのJSONを生成する。
4.  全てのタスクが完了し、これ以上のツール実行は不要だと確信した場合にのみ、沈黙する。
"""
# ▲▲▲ 定義ここまで ▲▲▲


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    character_name: str
    api_key: str
    final_model_name: str
    final_token_count: int


def get_configured_llm(model_name: str, api_key: str, bind_tools: List = None):
    """
    モデルを初期化する。
    安全設定は、ライブラリのデフォルト値に完全に委ねる。
    """
    print(f"  - 安全設定をLangChainのデフォルト値に委ねてモデルを初期化します。")
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


def tool_router_node(state: AgentState):
    """
    ツールを使うかどうかの判断に特化したノード。
    Flashに渡す情報を、「最後のユーザー指示以降」の、短期的な、履歴に、限定する。
    """
    print("--- ツールルーターノード (tool_router_node) 実行 ---")

    messages_for_router = []
    original_messages = state['messages']

    system_prompt = next((msg for msg in original_messages if isinstance(msg, SystemMessage)), None)
    if system_prompt:
        messages_for_router.append(system_prompt)
    else:
        messages_for_router.append(SystemMessage(content=TOOL_ROUTER_PROMPT_STRICT))

    last_human_message_index = -1
    for i in range(len(original_messages) - 1, -1, -1):
        if isinstance(original_messages[i], HumanMessage):
            last_human_message_index = i
            break

    if last_human_message_index != -1:
        recent_context = original_messages[last_human_message_index:]
        messages_for_router.extend(recent_context)
        print(f"  - Flashに最後のユーザー指示以降の{len(recent_context)}件のメッセージを「集中モード用コンテキスト」として使用します。")
    else:
        # ユーザーメッセージが見つからない場合（通常はありえないが念のため）、全履歴を使用
        messages_for_router.extend(original_messages)
        print("  - 警告: ユーザーメッセージが見つかりません。全履歴をコンテキストとして使用します。")

    api_key = state['api_key']
    available_tools = [
        rag_manager.diary_search_tool,
        rag_manager.conversation_memory_search_tool,
        web_search_tool, # web_search_tool はこのファイル内で定義されているのでそのまま
        read_url_tool,   # tools.web_tools からインポート
        add_to_notepad,
        update_notepad,
        delete_from_notepad,
        read_full_notepad
    ]
    llm_flash_with_tools = get_configured_llm("gemini-2.5-flash", api_key, available_tools)

    print(f"  - Flashへの入力メッセージ数: {len(messages_for_router)}")
    response = llm_flash_with_tools.invoke(messages_for_router)

    if hasattr(response, 'tool_calls') and response.tool_calls:
        print("  - Flashが道具の使用を決定。")
        return {"messages": [response]}
    else:
        print("  - Flashは道具を使用しないと判断。最終応答生成へ。")
        return {}


def final_response_node(state: AgentState):
    """
    彼らしい応答を生成することに特化した最終ノード。
    Proに「完全な会話履歴」を与え、深く豊かな応答を生成させる。
    """
    print("--- 最終応答生成ノード (final_response_node) 実行 ---")
    api_key = state['api_key']
    final_model_to_use = state.get("final_model_name", "gemini-2.5-pro")

    llm_final = get_configured_llm(final_model_to_use, api_key)

    messages_for_final_response = state['messages'] # Proには完全な履歴を渡す

    total_tokens = gemini_api.count_tokens_from_lc_messages(
        messages_for_final_response, final_model_to_use, api_key
    )
    print(f"  - 最終的な合計入力トークン数（完全な履歴）を計算しました: {total_tokens}")

    print(f"  - {final_model_to_use}への入力メッセージ数（完全な履歴）: {len(messages_for_final_response)}")
    try:
        response = llm_final.invoke(messages_for_final_response)
        return {"messages": [response], "final_token_count": total_tokens}
    except Exception as e:
        print(f"  - 最終応答生成ノードでエラー: {e}")
        return {"messages": [AIMessage(content=f"[エラー：最終応答の生成中に問題が発生しました。詳細: {e}]")], "final_token_count": 0}


def call_tool_node(state: AgentState):
    last_message = state['messages'][-1]
    if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
        return {}
    print(f"--- 道具実行ノード (call_tool_node) 実行 ---")
    tool_messages = []
    available_tools_map = {
        "diary_search_tool": rag_manager.diary_search_tool,
        "conversation_memory_search_tool": rag_manager.conversation_memory_search_tool,
        "web_search_tool": web_search_tool,
        "read_url_tool": read_url_tool,
        "add_to_notepad": add_to_notepad,
        "update_notepad": update_notepad,
        "delete_from_notepad": delete_from_notepad,
        "read_full_notepad": read_full_notepad
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
                if tool_name in ["diary_search_tool", "conversation_memory_search_tool", "add_to_notepad", "update_notepad", "delete_from_notepad", "read_full_notepad"]:
                    tool_args["character_name"] = state.get("character_name")
                if tool_name in ["diary_search_tool", "conversation_memory_search_tool"]:
                    tool_args["api_key"] = state.get("api_key")
                output = tool_to_call.invoke(tool_args)
            except Exception as e:
                output = f"[エラー：道具'{tool_name}'の実行に失敗しました。詳細: {e}]"
                traceback.print_exc()
        tool_messages.append(ToolMessage(content=str(output), tool_call_id=tool_call_id, name=tool_name))
    return {"messages": tool_messages}


def should_call_tool(state: AgentState):
    print("--- ルーティング判断 (should_call_tool) 実行 ---")
    last_message = state['messages'][-1] if state['messages'] else None
    if isinstance(last_message, AIMessage) and hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        print("  - 判断: ツール呼び出しあり。call_tool_node へ。")
        return "call_tool"
    else:
        print("  - 判断: ツール呼び出しなし。final_response_node へ。")
        return "final_response"


# グラフの構築
workflow = StateGraph(AgentState)
workflow.add_node("tool_router", tool_router_node)
workflow.add_node("call_tool", call_tool_node)
workflow.add_node("final_response", final_response_node)

# workflow.set_entry_point("tool_router") # LangGraphの推奨に従い、add_edge(START,...)を使用
workflow.add_edge(START, "tool_router")

workflow.add_conditional_edges(
    "tool_router",
    should_call_tool,
    {
        "call_tool": "call_tool",
        "final_response": "final_response"
    }
)
workflow.add_edge("call_tool", "tool_router") # ツール実行後、再度tool_routerに戻る
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
