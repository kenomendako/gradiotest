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
import gemini_api # final_response_node で gemini_api.FINAL_RESPONSE_PROMPT を参照するため
# ▼▼▼【重要】prompts.pyから、MEMORY_WEAVER_PROMPT_TEMPLATE を、インポート▼▼▼
from agent.prompts import MEMORY_WEAVER_PROMPT_TEMPLATE
from tools.web_tools import read_url_tool
from tools.notepad_tools import add_to_notepad, update_notepad, delete_from_notepad, read_full_notepad


# ▼▼▼【重要】AgentStateを、最終形態に、修正▼▼▼
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    character_name: str
    api_key: str
    final_model_name: str
    final_token_count: int
    # 要約コンテキストと、長期記憶検索結果を、保持する、フィールドを、再追加
    synthesized_context: SystemMessage
    retrieved_long_term_memories: str


def get_configured_llm(model_name: str, api_key: str, bind_tools: List = None):
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


# ▼▼▼【重要】memory_weaver_nodeを、完全に、復活させ、定義▼▼▼
def memory_weaver_node(state: AgentState):
    """
    グラフの最初に実行され、長期記憶と短期記憶を要約し、
    その結果をstateに格納する、新しい、心臓部。
    """
    print("--- 魂を織りなす記憶ノード (memory_weaver_node) 実行 ---")

    messages = state['messages']
    character_name = state['character_name']
    api_key = state['api_key']

    RECENT_HISTORY_COUNT = 30 # 要約に含める短期記憶の件数

    # 検索クエリとして、最後のユーザーメッセージ（テキスト部分）を使用
    last_user_message_obj = next((msg for msg in reversed(messages) if isinstance(msg, HumanMessage)), None)
    search_query = ""
    if last_user_message_obj:
        if isinstance(last_user_message_obj.content, str):
            search_query = last_user_message_obj.content
        elif isinstance(last_user_message_obj.content, list): # マルチモーダルの場合
            text_parts = [part['text'] for part in last_user_message_obj.content if isinstance(part, dict) and part.get('type') == 'text']
            search_query = " ".join(text_parts)

    # クエリが長すぎる場合や、ファイルのみでテキストがない場合を考慮
    if len(search_query) > 500: # クエリが長すぎる場合は切り詰める
        search_query = search_query[:500] + "..."
    if not search_query.strip(): # 空白文字のみ、または完全に空の場合
        search_query = "（ユーザーからの添付ファイル、または、空のメッセージ）" # テキストがない場合のデフォルトクエリ

    print(f"  - [Memory Weaver] 生成された検索クエリ: '{search_query}'")

    # 長期記憶を検索
    long_term_memories_str = rag_manager.search_conversation_memory_for_summary(
        character_name=character_name,
        query=search_query,
        api_key=api_key
    )

    # 直近の会話履歴を整形
    recent_history_messages = messages[-RECENT_HISTORY_COUNT:]
    recent_history_str = "\n".join([f"- {msg.type}: {msg.content}" for msg in recent_history_messages]) # typeを使用
    print(f"  - 直近の会話履歴 {len(recent_history_messages)} 件を、要約の、材料とします。")

    # Flashに要約を依頼
    summarizer_prompt = MEMORY_WEAVER_PROMPT_TEMPLATE.format(
        character_name=character_name,
        long_term_memories=long_term_memories_str,
        recent_history=recent_history_str
    )

    llm_flash = get_configured_llm("gemini-2.5-flash", api_key)
    summary_text = llm_flash.invoke(summarizer_prompt).content

    print(f"  - 生成された状況サマリー:\n{summary_text}")

    synthesized_context_message = SystemMessage(content=f"【現在の状況サマリー】\n{summary_text}")

    # 要約結果と、検索結果の両方を、stateに格納して返す
    return {
        "synthesized_context": synthesized_context_message,
        "retrieved_long_term_memories": long_term_memories_str
    }


def tool_router_node(state: AgentState):
    """
    ツールを使うかどうかの判断に特化したノード。
    memory_weaver_nodeが生成した「要約コンテキスト」を使用する。
    """
    print("--- ツールルーターノード (tool_router_node) 実行 ---")

    messages_for_router = []
    original_messages = state['messages'] # これは全履歴

    # 本来のシステムプロンプトを抽出
    system_prompt = next((msg for msg in original_messages if isinstance(msg, SystemMessage) and msg.content != state['synthesized_context'].content), None)
    if system_prompt:
        messages_for_router.append(system_prompt)

    # memory_weaverが生成した要約コンテキストを追加
    messages_for_router.append(state['synthesized_context'])

    # 最後のユーザー指示を追加
    last_user_message = next((msg for msg in reversed(original_messages) if isinstance(msg, HumanMessage)), None)
    if last_user_message:
        messages_for_router.append(last_user_message)

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

    llm_flash_with_tools = get_configured_llm("gemini-2.5-flash", api_key, available_tools)

    print(f"  - Flashへの入力メッセージ数（要約＋最新指示）: {len(messages_for_router)}")
    response = llm_flash_with_tools.invoke(messages_for_router)

    if hasattr(response, 'tool_calls') and response.tool_calls:
        print("  - Flashが道具の使用を決定。")
        # AIMessageをそのままmessagesに追加するのではなく、tool_callsを持つAIMessageを返す
        return {"messages": [response]}
    else:
        print("  - Flashは道具を使用しないと判断。最終応答生成へ。")
        # ツールを使わない場合は、空の辞書を返して final_response_node へ進むようにする
        # この場合、state['messages']は更新されないので、final_response_nodeは元のmessagesを見る
        return {}


