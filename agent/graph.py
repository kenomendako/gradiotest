# agent/graph.py

import os
import traceback
from typing import TypedDict, List
from typing_extensions import Annotated
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END, START, add_messages
from langchain_core.tools import tool

# ▼▼▼ config_managerをインポート ▼▼▼
import config_manager
import gemini_api
# ▲▲▲ インポート追加 ▲▲▲
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

# ▼▼▼【重要】get_configured_llm を最終修正▼▼▼
def get_configured_llm(model_name: str, api_key: str, bind_tools: List = None):
    """
    config_managerの安全設定リストを、ChatGoogleGenerativeAIが要求する
    辞書形式に変換して、モデルを初期化する。
    """
    # 1. config_managerからリスト形式の安全設定を取得
    safety_settings_list = config_manager.SAFETY_CONFIG

    # 2. ChatGoogleGenerativeAIが要求する辞書形式に「通訳」する
    safety_settings_dict = {item['category']: item['threshold'] for item in safety_settings_list}
    print(f"  - 安全設定をLangChain用の辞書形式に変換しました。")

    # 3. 変換後の辞書を渡してモデルを初期化
    llm = ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=api_key,
        safety_settings=safety_settings_dict # ★★★ 変換後の辞書を渡す ★★★
    )
    if bind_tools:
        llm = llm.bind_tools(bind_tools)
        print(f"  - モデル '{model_name}' に道具: {[tool.name for tool in bind_tools]} をバインドしました。")
    else:
        print(f"  - モデル '{model_name}' は道具なしで初期化されました。")
    return llm

# ▼▼▼【重要】tool_router_nodeを再導入し、Flashに「集中コンテキスト」を与える▼▼▼
def tool_router_node(state: AgentState):
    """
    ツールを使うかどうかの判断に特化したノード。
    gemini-2.5-flashに「集中モード用コンテキスト」を与え、迅速かつ正確に判断させる。
    """
    print("--- ツールルーターノード (tool_router_node) 実行 ---")

    # 1. 集中モード用の新しいメッセージリストを作成
    messages_for_router = []
    original_messages = state['messages']

    # 2. 元の履歴からシステムプロンプトを最初に抽出
    system_prompt = next((msg for msg in original_messages if isinstance(msg, SystemMessage)), None)
    if system_prompt:
        messages_for_router.append(system_prompt)

    # 3. 最後のユーザー指示以降のメッセージのみを抽出
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
        messages_for_router.extend(original_messages) # フォールバックとして全履歴
        print("  - 警告: ユーザーメッセージが見つかりません。全履歴をコンテキストとして使用します。")

    # 4. Flashを呼び出す
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

    print(f"  - Flashへの入力メッセージ数: {len(messages_for_router)}")
    response = llm_flash_with_tools.invoke(messages_for_router)

    if hasattr(response, 'tool_calls') and response.tool_calls:
        print("  - Flashが道具の使用を決定。")
        return {"messages": [response]}
    else:
        print("  - Flashは道具を使用しないと判断。最終応答生成へ。")
        # ツールを使わない場合、Proに完全な履歴を渡して応答させる
        # この時点では何も返さず、ルーティングで final_response に向かわせる
        return {}

# ▼▼▼【重要】final_response_nodeを再導入し、Proに「完全な記憶」を与える▼▼▼
def final_response_node(state: AgentState):
    """
    彼らしい応答を生成することに特化した最終ノード。
    gemini-2.5-proに「完全な会話履歴」を与え、深く豊かな応答を生成させる。
    """
    print("--- 最終応答生成ノード (final_response_node) 実行 ---")
    api_key = state['api_key']
    final_model_to_use = state.get("final_model_name", "gemini-2.5-pro")

    # 完全な会話履歴を使用してProを呼び出す
    llm_final = get_configured_llm(final_model_to_use, api_key)

    # トークン数は完全な履歴で計算
    total_tokens = gemini_api.count_tokens_from_lc_messages(
        state['messages'], final_model_to_use, api_key
    )
    print(f"  - 最終的な合計入力トークン数（完全な履歴）を計算しました: {total_tokens}")

    print(f"  - {final_model_to_use}への入力メッセージ数（完全な履歴）: {len(state['messages'])}")
    try:
        response = llm_final.invoke(state['messages'])
        return {"messages": [response], "final_token_count": total_tokens}
    except Exception as e:
        print(f"  - 最終応答生成ノードでエラー: {e}")
        return {"messages": [AIMessage(content=f"[エラー：最終応答の生成中に問題が発生しました。詳細: {e}]")], "final_token_count": 0}

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

# ▼▼▼【重要】グラフの再構築▼▼▼
workflow = StateGraph(AgentState)

workflow.add_node("tool_router", tool_router_node)
workflow.add_node("call_tool", call_tool_node)
workflow.add_node("final_response", final_response_node) # 最終応答ノードを再追加

workflow.set_entry_point("tool_router")

workflow.add_conditional_edges(
    "tool_router",
    should_call_tool,
    {
        "call_tool": "call_tool",
        "final_response": "final_response" # ツールを使わない場合はfinal_responseへ
    }
)

# ツール実行後、再度tool_routerに戻り、次の行動を考えさせる (ReActループ)
workflow.add_edge("call_tool", "tool_router")

# 最終応答の後、グラフは終了する
workflow.add_edge("final_response", END)

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
