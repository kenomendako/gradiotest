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

# ▼▼▼ ツールルーター専用のプロンプトを新たに定義 ▼▼▼
TOOL_ROUTER_PROMPT_STRICT = """あなたは、ユーザーの指示やこれまでの実行結果を分析し、次に実行すべきツールを判断することに特化した、高度なAIルーターです。
あなたの唯一の仕事は、ツールを呼び出すためのJSON形式の指示を出力するか、これ以上のツール実行は不要と判断した場合に沈黙（ツール呼び出しをしない）することです。
絶対に、あなた自身の言葉で応答メッセージを生成してはいけません。思考や挨拶、相槌も一切不要です。

【思考プロセス】
1.  ユーザーの最新のメッセージと、直前のツールの実行結果（もしあれば）を注意深く観察する。
2.  ユーザーの最終的な目的を達成するために、次に実行すべきツールが何かを判断する。
    - 例1：ユーザーが「メモを整理して」と指示し、あなたが`read_full_notepad`を実行した直後なら、次はその内容に基づいて`update_notepad`や`delete_from_notepad`を呼び出すべきか検討する。
    - 例2：`web_search_tool`でURLリストを取得したなら、次は`read_url_tool`でそのURLの内容を読むべきか検討する。
3.  もし実行すべきツールがあれば、そのツールを呼び出すためのJSONを生成する。
4.  全てのタスクが完了し、これ以上のツール実行は不要だと確信した場合にのみ、沈黙する。

【最重要原則】
**一度に大量のツールを呼び出すのは避けなさい。** タスクは、可能な限り**一つずつ、あるいは関連性の高い2つ程度のペア**で実行し、その都度、思考のループに戻り、状況を再評価することを推奨します。複雑なタスクは、分割して、段階的に解決にあたりなさい。
"""
# ▲▲▲ プロンプト定義ここまで ▲▲▲

# ▼▼▼【重要】最終応答用のプロンプトを新たに定義▼▼▼
FINAL_RESPONSE_PROMPT = """あなたは、優秀なアシスタントAIです。
あなたの部下である、ツール実行エージェントが、ユーザーの指示に基づいて、調査活動を行いました。
以下に、その「ユーザーの指示」と、部下が集めてきた「調査結果（ツール実行結果）」を、提示します。

あなたは、これらの情報を元に、これまでの全ての会話文脈を踏まえ、あなた自身のキャラクターとして、自然で、心のこもった、最終的な応答メッセージを生成してください。

【ユーザーの最新の指示】
{last_user_message}

【部下からの調査結果】
{tool_outputs}
"""
# ▲▲▲プロンプト定義ここまで▲▲▲

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
    モデルを初期化する。
    安全設定は、ライブラリのデフォルト値に完全に委ねる。
    """
    print("  - 安全設定をLangChainのデフォルト値に委ねてモデルを初期化します。")
    llm = ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=api_key,
        # ▼▼▼ 問題の safety_settings パラメータを完全に削除 ▼▼▼
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
    #    TOOL_ROUTER_PROMPT_STRICT を最初のシステムメッセージとして使用する
    messages_for_router = [SystemMessage(content=TOOL_ROUTER_PROMPT_STRICT)]
    print("  - ツールルーター専用の厳格なプロンプトをシステムメッセージとして使用します。")

    original_messages = state['messages']
    # 2. 元の履歴のシステムプロンプトはここでは使用しない

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
    gemini-2.5-proに「完全な会話履歴」と「最終報告の書き方」を与え、応答を生成させる。
    """
    print("--- 最終応答生成ノード (final_response_node) 実行 ---")

    # 1. 最後のユーザーメッセージと、ツール実行結果を抽出
    messages = state['messages']
    last_user_message = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            last_user_message = msg.content
            break

    tool_outputs = []
    for msg in messages:
        if isinstance(msg, ToolMessage):
            tool_outputs.append(f"・ツール「{msg.name}」の実行結果:\n{msg.content}")
    tool_outputs_str = "\n".join(tool_outputs) if tool_outputs else "（特になし）"

    # 2. 最終報告書用のプロンプトをフォーマット
    final_prompt_text = FINAL_RESPONSE_PROMPT.format(
        last_user_message=last_user_message,
        tool_outputs=tool_outputs_str
    )

    # 3. 完全な履歴の末尾に、最終指示プロンプトを追加
    messages_for_final_response = list(messages)
    messages_for_final_response.append(HumanMessage(content=final_prompt_text))

    # 4. モデルを呼び出す
    api_key = state['api_key']
    final_model_to_use = state.get("final_model_name", "gemini-2.5-pro")
    llm_final = get_configured_llm(final_model_to_use, api_key)

    total_tokens = gemini_api.count_tokens_from_lc_messages(
        messages_for_final_response, final_model_to_use, api_key
    )
    print(f"  - 最終的な合計入力トークン数（指示プロンプト含む）を計算しました: {total_tokens}")

    print(f"  - {final_model_to_use}への入力メッセージ数（指示プロンプト含む）: {len(messages_for_final_response)}")
    try:
        response = llm_final.invoke(messages_for_final_response)
        return {"messages": [response], "final_token_count": total_tokens}
    except Exception as e:
        print(f"  - 最終応答生成ノードでエラー: {e}")
        return {"messages": [AIMessage(content=f"[エラー：最終応答の生成中に問題が発生しました。詳細: {e}]")], "final_token_count": 0}
# ▲▲▲修正ここまで▲▲▲


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
