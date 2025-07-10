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
    # ★★★ ここから追加 ★★★
    # 振り返りの結果を格納するキー
    reflection: str
    # ★★★ 追加ここまで ★★★

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

# ★★★ ここから新しいノードの定義を追加 ★★★
def reflection_node(state: AgentState) -> dict:
    """
    最終応答が、本来ツールを使うべきだったという「後悔」を含んでいないか、
    あるいはユーザーの指示を達成しきれているかを確認する。
    """
    print("--- 振り返りノード (reflection_node) 実行 ---")

    # 最後のAIメッセージ（Proの応答）と、その前のユーザーメッセージを取得
    # messagesリストの構造を確認し、適切なインデックスでアクセスする
    # 通常、最後がAIの応答、その一つ前がユーザーの指示のはず
    if len(state["messages"]) < 2:
        print("  - 警告: 振り返りのための十分なメッセージがありません。安全に終了します。")
        return {"reflection": "FINISH"}

    ai_message_obj = state["messages"][-1]
    user_message_obj = state["messages"][-2]

    # content属性から文字列を取得
    ai_message = ai_message_obj.content if hasattr(ai_message_obj, 'content') else str(ai_message_obj)
    user_message = user_message_obj.content if hasattr(user_message_obj, 'content') else str(user_message_obj)

    # 振り返り用のプロンプト
    reflection_prompt = f"""
あなたは、AIアシスタントの応答を評価する、高度な評価者です。
以下の「ユーザーの指示」と、それに対する「AIの応答」を分析してください。

【ユーザーの指示】
{user_message}

【AIの応答】
{ai_message}

【評価基準】
AIの応答は、ユーザーの指示を完全に満たしていますか？
それとも、AIは「Webで検索すればよかった」「メモ帳を確認するべきだった」のように、本来ツールを使うべきだったというニュアンスや、情報不足を示唆していませんか？

【判断】
もし、AIの応答が不完全で、ツールを使えばより良い応答ができたと考えられる場合は "RETRY" とだけ出力してください。
応答が完全で、これ以上のアクションが不要な場合は "FINISH" とだけ出力してください。
"""

    # 振り返りには高速なモデルで十分
    api_key = state['api_key']
    # モデル名は state から取得するか、固定で指定するか検討。ここでは Flash を直接指定。
    llm_flash = get_configured_llm("gemini-1.5-flash-latest", api_key) # モデル名を最新版に更新

    try:
        reflection_result = llm_flash.invoke(reflection_prompt)
        decision = reflection_result.content.strip().upper()
        print(f"  - 振り返りの結果: {decision}")
        # 想定外の応答が来た場合も安全にFINISHとする
        if decision not in ["RETRY", "FINISH"]:
            print(f"  - 警告: 振り返りノードの応答が予期せぬ形式です ({decision})。FINISHとして扱います。")
            decision = "FINISH"
        return {"reflection": decision}
    except Exception as e:
        print(f"  - 振り返りノードでエラー: {e}")
        traceback.print_exc()
        # エラー時は安全に終了させる
        return {"reflection": "FINISH"}
# ★★★ 追加ここまで ★★★

# ★★★ ここから新しい条件付きエッジの定義を追加 ★★★
def should_retry(state: AgentState) -> str:
    """
    reflection_nodeの結果に基づき、グラフをやり直すか終了するかを決定する。
    """
    print("--- 再試行判断 (should_retry) 実行 ---")
    if state.get("reflection") == "RETRY":
        print("  - 判断: 応答が不十分。tool_router に戻ってやり直します。")
        # messagesの最後にユーザーの指示を再度追加して、tool_routerがそれを参照できるようにする
        # あるいは、tool_routerが参照するメッセージを調整する
        # ここでは、stateは変更せずに、単にルーティング先を返す
        return "tool_router"
    else: # FINISH または予期せぬ値
        print("  - 判断: 応答は完了。グラフを終了します。")
        return END
# ★★★ 追加ここまで ★★★

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
workflow.add_node("reflection", reflection_node) # ★ 新しいノードを追加

# エッジ（配線）の接続
workflow.set_entry_point("tool_router")

# 最初のルーターからの分岐
workflow.add_conditional_edges(
    "tool_router",
    should_call_tool,
    {
        "call_tool": "call_tool",
        "final_response": "final_response"
    }
)

# ツール呼び出しから最終応答へ
workflow.add_edge("call_tool", "final_response")

# ★★★ ここからが最重要変更点 ★★★
# 最終応答の後、すぐに終了(END)するのではなく、振り返り(reflection)を行う
workflow.add_edge("final_response", "reflection")

# 振り返りの結果に応じて、やり直す(tool_routerへループ)か、終了(END)するかを決める
workflow.add_conditional_edges(
    "reflection",
    should_retry,
    { # should_retryが返す文字列とノード名をマッピング
        "tool_router": "tool_router",
        END: END
    }
)
# ★★★ 変更ここまで ★★★

# グラフのコンパイル
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
