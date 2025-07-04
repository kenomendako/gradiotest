import os
import traceback
from typing import TypedDict, List, Optional
from typing_extensions import Annotated # または from typing import Annotated (Python 3.9+)

# LangChain/LangGraphに最適化された、正しい、ライブラリを、インポートする
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage # ToolMessageもインポート

from langgraph.graph import StateGraph, END, START, add_messages # add_messages をインポート
from tavily import TavilyClient

import config_manager
import rag_manager
from tools.web_tools import read_url_tool # read_url_tool をインポート

# --- 新しい、魂の、定義書 (State) ---
class AgentState(TypedDict):
    # ★★★ この一行が、全てを、解決する ★★★
    messages: Annotated[list, add_messages]
    character_name: str # キャラクター名は引き続き必要
    api_key: str # Google APIキーも引き続き必要
    # perceived_content: str # これは messages に統合される
    # rag_results: Optional[str] # これらはToolMessageとしてmessagesに格納
    # web_search_results: Optional[str] # これらはToolMessageとしてmessagesに格納
    # response_outline: Optional[str] # 今回のアーキテクチャでは未使用
    # final_response: str # messages[-1].content で取得
    # input_parts: List[any] # messages に統合
    # route_decision: str # should_continue_logic で直接判断するためStateには不要

# ヘルパー関数や他のノードは、次のステップで追加します。
# 現時点では、グラフの基本構造とState定義のみ。

# --- 新しい、ノードの、定義 ---

def get_configured_llm(model_name: str, api_key: str, bind_tools: Optional[List] = None):
    """指定されたモデル名とAPIキーでLLMを初期化し、オプションでツールをバインドする"""
    llm = ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=api_key,
        convert_system_message_to_human=True,
        # safety_settings=config_manager.SAFETY_CONFIG # 必要に応じて追加
    )
    if bind_tools:
        llm = llm.bind_tools(bind_tools)
        print(f"  - モデル '{model_name}' に道具: {[tool.name for tool in bind_tools]} をバインドしました。")
    else:
        print(f"  - モデル '{model_name}' は道具なしで初期化されました。")
    return llm

def decide_tool_use_node(state: AgentState):
    """【ツール判断】gemini-2.5-flash を使用してツール使用を判断するノード"""
    print("--- ツール使用判断ノード (decide_tool_use_node) 実行 ---")
    api_key = state.get('api_key')
    if not api_key:
        return {"messages": [AIMessage(content="[エラー: APIキーが設定されていません。ツール判断ノード]")]}

    active_tools = []
    if hasattr(rag_manager, 'search_tool'):
        active_tools.append(rag_manager.search_tool)
    if 'web_search_tool' in globals() and callable(globals()['web_search_tool']):
        active_tools.append(globals()['web_search_tool'])
    active_tools.append(read_url_tool)

    llm_flash_with_tools = get_configured_llm("gemini-2.5-flash", api_key, active_tools) # モデル名を gemini-2.5-flash に修正

    if not state['messages']:
        print("  - 警告: メッセージ履歴が空です。ツール判断が不安定になる可能性があります。")
        # 空の応答を返すか、エラーメッセージを生成
        return {"messages": [AIMessage(content="[メッセージ履歴が空のため、ツール判断できませんでした]")]}

    print(f"  - Flashモデルへの入力メッセージ数: {len(state['messages'])}")
    try:
        response_message = llm_flash_with_tools.invoke(state['messages'])
        return {"messages": [response_message]}
    except Exception as e:
        print(f"  - ツール使用判断ノードでエラー: {e}")
        traceback.print_exc()
        error_message = AIMessage(content=f"[エラー：ツール使用判断中に問題が発生しました。詳細: {e}]")
        return {"messages": [error_message]}

def generate_final_response_node(state: AgentState):
    """【最終応答生成】gemini-2.5-pro を使用して最終的な応答を生成するノード"""
    print("--- 最終応答生成ノード (generate_final_response_node) 実行 ---")
    api_key = state.get('api_key')
    if not api_key:
        return {"messages": [AIMessage(content="[エラー: APIキーが設定されていません。最終応答生成ノード]")]}

    llm_pro = get_configured_llm("gemini-2.5-pro", api_key) # ツールはバインドしない

    if not state['messages']:
        print("  - 警告: メッセージ履歴が空です。最終応答が不安定になる可能性があります。")
        return {"messages": [AIMessage(content="[メッセージ履歴が空のため、最終応答を生成できませんでした]")]}

    print(f"  - Proモデルへの入力メッセージ数: {len(state['messages'])}")
    try:
        # ここでは、ツール呼び出しを期待しない純粋な応答生成を行う
        response_message = llm_pro.invoke(state['messages'])
        # tool_calls が含まれていないことを確認（または無視）
        if hasattr(response_message, 'tool_calls') and response_message.tool_calls:
            print("  - 警告: 最終応答生成モデルが予期せずツール呼び出しを返しました。無視します。")
            response_message.tool_calls = None # 強制的に削除
        return {"messages": [response_message]}
    except Exception as e:
        print(f"  - 最終応答生成ノードでエラー: {e}")
        traceback.print_exc()
        error_message = AIMessage(content=f"[エラー：最終応答生成中に問題が発生しました。詳細: {e}]")
        return {"messages": [error_message]}

