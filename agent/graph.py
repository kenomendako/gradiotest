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
    final_token_count: int
    # reflection: str # 不要になったキー
    pass # AgentStateの定義はこれ以上変更なし

def get_configured_llm(model_name: str, api_key: str, bind_tools: List = None):
    llm = ChatGoogleGenerativeAI(model=model_name, google_api_key=api_key)
    if bind_tools:
        llm = llm.bind_tools(bind_tools)
        print(f"  - モデル '{model_name}' に道具: {[tool.name for tool in bind_tools]} をバインドしました。")
    else:
        print(f"  - モデル '{model_name}' は道具なしで初期化されました。")
    return llm

# ▼▼▼【重要】新しい「魂の統合」ノードを定義 ▼▼▼
def agent_node(state: AgentState):
    """
    思考と行動の全てを担う、唯一の判断ノード。
    gemini-2.5-proがツールを直接呼び出すか、最終応答を返すかを決定する。
    """
    print("--- エージェントノード (agent_node) 実行 ---")
    api_key = state['api_key']
    # UIで選択されたモデル（Proのはず）を最終判断役として使用
    model_name = state.get("final_model_name", "gemini-2.5-pro")

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

    # Proモデルに全てのツールをバインド
    llm_pro_with_tools = get_configured_llm(model_name, api_key, available_tools)

    # トークン数を計算
    total_tokens = gemini_api.count_tokens_from_lc_messages(
        state['messages'], model_name, api_key
    )
    print(f"  - 合計入力トークン数を計算しました: {total_tokens}")

    print(f"  - {model_name}への入力メッセージ数: {len(state['messages'])}")
    try:
        # 全権を委任されたProが思考・判断・行動する
        response = llm_pro_with_tools.invoke(state['messages'])
        return {"messages": [response], "final_token_count": total_tokens}
    except Exception as e:
        print(f"  - エージェントノードでエラー: {e}")
        error_message = f"[エラー：エージェントの実行中に問題が発生しました。詳細: {e}]"
        return {"messages": [AIMessage(content=error_message)], "final_token_count": 0}

# call_tool_nodeは変更なし
def call_tool_node(state: AgentState):
    # (この関数は変更なし)
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
                # ▼▼▼ ここからが最重要修正点 ▼▼▼
                # LLMが生成した引数に、状態から取得した正しい値を上書き・追加する
                if tool_name in ["diary_search_tool", "conversation_memory_search_tool", "add_to_notepad", "update_notepad", "delete_from_notepad", "read_full_notepad"]:
                    # この上書きにより、LLMが 'character_name' を間違えても必ず正しい値に修正される
                    tool_args["character_name"] = state.get("character_name")
                    print(f"    - 引数に正しいキャラクター名 '{tool_args['character_name']}' を注入/上書きしました。")

                # RAGツールにはAPIキーも渡す (これも上書き)
                if tool_name in ["diary_search_tool", "conversation_memory_search_tool"]:
                    tool_args["api_key"] = state.get("api_key")
                    print(f"    - 引数にAPIキーを注入/上書きしました。")
                # ▲▲▲ 修正ここまで ▲▲▲

                output = tool_to_call.invoke(tool_args)
            except Exception as e:
                output = f"[エラー：道具'{tool_name}'の実行に失敗しました。詳細: {e}]"
                traceback.print_exc()
        tool_messages.append(ToolMessage(content=str(output), tool_call_id=tool_call_id))
    return {"messages": tool_messages}

# should_call_toolは変更なし
def should_call_tool(state: AgentState):
    # (この関数は変更なし)
    print("--- ルーティング判断 (should_call_tool) 実行 ---")
    last_message = state['messages'][-1] if state['messages'] else None
    if last_message and hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        print("  - 判断: ツール呼び出しあり。call_tool_node へ。")
        return "call_tool"
    else:
        print("  - 判断: ツール呼び出しなし。final_response_node へ。")
        return "final_response"

# ▼▼▼ グラフの再構築 ▼▼▼
workflow = StateGraph(AgentState)

# ノードは agent と call_tool の2つだけ
workflow.add_node("agent", agent_node)
workflow.add_node("call_tool", call_tool_node)

# エントリーポイントは agent
workflow.set_entry_point("agent")

# agentノードからの分岐ロジック
workflow.add_conditional_edges(
    "agent",
    should_call_tool,
    {
        "call_tool": "call_tool",
        # ツールを呼ばない場合（最終応答）はグラフ終了
        "final_response": END
    }
)

# ツール実行後、再度 agent に戻り、次の行動を考えさせる (ReActループ)
workflow.add_edge("call_tool", "agent")

app = workflow.compile()
# ▲▲▲ グラフ再構築ここまで ▲▲▲

# web_search_toolの定義は変更なし
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