def final_response_node(state: AgentState):
    """
    Proに「完全な会話履歴」と「最初に検索した長期記憶」を与え、応答を生成させる。
    """
    print("--- 最終応答生成ノード (final_response_node) 実行 ---")

    # 鞄から、旅の、最初に、得た、長期記憶を、取り出す
    retrieved_memories_str = state.get("retrieved_long_term_memories", "（関連する長期記憶なし）")

    messages = state['messages'] # これはツール実行結果も含む完全な履歴
    last_user_message_content = ""
    last_human_message_index = -1
    # 最後のHumanMessageを探す
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            # HumanMessageのcontentが文字列かリスト（マルチモーダル）かを確認
            if isinstance(messages[i].content, str):
                last_user_message_content = messages[i].content
            elif isinstance(messages[i].content, list):
                # マルチモーダルの場合、テキスト部分のみを抽出
                text_parts = [part['text'] for part in messages[i].content if isinstance(part, dict) and part.get('type') == 'text']
                last_user_message_content = " ".join(text_parts)
            last_human_message_index = i
            break

    tool_outputs = []
    if last_human_message_index != -1:
        # 最後のユーザーメッセージ以降のツールメッセージを収集
        for msg in messages[last_human_message_index:]:
            if isinstance(msg, ToolMessage):
                tool_outputs.append(f"・ツール「{msg.name}」を実行し、結果「{msg.content}」を得ました。")

    tool_outputs_str = "\n".join(tool_outputs) if tool_outputs else "（特筆すべき、ツール実行結果なし）"

    # 最終報告書用のプロンプトをフォーマット
    final_prompt_text = gemini_api.FINAL_RESPONSE_PROMPT.format(
        last_user_message=last_user_message_content,
        tool_outputs=tool_outputs_str,
        retrieved_memories=retrieved_memories_str
    )

    # Proモデルへの最終的な入力メッセージリストを作成
    # ここでは、元の会話履歴全体と、最後に整形した指示プロンプト(HumanMessageとして)を渡す
    final_messages_for_pro = list(messages)
    final_messages_for_pro.append(HumanMessage(content=final_prompt_text))

    api_key = state['api_key']
    final_model_to_use = state.get("final_model_name", "gemini-2.5-pro")
    llm_final = get_configured_llm(final_model_to_use, api_key)

    total_tokens = gemini_api.count_tokens_from_lc_messages(
        final_messages_for_pro, final_model_to_use, api_key
    )
    print(f"  - 最終的な合計入力トークン数（指示プロンプト含む）を計算しました: {total_tokens}")

    print(f"  - {final_model_to_use}への入力メッセージ数（指示プロンプト含む）: {len(final_messages_for_pro)}")
    try:
        response = llm_final.invoke(final_messages_for_pro)
        # 新しい応答のみを messages に追加して返すのではなく、新しい応答で上書きする
        return {"messages": [response], "final_token_count": total_tokens}
    except Exception as e:
        print(f"  - 最終応答生成ノードでエラー: {e}")
        return {"messages": [AIMessage(content=f"[エラー：最終応答の生成中に問題が発生しました。詳細: {e}]")], "final_token_count": 0}


def call_tool_node(state: AgentState):
    last_message = state['messages'][-1] # tool_routerからAIMessage(tool_calls=...) が入る想定
    if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
        return {} # ツールコールがない場合は何もせず、次の判断へ

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

    MAX_TOOLS_PER_TURN = 3 # 指示通り3に戻す
    tool_calls_to_execute = last_message.tool_calls[:MAX_TOOLS_PER_TURN]

    if len(last_message.tool_calls) > MAX_TOOLS_PER_TURN:
        print(f"  - 警告: 一度に{len(last_message.tool_calls)}個のツール呼び出しが要求されましたが、最初の{MAX_TOOLS_PER_TURN}個のみ実行します。")

    for tool_call in tool_calls_to_execute:
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

    # 実行したツールの結果(ToolMessage)をmessagesに追加して返す
    return {"messages": tool_messages}


def should_call_tool(state: AgentState):
    print("--- ルーティング判断 (should_call_tool) 実行 ---")
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

# ▼▼▼【重要】ノードを再定義し、エントリーポイントを修正▼▼▼
workflow.add_node("memory_weaver", memory_weaver_node)
workflow.add_node("tool_router", tool_router_node)
workflow.add_node("call_tool", call_tool_node)
workflow.add_node("final_response", final_response_node)

workflow.set_entry_point("memory_weaver") # エントリーポイントを memory_weaver に設定
workflow.add_edge("memory_weaver", "tool_router") # memory_weaver から tool_router へ

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
