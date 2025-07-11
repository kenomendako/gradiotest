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
from agent.prompts import MEMORY_WEAVER_PROMPT_TEMPLATE
from tools.web_tools import read_url_tool
from tools.notepad_tools import add_to_notepad, update_notepad, delete_from_notepad, read_full_notepad


# AgentStateに、要約を格納するための新しいフィールドを追加
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    character_name: str
    api_key: str
    final_model_name: str
    final_token_count: int
    synthesized_context: SystemMessage


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


def memory_weaver_node(state: AgentState):
    """
    グラフの最初に実行され、長期記憶と短期記憶を要約し、
    判断役（Flash）に渡すための短期コンテキストを生成する。
    """
    print("--- 魂を織りなす記憶ノード (memory_weaver_node) 実行 ---")

    messages = state['messages']
    character_name = state['character_name']
    api_key = state['api_key']

    RECENT_HISTORY_COUNT = 30

    # クエリ生成ロジックの修正
    # HumanMessageのcontentが文字列の場合とリスト（マルチモーダル）の場合を考慮
    raw_last_message_content = ""
    last_human_message = next((msg for msg in reversed(messages) if isinstance(msg, HumanMessage)), None)
    if last_human_message:
        if isinstance(last_human_message.content, str):
            raw_last_message_content = last_human_message.content
        elif isinstance(last_human_message.content, list):
            # テキストパートのみを抽出して結合
            text_parts = [part['text'] for part in last_human_message.content if isinstance(part, dict) and part.get('type') == 'text']
            raw_last_message_content = " ".join(text_parts)
            if not raw_last_message_content.strip() and any(part.get('type') != 'text' for part in last_human_message.content):
                 # テキスト以外の部分（例: 画像）があり、テキストが空の場合
                raw_last_message_content = "（ファイル添付、または、テキスト以外のコンテンツ）"


    search_query = raw_last_message_content
    if len(search_query) > 500: # クエリが長すぎる場合は切り詰める
        search_query = search_query[:500] + "..."
    if not search_query.strip(): # 空白文字のみ、または完全に空の場合
        search_query = "（ユーザーからの添付ファイル、または、空のメッセージ）"

    print(f"  - [Memory Weaver] 生成された検索クエリ: '{search_query}'")

    long_term_memories = rag_manager.search_conversation_memory_for_summary(
        character_name=character_name,
        query=search_query, # 最適化されたクエリを使用
        api_key=api_key
    )

    recent_history_messages = messages[-RECENT_HISTORY_COUNT:]
    recent_history_str = "\n".join([f"- {msg.type}: {msg.content}" for msg in recent_history_messages])
    print(f"  - 直近の会話履歴 {len(recent_history_messages)} 件を、要約の、材料とします。")

    summarizer_prompt = MEMORY_WEAVER_PROMPT_TEMPLATE.format(
        character_name=character_name,
        long_term_memories=long_term_memories,
        recent_history=recent_history_str
    )

    llm_flash = get_configured_llm("gemini-2.5-flash", api_key) # モデルバージョンを規約通りに
    summary_text = llm_flash.invoke(summarizer_prompt).content

    print(f"  - 生成された状況サマリー:\n{summary_text}")

    synthesized_context_message = SystemMessage(content=f"【現在の状況サマリー】\n{summary_text}")

    return {"synthesized_context": synthesized_context_message}


