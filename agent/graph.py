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
import gemini_api # final_response_node で gemini_api.FINAL_RESPONSE_PROMPT を参照するため（ただし、最終的にはこのファイル内の定数を使う）
import rag_manager
from agent.prompts import MEMORY_WEAVER_PROMPT_TEMPLATE, TOOL_ROUTER_PROMPT_STRICT, FINAL_RESPONSE_PROMPT
from tools.web_tools import read_url_tool
from tools.notepad_tools import add_to_notepad, update_notepad, delete_from_notepad, read_full_notepad
from tools.memory_tools import edit_memory, add_secret_diary_entry # ★ インポート

# ▼▼▼【重要】AgentStateを、最終形態に、修正▼▼▼
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    character_name: str
    api_key: str
    final_model_name: str
    final_token_count: int
    synthesized_context: SystemMessage # memory_weaver_node が生成する要約
    retrieved_long_term_memories: str # memory_weaver_node が検索する長期記憶
    tool_call_count: int  # ★★★ この行を追加 ★★★

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

def memory_weaver_node(state: AgentState):
    """
    グラフの最初に実行され、長期記憶と短期記憶を要約し、
    その結果をstateに格納する、新しい、心臓部。
    """
    print("--- 魂を織りなす記憶ノード (memory_weaver_node) 実行 ---")

    messages = state['messages']
    character_name = state['character_name']
    api_key = state['api_key']

    # RECENT_HISTORY_COUNT = 30 # ★★★ この行を削除 ★★★

    last_user_message_obj = next((msg for msg in reversed(messages) if isinstance(msg, HumanMessage)), None)
    search_query = ""
    if last_user_message_obj:
        if isinstance(last_user_message_obj.content, str):
            search_query = last_user_message_obj.content
        elif isinstance(last_user_message_obj.content, list):
            text_parts = [part['text'] for part in last_user_message_obj.content if isinstance(part, dict) and part.get('type') == 'text']
            search_query = " ".join(text_parts)

    if len(search_query) > 500:
        search_query = search_query[:500] + "..."
    if not search_query.strip():
        search_query = "（ユーザーからの添付ファイル、または、空のメッセージ）"

    print(f"  - [Memory Weaver] 生成された検索クエリ: '{search_query}'")

    long_term_memories_str = rag_manager.search_conversation_memory_for_summary(
        character_name=character_name,
        query=search_query,
        api_key=api_key
    )

    # ★★★ config_managerのグローバル変数を参照するように変更 ★★★
    recent_history_messages = messages[-config_manager.initial_memory_weaver_history_count_global:]
    recent_history_str = "\n".join([f"- {msg.type}: {msg.content}" for msg in recent_history_messages])
    print(f"  - 直近の会話履歴 {len(recent_history_messages)} 件を、要約の、材料とします。")

    summarizer_prompt = MEMORY_WEAVER_PROMPT_TEMPLATE.format(
        character_name=character_name,
        long_term_memories=long_term_memories_str,
        recent_history=recent_history_str
    )

    llm_flash = get_configured_llm("gemini-2.5-flash", api_key) # モデル名を規約通りに
    summary_text = llm_flash.invoke(summarizer_prompt).content

    print(f"  - 生成された状況サマリー:\n{summary_text}")

    synthesized_context_message = SystemMessage(content=f"【現在の状況サマリー】\n{summary_text}")

    return {
        "synthesized_context": synthesized_context_message,
        "retrieved_long_term_memories": long_term_memories_str
    }