# --- call_tool_node の、修正 (内容は変更なし、呼び出し元が変わるだけ) ---
def call_tool_node(state: AgentState):
    """【配線修正済】AIが使用を決めたツールを正しく呼び出し、実行するノード"""
    # messagesが空、あるいは最後のメッセージが存在しない場合は何もしない
    if not state['messages'] or not state['messages'][-1]:
        print("  - 警告: call_tool_nodeに渡されたメッセージリストが空、または最後のメッセージがありません。")
        return {"messages": []}

    last_message = state['messages'][-1]

    if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
        # ツール呼び出しがない場合は、空のリストを返してStateを壊さず、次のcall_modelに処理を委ねる
        print("  - 道具呼び出しなし。スキップします。")
        return {"messages": []}

    print(f"--- 道具実行ノード (Tool) 実行 ---")
    tool_messages: List[ToolMessage] = [] # 型ヒントを明確化

    # ★★★【最後の真実】利用可能な、全ての、道具を、辞書として、定義する ★★★
    available_tools = {
        "search_tool": rag_manager.search_tool, # rag_manager.py の search_tool
        "web_search_tool": web_search_tool,     # このファイルのグローバルスコープの web_search_tool
        "read_url_tool": read_url_tool          # 追加したURL読み取りツール
    }

    for tool_call in last_message.tool_calls:
        tool_name = tool_call.get("name")
        tool_args = tool_call.get("args", {}) # argsがない場合も考慮し、デフォルトは空辞書
        tool_call_id = tool_call.get("id")

        if not tool_call_id: # LangChainの規約上、tool_call_idは必須
            print(f"  - 警告: tool_callにIDがありません。スキップします。Tool call: {tool_call}")
            # エラーとしてToolMessageを返すこともできるが、ここではスキップ
            continue

        print(f"  - 道具: {tool_name} を使用 (ID: {tool_call_id})")
        print(f"    - 引数: {tool_args}")

        # ★★★ 辞書から、正しい、道具を、取り出す ★★★
        tool_to_call = available_tools.get(tool_name)

        if not tool_to_call:
            print(f"  - 警告: 不明な道具 '{tool_name}' が指定されました。")
            tool_messages.append(ToolMessage(content=f"Error: Unknown tool '{tool_name}'", tool_call_id=tool_call_id))
            continue

        try:
            # ツールを実行し、結果を得る
            # rag_search_tool のために、args に character_name と api_key を追加する
            # web_search_tool は 'query' のみのはずなので、影響はない
            final_tool_args = tool_args
            if tool_name == "search_tool": # RAGツールの場合のみ追加引数を考慮
                final_tool_args = {
                    **tool_args,
                    "character_name": state.get("character_name"),
                    "api_key": state.get("api_key") # APIキーも渡す
                }

            observation = tool_to_call.invoke(final_tool_args)
            # ★★★【最後の真実】過剰な装飾をやめ、ツールの生の出力を、そのまま、contentとして、渡す ★★★
            tool_messages.append(
                ToolMessage(
                    content=str(observation),
                    tool_call_id=tool_call['id']
                )
            )
        except Exception as e:
            print(f"  - 道具 '{tool_name}' の実行中にエラー: {e}")
            traceback.print_exc()
            tool_messages.append(ToolMessage(content=f"[エラー：道具'{tool_name}'の実行に失敗しました。詳細: {e}]", tool_call_id=tool_call['id']))

    return {"messages": tool_messages}


# --- 新しい、ルーティング論理 ---
def route_after_tool_decision(state: AgentState):
    """ツール使用判断ノードの後、次にどこへ進むかを決定するロジック"""
    print("--- ルーティング判断 (route_after_tool_decision) 実行 ---")
    last_message = state['messages'][-1] if state['messages'] else None

    if not last_message or not isinstance(last_message, AIMessage):
        print("  - 警告: ルーティング判断に必要なAIメッセージが存在しません。最終応答生成へ。")
        return "generate_final_response" # または END

    if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        print("  - 判断: ツール呼び出しあり。call_tool ノードへ。")
        return "call_tool"
    else:
        print("  - 判断: ツール呼び出しなし。generate_final_response ノードへ。")
        return "generate_final_response"

# --- 新しい、ツールの、定義 ---

# Web検索ツールを、LangChainが、理解できる、形式で、定義
from langchain_core.tools import tool

@tool
def web_search_tool(query: str) -> str:
    """ユーザーからのクエリに基づいて、最新の情報を得るためにWeb検索を実行します。"""
    print(f"--- Web検索ツール実行 (Query: '{query}') ---")
    tavily_api_key = os.environ.get("TAVILY_API_KEY")
    if not tavily_api_key:
        return "[エラー：Tavily APIキーが環境変数に設定されていません]"
    try:
        client = TavilyClient(api_key=tavily_api_key)
        # Tavilyのsearchメソッドは辞書を返すので、結果を適切に処理する
        response = client.search(query=query, search_depth="advanced", max_results=3) # 結果は3件に絞る

        if response and response.get('results'):
            # 結果を連結して文字列として返す
            return "\n\n".join([f"URL: {res['url']}\n内容: {res['content']}" for res in response['results']])
        else:
            return "[情報：Web検索で結果が見つかりませんでした]"

    except Exception as e:
        print(f"  - Web検索ツールでエラー: {e}")
        traceback.print_exc()
        return f"[エラー：Web検索中に問題が発生しました。詳細: {e}]"

# --- 新しい、グラフの、構築 ---
workflow = StateGraph(AgentState)

# ノードを登録
workflow.add_node("decide_tool_use", decide_tool_use_node)
workflow.add_node("call_tool", call_tool_node)
workflow.add_node("generate_final_response", generate_final_response_node)

# エントリーポイントを設定
workflow.set_entry_point("decide_tool_use")

# 条件付きエッジ: ツール判断ノードからの分岐
workflow.add_conditional_edges(
    "decide_tool_use",
    route_after_tool_decision,
    {
        "call_tool": "call_tool",
        "generate_final_response": "generate_final_response"
    }
)

# ツール実行後は最終応答生成へ
workflow.add_edge("call_tool", "generate_final_response")

# 最終応答生成後は終了
workflow.add_edge("generate_final_response", END)

app = workflow.compile()