def tool_router_node(state: AgentState):
    """
    ツールを使うかどうかの判断に特化したノード。
    memory_weaver_nodeが生成した「要約コンテキスト」を使用する。
    """
    print("--- ツールルーターノード (tool_router_node) 実行 ---")

    messages_for_router = []
    original_messages = state['messages']

    system_prompt = next((msg for msg in original_messages if isinstance(msg, SystemMessage)), None)
    if system_prompt:
        messages_for_router.append(system_prompt)

    messages_for_router.append(state['synthesized_context'])

    last_user_message = next((msg for msg in reversed(original_messages) if isinstance(msg, HumanMessage)), None)
    if last_user_message:
        messages_for_router.append(last_user_message) # 完全なユーザーメッセージ（ファイル含む）をルーターに渡す

    api_key = state['api_key']
    available_tools = [
        rag_manager.diary_search_tool,
        rag_manager.conversation_memory_search_tool,
        web_search_tool,
        read_url_tool,
        add_to_notepad,
        update_notepad,
        delete_from_notepad,
        read_full_notepad
    ]

    llm_flash_with_tools = get_configured_llm("gemini-2.5-flash", api_key, available_tools) # モデルバージョンを規約通りに

    print(f"  - Flashへの入力メッセージ数: {len(messages_for_router)}")
    response = llm_flash_with_tools.invoke(messages_for_router)

    if hasattr(response, 'tool_calls') and response.tool_calls:
        print("  - Flashが道具の使用を決定。")
        return {"messages": [response]}
    else:
        print("  - Flashは道具を使用しないと判断。最終応答生成へ。")
        return {} # ツールを使わない場合は {} を返す


def final_response_node(state: AgentState):
    """
    彼らしい応答を生成することに特化した最終ノード。
    Proに「完全な会話履歴」を与え、深く豊かな応答を生成させる。
    """
    print("--- 最終応答生成ノード (final_response_node) 実行 ---")
    api_key = state['api_key']
    final_model_to_use = state.get("final_model_name", "gemini-2.5-pro") # モデルバージョンを規約通りに

    llm_final = get_configured_llm(final_model_to_use, api_key)

    # Proには、要約コンテキストと、完全な履歴を渡す
    # synthesized_context は SystemMessage なので、そのままリストの先頭に追加できる
    messages_for_final_response = [state['synthesized_context']] + state['messages']

    total_tokens = gemini_api.count_tokens_from_lc_messages(
        messages_for_final_response, final_model_to_use, api_key
    )
    print(f"  - 最終的な合計入力トークン数（要約＋完全な履歴）を計算しました: {total_tokens}")

    print(f"  - {final_model_to_use}への入力メッセージ数（要約＋完全な履歴）: {len(messages_for_final_response)}")
    try:
        response = llm_final.invoke(messages_for_final_response)
        return {"messages": [response], "final_token_count": total_tokens}
    except Exception as e:
        print(f"  - 最終応答生成ノードでエラー: {e}")
        return {"messages": [AIMessage(content=f"[エラー：最終応答の生成中に問題が発生しました。詳細: {e}]")], "final_token_count": 0}


def call_tool_node(state: AgentState):
    last_message = state['messages'][-1] # tool_routerからAIMessage(tool_calls=...) が入る想定
    if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
        return {} # ツールコールがない場合は何もせず、次の判断へ（通常は発生しないはず）
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
                # 必要な引数を注入
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
    # tool_router_node からの出力 (state['messages'] の最後) を確認
    last_message = state['messages'][-1] if state['messages'] else None

    # tool_routerがツール使用を決定した場合、last_messageはAIMessageでtool_callsを持つ
    if isinstance(last_message, AIMessage) and hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        print("  - 判断: ツール呼び出しあり。call_tool_node へ。")
        return "call_tool"
    else:
        # ツールを使用しない場合や、他のケース（エラーなど）は最終応答へ
        print("  - 判断: ツール呼び出しなし。final_response_node へ。")
        return "final_response"


# グラフの構築
workflow = StateGraph(AgentState)
workflow.add_node("memory_weaver", memory_weaver_node)
workflow.add_node("tool_router", tool_router_node)
workflow.add_node("call_tool", call_tool_node)
workflow.add_node("final_response", final_response_node)

# エントリーポイントを memory_weaver に設定
workflow.add_edge(START, "memory_weaver") # STARTからmemory_weaverへ

workflow.add_edge("memory_weaver", "tool_router")
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
