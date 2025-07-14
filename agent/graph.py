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
from agent.prompts import MEMORY_WEAVER_PROMPT_TEMPLATE, TOOL_ROUTER_PROMPT_STRICT
from tools.web_tools import read_url_tool, web_search_tool
from tools.notepad_tools import add_to_notepad, update_notepad, delete_from_notepad, read_full_notepad
from tools.memory_tools import edit_memory, add_secret_diary_entry, summarize_and_save_core_memory # コアメモリツールも追加

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
    initial_intent: str # ★★★ AIの最初の意志（計画）を保持するキーを追加 ★★★

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


# 【新設】これまでのtool_routerとfinal_responseを統合した、新しい「心」
def nexus_mind_node(state: AgentState):
    """
    AIの思考と応答生成の中心。初回呼び出しとループ中で役割が変わる。
    """
    print("--- 統合思考ノード (nexus_mind_node) 実行 ---")

    messages_for_mind = []
    # システムプロンプトは常に含める
    system_prompt = next((msg for msg in state['messages'] if isinstance(msg, SystemMessage)), None)
    if system_prompt:
        messages_for_mind.append(system_prompt)

    is_first_call = state.get('tool_call_count', 0) == 0

    if is_first_call:
        print("  - [初回呼び出し] 完全な履歴を基に、応答または行動計画を生成します。")
        # 初回は、memory_weaverの要約は使わず、生の全履歴を渡す
        messages_for_mind.extend(state['messages'])
    else:
        print("  - [ループ内呼び出し] AIの当初の意志とツール結果を基に、次の行動を判断します。")
        # ループ内では、当初の意志、直近のユーザーメッセージ、そしてツール関連のメッセージのみを引き継ぐ

        # 1. 当初の意志をシステムメッセージとして追加
        initial_intent_text = state.get('initial_intent', '（エラー：当初の意志が見つかりません）')
        intent_prompt = f"""【あなたの当初の行動計画】
{initial_intent_text}
---
上記の計画を達成するため、提供された最新のツール実行結果を分析し、次の行動を判断してください。
全てのタスクが完了したと判断した場合にのみ、最終的な応答を生成してください。"""
        messages_for_mind.append(SystemMessage(content=intent_prompt))

        # 2. 最後のユーザーメッセージと、それ以降のツール関連メッセージを追加
        last_human_message_index = -1
        for i in range(len(state['messages']) - 1, -1, -1):
            if isinstance(state['messages'][i], HumanMessage):
                last_human_message_index = i
                break

        if last_human_message_index != -1:
            messages_for_mind.extend(state['messages'][last_human_message_index:])
        else:
            # 万が一ユーザーメッセージが見つからない場合
            messages_for_mind.append(state['messages'][-1])

    api_key = state['api_key']
    final_model_to_use = state.get("final_model_name", "gemini-2.5-pro")

    available_tools = [
        rag_manager.diary_search_tool,
        rag_manager.conversation_memory_search_tool,
        web_search_tool,
        read_url_tool,
        add_to_notepad,
        update_notepad,
        delete_from_notepad,
        read_full_notepad,
        edit_memory,
        add_secret_diary_entry,
        summarize_and_save_core_memory # UIからだけでなく、AIの判断でも実行できるよう追加
    ]

    llm_pro_with_tools = get_configured_llm(final_model_to_use, api_key, available_tools)

    print(f"  - {final_model_to_use}への入力メッセージ数: {len(messages_for_mind)}")
    response = llm_pro_with_tools.invoke(messages_for_mind)

    # 初回呼び出し時にツール使用を決めた場合、その応答（思考）を「当初の意志」として保存する
    if is_first_call and hasattr(response, 'tool_calls') and response.tool_calls:
        # 応答のテキスト部分（思考や計画が書かれているはず）を抽出
        initial_intent_content = response.content if isinstance(response.content, str) else str(response)
        print(f"  - [意志の記録] AIの当初の行動計画を記録しました:\n{initial_intent_content}")
        return {"messages": [response], "initial_intent": initial_intent_content}

    return {"messages": [response]}


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
                # ★★★ ここから修正 ★★★
                # api_keyを必要とするツールに、現在のstateからapi_keyを注入する
                if tool_name in ["diary_search_tool", "conversation_memory_search_tool", "summarize_and_save_core_memory"]:
                    tool_args["api_key"] = state.get("api_key")
                    print(f"    - 引数にAPIキーを注入/上書きしました。")
                # ★★★ 修正ここまで ★★★

                output = tool_to_call.invoke(tool_args)
            except Exception as e:
                output = f"[エラー：道具'{tool_name}'の実行に失敗しました。詳細: {e}]"
                traceback.print_exc()
        tool_messages.append(ToolMessage(content=str(output), tool_call_id=tool_call_id, name=tool_name))

    # 現在のカウントを取得し、1加算して返す
    current_count = state.get('tool_call_count', 0)
    return {"messages": tool_messages, "tool_call_count": current_count + 1}

# 【改訂】ルーティング判断ロジック
def should_call_tool_or_finish(state: AgentState):
    print("--- ルーティング判断 (should_call_tool_or_finish) 実行 ---")

    # ループ回数チェックは維持
    MAX_ITERATIONS = 5
    tool_call_count = state.get('tool_call_count', 0)
    print(f"  - 現在のツール実行ループ回数: {tool_call_count}")
    if tool_call_count >= MAX_ITERATIONS:
        print(f"  - 警告: ツール実行ループが上限の {MAX_ITERATIONS} 回に達しました。強制的に終了します。")
        return END # 直接ENDを返す

    last_message = state['messages'][-1] if state['messages'] else None

    if isinstance(last_message, AIMessage) and hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        print("  - 判断: ツール呼び出しあり。call_tool_node へ。")
        return "call_tool"
    else:
        # ツール呼び出しがない = AIが応答生成した、ということなのでグラフを終了
        print("  - 判断: ツール呼び出しなし。AIが応答を完了。グラフを終了します。")
        return END

# グラフの構築
workflow = StateGraph(AgentState)

# ノードの定義
workflow.add_node("memory_weaver", memory_weaver_node)
workflow.add_node("nexus_mind", nexus_mind_node) # 新しい中心ノード
workflow.add_node("call_tool", call_tool_node)

# エッジ（繋がり）の定義
workflow.add_edge(START, "memory_weaver")
workflow.add_edge("memory_weaver", "nexus_mind")

# nexus_mindノードからの条件分岐
workflow.add_conditional_edges(
    "nexus_mind",
    should_call_tool_or_finish, # 新しい判断関数
    {
        "call_tool": "call_tool",
        END: END
    }
)

# ツール実行後は、再びnexus_mindに戻る（ループ）
workflow.add_edge("call_tool", "nexus_mind")

app = workflow.compile()

