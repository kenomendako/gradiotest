import os
import traceback
from typing import TypedDict, List, Optional

# LangChain/LangGraphに最適化された、正しい、ライブラリを、インポートする
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage # ToolMessageもインポート

from langgraph.graph import StateGraph, END, START # STARTもインポートする可能性を考慮 (今回は未使用)
from tavily import TavilyClient

import config_manager
import rag_manager

# --- 新しい、魂の、定義書 (State) ---
class AgentState(TypedDict):
    messages: List[AIMessage | HumanMessage | ToolMessage] # LangChainのメッセージ形式
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

def call_model_node(state: AgentState):
    """【新世界の作法】AIを呼び出し、自律的な判断を促すノード"""
    print("--- AI思考ノード実行 ---")

    # 正しい、高レベルな、モデルクラスを、使用する
    # TODO: safety_settings を config_manager から読み込んで適用する
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-pro", # 思考の、中枢は、Proモデル
        google_api_key=state['api_key'],
        convert_system_message_to_human=True, # システムプロンプトを、扱えるようにする
        # safety_settings=config_manager.SAFETY_CONFIG # ここで適用すべき
    )

    # ツールを、定義する (実際のツールオブジェクトは後で定義・インポート)
    # ここでは、ツールが持つべき名前と説明を仮に定義しておくか、
    # あるいは、ツールオブジェクトが完成してから参照するようにする。
    # 今回は、後で作成するツール名だけをリストアップしておく形にする。
    # tools = [rag_manager.search_tool, web_search_tool] # 後で、ツールを、作成する

    # LangChainの推奨に従い、ツール自体を渡すのではなく、モデルにツールスキーマを渡す
    # ただし、ChatGoogleGenerativeAI は .bind_tools にツールオブジェクトのリストを期待する
    # 外部で定義されたツールオブジェクトをインポートして使う

    # 現時点ではツールが未定義なので、一旦ツールなしで呼び出すか、
    # ダミーのツールを渡す必要がある。
    # 指示書ではツールを渡しているので、その前提で進めるが、
    # 実行時エラーを避けるため、ツールが未定義の場合はスキップする。

    active_tools = []
    if hasattr(rag_manager, 'search_tool'): # rag_manager.search_tool が存在すれば追加
        active_tools.append(rag_manager.search_tool)

    # web_search_tool はこのファイル内で後ほど定義されるので、
    # ここではグローバルスコープで参照できるか確認する
    if 'web_search_tool' in globals() and callable(globals()['web_search_tool']):
         active_tools.append(globals()['web_search_tool'])

    if active_tools:
        llm_with_tools = llm.bind_tools(active_tools)
        print(f"  - 利用可能な道具: {[tool.name for tool in active_tools]}")
    else:
        llm_with_tools = llm # ツールがなければそのまま
        print("  - 利用可能な道具なし。")


    try:
        # AIに、メッセージ履歴と、利用可能な、ツールを、渡して、判断を、仰ぐ
        # 最後のメッセージがユーザーからのものであることを期待
        # もし履歴が空なら、HumanMessage("") のような空のメッセージで開始することも検討
        if not state['messages']:
             print("  - 警告: メッセージ履歴が空です。AIの応答が不安定になる可能性があります。")
             # 空のHumanMessageを追加してエラーを回避するか、あるいはエラーとするか。
             # ここでは空の応答を返すようにする。
             # return {"messages": [AIMessage(content="[メッセージ履歴が空のため応答できません]")]}


        print(f"  - AIへの入力メッセージ数: {len(state['messages'])}")
        # 最後のメッセージがToolMessageの場合、次のAIMessageを期待する
        # 最後のメッセージがAIMessageでtool_callsがある場合、それはエラーケースか、未完了のツール呼び出し

        response_message = llm_with_tools.invoke(state['messages'])
        return {"messages": [response_message]}
    except Exception as e:
        print(f"  - AI思考ノードでエラー: {e}")
        traceback.print_exc()
        error_message = AIMessage(content=f"[エラー：思考中に問題が発生しました。詳細: {e}]")
        return {"messages": [error_message]}

# --- call_tool_node の、修正 ---
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
        "web_search_tool": web_search_tool      # このファイルのグローバルスコープの web_search_tool
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
            tool_messages.append(ToolMessage(content=str(observation), tool_call_id=tool_call_id))
        except Exception as e:
            print(f"  - 道具 '{tool_name}' の実行中にエラー: {e}")
            traceback.print_exc()
            tool_messages.append(ToolMessage(content=f"[エラー：道具'{tool_name}'の実行に失敗しました。詳細: {e}]", tool_call_id=tool_call_id))

    return {"messages": tool_messages}

# --- 新しい、ルーティング論理 ---
def should_continue_logic(state: AgentState):
    """次に何をすべきかを判断するロジック"""
    last_message = state['messages'][-1] if state['messages'] else None

    # messagesが空、あるいは最後のメッセージが存在しない場合は終了
    if not last_message:
        print("  - ルーティングロジック: メッセージリストが空のため終了します。")
        return END

    # AIが、ツール使用を、選択した場合、道具実行ノードへ
    if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        print("  - ルーティングロジック: 道具呼び出しあり。call_tool へ。")
        return "call_tool"
    # そうでなければ、終了
    else:
        print("  - ルーティングロジック: 道具呼び出しなし。終了します。")
        return END

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

workflow.add_node("call_model", call_model_node)
workflow.add_node("call_tool", call_tool_node)

workflow.set_entry_point("call_model")

workflow.add_conditional_edges(
    "call_model",
    should_continue_logic,
    {
        "call_tool": "call_tool",
        END: END
    }
)
workflow.add_edge("call_tool", "call_model")

app = workflow.compile()