def tool_router_node(state: AgentState):
    """
    ツールを使うかどうかの判断に特化したノード。
    これまでのループでのツール実行履歴も含めて、次の行動を判断する。
    """
    print("--- ツールルーターノード (tool_router_node) 実行 ---")

    messages_for_router = []
    original_messages = state['messages']

    # システムプロンプトと、memory_weaverが生成した初期コンテキストを追加
    system_prompt = next((msg for msg in original_messages if isinstance(msg, SystemMessage) and msg.content != state['synthesized_context'].content), None)
    if system_prompt:
        messages_for_router.append(system_prompt)
    else:
        messages_for_router.append(SystemMessage(content=TOOL_ROUTER_PROMPT_STRICT))
    messages_for_router.append(state['synthesized_context'])

    # ★★★ ここからが新しいロジック ★★★
    # 最後のユーザーメッセージ以降の、すべてのメッセージ（AIのツール呼び出しとツールの結果）をコンテキストに追加する
    last_human_message_index = -1
    for i in range(len(original_messages) - 1, -1, -1):
        if isinstance(original_messages[i], HumanMessage):
            last_human_message_index = i
            break

    if last_human_message_index != -1:
        # 最後のユーザーメッセージとその後の全メッセージ（ツール関連）を追加
        messages_since_last_user = original_messages[last_human_message_index:]
        messages_for_router.extend(messages_since_last_user)
    else:
        # 万が一ユーザーメッセージが見つからない場合、最新のメッセージだけを追加
        if original_messages:
            messages_for_router.append(original_messages[-1])
    # ★★★ ロジックの変更はここまで ★★★

    api_key = state['api_key']
    available_tools = [
        rag_manager.diary_search_tool,
        rag_manager.conversation_memory_search_tool,
        web_search_tool,
        read_url_tool,
        add_to_notepad,
        update_notepad,
        delete_from_notepad,
        read_full_notepad,
        edit_memory,              # ★ 追加
        add_secret_diary_entry    # ★ 追加
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
    Proに「クリーンな会話履歴」と「要約されたツール実行ログ」のみを与え、応答を生成させる。
    """
    print("--- 最終応答生成ノード (final_response_node) 実行 ---")

    all_messages = state['messages']

    # 最後のユーザーメッセージを探し、それ以前のクリーンな履歴を構築する
    last_human_message_index = -1
    for i in range(len(all_messages) - 1, -1, -1):
        if isinstance(all_messages[i], HumanMessage):
            last_human_message_index = i
            break

    if last_human_message_index == -1:
        print("警告: 最終応答ノードでユーザーメッセージが見つかりませんでした。")
        error_response_message = AIMessage(content="[エラー：処理対象のユーザーメッセージが見つかりませんでした。]")
        return {"messages": [error_response_message], "final_token_count": 0}

    # クリーンな会話履歴（ツール実行ループの手前まで）を抽出
    clean_history = all_messages[:last_human_message_index + 1]

    # 最後のユーザーメッセージの内容を取得
    last_user_message_content = ""
    last_user_message = clean_history[-1]
    if isinstance(last_user_message.content, str):
        last_user_message_content = last_user_message.content
    elif isinstance(last_user_message.content, list):
        text_parts = [part['text'] for part in last_user_message.content if isinstance(part, dict) and part.get('type') == 'text']
        last_user_message_content = " ".join(text_parts)

    # ツール実行のログを全メッセージから集約して要約する
    tool_outputs = []
    for msg in all_messages[last_human_message_index:]:
        if isinstance(msg, ToolMessage):
            # 非常に長いツール出力を要約する（例：最初の200文字）
            content_preview = (str(msg.content)[:200] + '...') if len(str(msg.content)) > 200 else str(msg.content)
            tool_outputs.append(f"・ツール「{msg.name}」を実行し、結果「{content_preview}」を得ました。")
    tool_outputs_str = "\n".join(tool_outputs) if tool_outputs else "（特筆すべき、ツール実行結果なし）"

    # 最終モデルに渡すための、新しいクリーンなメッセージリストを作成
    messages_for_pro = list(clean_history)

    # 最終指示プロンプトを作成
    final_prompt_text = FINAL_RESPONSE_PROMPT.format(
        last_user_message=last_user_message_content,
        tool_outputs=tool_outputs_str
    )
    # 最終指示を新しいHumanMessageとして追加
    messages_for_pro.append(HumanMessage(content=final_prompt_text))

    api_key = state['api_key']
    final_model_to_use = state.get("final_model_name", "gemini-2.5-pro")
    llm_final = get_configured_llm(final_model_to_use, api_key)

    total_tokens = gemini_api.count_tokens_from_lc_messages(
        messages_for_pro, final_model_to_use, api_key
    )
    print(f"  - 最終的な合計入力トークン数（指示プロンプト含む）を計算しました: {total_tokens}")

    print(f"  - {final_model_to_use}への入力メッセージ数（指示プロンプト含む）: {len(messages_for_pro)}")
    try:
        response = llm_final.invoke(messages_for_pro)
        # 最終状態には、ループの過程を含んだ元の全メッセージを返す
        # これにより、次のターンのmemory_weaverは全コンテキストを把握できる
        all_messages.append(response)
        return {"messages": all_messages, "final_token_count": total_tokens}
    except Exception as e:
        print(f"  - 最終応答生成ノードでエラー: {e}")
        error_response_message = AIMessage(content=f"[エラー：最終応答の生成中に問題が発生しました。詳細: {e}]")
        all_messages.append(error_response_message)
        return {"messages": all_messages, "final_token_count": 0}

def call_tool_node(state: AgentState):
    """
    ツールを実行するノード。
    一度に実行するツールの数を物理的に制限し、APIのレートリミット超過を防ぐ。
    """
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
        "read_full_notepad": read_full_notepad,
        "edit_memory": edit_memory,                      # ★ 追加
        "add_secret_diary_entry": add_secret_diary_entry # ★ 追加
    }

    MAX_TOOLS_PER_TURN = 5 # 指示通り3から5に変更
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
                # character_nameを注入するロジックを更新
                if tool_name in [
                    "diary_search_tool", "conversation_memory_search_tool",
                    "add_to_notepad", "update_notepad", "delete_from_notepad", "read_full_notepad",
                    "edit_memory", "add_secret_diary_entry" # ★ 追加
                ]:
                    tool_args["character_name"] = state.get("character_name")
                    print(f"    - 引数に正しいキャラクター名 '{tool_args['character_name']}' を注入/上書きしました。")
                if tool_name in ["diary_search_tool", "conversation_memory_search_tool"]:
                    tool_args["api_key"] = state.get("api_key")
                    print(f"    - 引数にAPIキーを注入/上書きしました。")
                output = tool_to_call.invoke(tool_args)
            except Exception as e:
                output = f"[エラー：道具'{tool_name}'の実行に失敗しました。詳細: {e}]"
                traceback.print_exc()
        tool_messages.append(ToolMessage(content=str(output), tool_call_id=tool_call_id, name=tool_name))

    # 現在のカウントを取得し、1加算して返す
    current_count = state.get('tool_call_count', 0)
    return {"messages": tool_messages, "tool_call_count": current_count + 1}

def should_call_tool(state: AgentState):
    print("--- ルーティング判断 (should_call_tool) 実行 ---")

    # ★★★ ここからが追加/変更箇所 ★★★
    MAX_ITERATIONS = 5  # ループの最大回数を定義 (5回で十分なはず)
    tool_call_count = state.get('tool_call_count', 0)
    print(f"  - 現在のツール実行ループ回数: {tool_call_count}")

    if tool_call_count >= MAX_ITERATIONS:
        print(f"  - 警告: ツール実行ループが上限の {MAX_ITERATIONS} 回に達しました。")
        print("  - AIの判断を無視し、強制的に最終応答生成へ移行します。")
        return "final_response"
    # ★★★ ここまでが追加/変更箇所 ★★★

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

# workflow.set_entry_point("memory_weaver") # LangGraphの推奨に従い、add_edge(START,...)を使用
workflow.add_edge(START, "memory_weaver") # エントリーポイントを memory_weaver に設定

workflow.add_edge("memory_weaver", "tool_router")
workflow.add_conditional_edges(
    "tool_router",
    should_call_tool,
    {
        "call_tool": "call_tool",
        "final_response": "final_response"
    }
)
workflow.add_edge("call_tool", "tool_router") # ★★★ この行を復活させる ★★★
# workflow.add_edge("call_tool", "final_response") # この行は削除、またはコメントアウト
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
