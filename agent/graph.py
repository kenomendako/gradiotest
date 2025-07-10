# agent/graph.py

import os
import traceback
from typing import TypedDict, List
from typing_extensions import Annotated
# ▼▼▼ SystemMessage をインポート ▼▼▼
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, SystemMessage
# ▲▲▲ インポート追加 ▲▲▲
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
    最終応答を評価し、不十分な場合はRETRYを決定する。
    RETRYの場合、会話履歴を最後のユーザー入力まで巻き戻し、
    再試行を促すシステムメッセージを追加して、クリーンな状態で再試行する。
    """
    print("--- 振り返りノード (reflection_node) 実行 ---")

    # ▼▼▼ ここからが最重要変更点 ▼▼▼
    # 1. モデルのバージョンを規約通りに修正
    print("  - 振り返りモデルとして 'gemini-2.5-flash' を使用します。")
    llm_flash = get_configured_llm("gemini-2.5-flash", state['api_key'])

    # 2. 評価対象のメッセージを取得
    if len(state["messages"]) < 2:
        print("  - 警告: 振り返りのための十分なメッセージがありません。FINISHします。")
        return {"reflection": "FINISH"}

    ai_message = state["messages"][-1]
    # HumanMessage, AIMessage, ToolMessage以外のメッセージは評価対象外とする
    if not isinstance(ai_message, (AIMessage, ToolMessage)):
        last_human_message_index = -1
        for i in range(len(state["messages"]) - 1, -1, -1):
            if isinstance(state["messages"][i], HumanMessage):
                last_human_message_index = i
                break
        if last_human_message_index != -1 and last_human_message_index < len(state["messages"]) - 1:
            ai_message = state["messages"][last_human_message_index + 1]
        else:
             print("  - 評価対象のAIメッセージが見つかりません。FINISHします。")
             return {"reflection": "FINISH"}


    user_message = None
    for i in range(len(state["messages"]) - 2, -1, -1):
        if isinstance(state["messages"][i], HumanMessage):
            user_message = state["messages"][i]
            break

    if not user_message:
        print("  - 評価対象のユーザーメッセージが見つかりません。FINISHします。")
        return {"reflection": "FINISH"}

    reflection_prompt = f"""
あなたは、AIアシスタントの応答を評価する、高度な評価者です。
以下の「ユーザーの指示」と、それに対する「AIの応答」を分析してください。

【ユーザーの指示】
{user_message.content}

【AIの応答】
{ai_message.content}

【評価基準】
AIの応答は、ユーザーの指示を完全に満たしていますか？
それとも、AIは「Webで検索すればよかった」「メモ帳を確認するべきだった」のように、本来ツールを使うべきだったというニュアンスや、情報不足を示唆していませんか？

【判断】
もし、AIの応答が不完全で、ツールを使えばより良い応答ができたと考えられる場合は "RETRY" とだけ出力してください。
応答が完全で、これ以上のアクションが不要な場合は "FINISH" とだけ出力してください。
"""
    try:
        reflection_result = llm_flash.invoke(reflection_prompt)
        decision = reflection_result.content.strip().upper()
        print(f"  - 振り返りの結果: {decision}")

        if decision == "RETRY":
            print("  - 再試行を決定。履歴を最後のユーザー入力まで巻き戻します。")

            # 3. 最後のHumanMessageの位置を探す
            last_human_message_index = -1
            for i in range(len(state["messages"]) - 1, -1, -1):
                if isinstance(state["messages"][i], HumanMessage):
                    last_human_message_index = i
                    break

            if last_human_message_index == -1:
                print("  - 警告: 巻き戻し地点となるユーザーメッセージが見つかりません。FINISHします。")
                return {"reflection": "FINISH"}

            # 4. 履歴をリセットし、再試行用のシステムメッセージを追加
            messages_for_retry = state["messages"][:last_human_message_index + 1]
            retry_instruction = SystemMessage(
                content="【システム指示】前回の応答は不十分でした。ユーザーの最新の要求を再度分析し、利用可能なツールを最大限活用して、より精度の高い応答を生成してください。"
            )
            messages_for_retry.append(retry_instruction)
            print(f"  - 履歴を{len(state['messages'])}件から{len(messages_for_retry)}件にリセットしました。")

            return {
                "messages": messages_for_retry,
                "reflection": "RETRY"
            }
        else:
            if decision != "FINISH":
                print(f"  - 警告: 振り返りノードの応答が予期せぬ形式({decision})。FINISHとして扱います。")
            return {"reflection": "FINISH"}

    except Exception as e:
        print(f"  - 振り返りノードでエラー: {e}")
        traceback.print_exc()
        return {"reflection": "FINISH"}
# ▲▲▲ 変更ここまで ▲▲▲

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
