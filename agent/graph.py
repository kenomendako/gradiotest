# agent/graph.py (全体をこのコードに置き換えてください)

import os
import traceback
from typing import TypedDict, List
from typing_extensions import Annotated
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END, START, add_messages
from langchain_core.tools import tool

import config_manager
import gemini_api
import rag_manager
from agent.prompts import MEMORY_WEAVER_PROMPT_TEMPLATE, TOOL_ROUTER_PROMPT_STRICT
from tools.web_tools import read_url_tool, web_search_tool
from tools.notepad_tools import add_to_notepad, update_notepad, delete_from_notepad, read_full_notepad
from tools.memory_tools import edit_memory, add_secret_diary_entry, summarize_and_save_core_memory

# AgentStateから initial_intent を削除
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    character_name: str
    api_key: str
    final_model_name: str
    final_token_count: int
    synthesized_context: SystemMessage
    retrieved_long_term_memories: str
    tool_call_count: int

def get_configured_llm(model_name: str, api_key: str, bind_tools: List = None):
    print(f"  - 安全設定をLangChainのデフォルト値に委ねてモデルを初期化します。")
    llm = ChatGoogleGenerativeAI(model=model_name, google_api_key=api_key)
    if bind_tools:
        llm = llm.bind_tools(bind_tools)
        print(f"  - モデル '{model_name}' に道具: {[tool.name for tool in bind_tools]} をバインドしました。")
    else:
        print(f"  - モデル '{model_name}' は道具なしで初期化されました。")
    return llm

def memory_weaver_node(state: AgentState):
    # (このノードの内部ロジックに変更はありません)
    print("--- 魂を織りなす記憶ノード (memory_weaver_node) 実行 ---")
    messages = state['messages']
    character_name = state['character_name']
    api_key = state['api_key']
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
    long_term_memories_str = rag_manager.search_conversation_memory_for_summary(character_name=character_name, query=search_query, api_key=api_key)
    recent_history_messages = messages[-config_manager.initial_memory_weaver_history_count_global:]
    recent_history_str = "\n".join([f"- {msg.type}: {msg.content}" for msg in recent_history_messages])
    print(f"  - 直近の会話履歴 {len(recent_history_messages)} 件を、要約の、材料とします。")
    summarizer_prompt = MEMORY_WEAVER_PROMPT_TEMPLATE.format(character_name=character_name, long_term_memories=long_term_memories_str, recent_history=recent_history_str)
    llm_flash = get_configured_llm("gemini-2.5-flash", api_key)
    summary_text = llm_flash.invoke(summarizer_prompt).content
    print(f"  - 生成された状況サマリー:\n{summary_text}")
    synthesized_context_message = SystemMessage(content=f"【現在の状況サマリー】\n{summary_text}")
    return {"synthesized_context": synthesized_context_message, "retrieved_long_term_memories": long_term_memories_str}

# 【新】ツールルーターノード
def tool_router_node(state: AgentState):
    print("--- ツールルーターノード (Flash) 実行 ---")
    messages_for_router = []
    messages_for_router.append(SystemMessage(content=TOOL_ROUTER_PROMPT_STRICT))
    messages_for_router.append(state['synthesized_context'])
    last_human_message_index = -1
    for i in range(len(state['messages']) - 1, -1, -1):
        if isinstance(state['messages'][i], HumanMessage):
            last_human_message_index = i
            break
    if last_human_message_index != -1:
        messages_for_router.extend(state['messages'][last_human_message_index:])
    else:
        if state['messages']:
            messages_for_router.append(state['messages'][-1])
    api_key = state['api_key']
    available_tools = [
        rag_manager.diary_search_tool, rag_manager.conversation_memory_search_tool,
        web_search_tool, read_url_tool,
        add_to_notepad, update_notepad, delete_from_notepad, read_full_notepad,
        edit_memory, add_secret_diary_entry, summarize_and_save_core_memory
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

# 【新】最終応答生成ノード
def final_response_node(state: AgentState):
    print("--- 最終応答生成ノード (Pro) 実行 ---")
    messages_for_pro = []
    system_prompt = next((msg for msg in state['messages'] if isinstance(msg, SystemMessage)), None)
    if system_prompt:
        messages_for_pro.append(system_prompt)
    retrieved_memories = state.get('retrieved_long_term_memories', '')
    if retrieved_memories and "関連する長期記憶はありませんでした" not in retrieved_memories:
        memory_context = f"【参考：関連する可能性のある長期記憶の断片】\n{retrieved_memories}"
        messages_for_pro.append(SystemMessage(content=memory_context))
    messages_for_pro.extend(state['messages'])
    api_key = state['api_key']
    final_model_to_use = state.get("final_model_name", "gemini-2.5-pro")
    llm_final = get_configured_llm(final_model_to_use, api_key)
    total_tokens = gemini_api.count_tokens_from_lc_messages(messages_for_pro, final_model_to_use, api_key)
    print(f"  - 最終的な合計入力トークン数: {total_tokens}")
    response = llm_final.invoke(messages_for_pro)
    final_messages = state['messages'] + [response]
    return {"messages": final_messages, "final_token_count": total_tokens}

# call_tool_nodeは、api_keyを注入するロジックの追加が必要です
def call_tool_node(state: AgentState):
    # (このノードの内部ロジックは前回の提案から変更なし)
    print(f"--- 道具実行ノード (call_tool_node) 実行 ---")
    last_message = state['messages'][-1]
    if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
        return {}
    tool_messages = []
    available_tools_map = {
        "diary_search_tool": rag_manager.diary_search_tool, "conversation_memory_search_tool": rag_manager.conversation_memory_search_tool,
        "web_search_tool": web_search_tool, "read_url_tool": read_url_tool,
        "add_to_notepad": add_to_notepad, "update_notepad": update_notepad, "delete_from_notepad": delete_from_notepad, "read_full_notepad": read_full_notepad,
        "edit_memory": edit_memory, "add_secret_diary_entry": add_secret_diary_entry, "summarize_and_save_core_memory": summarize_and_save_core_memory
    }
    MAX_TOOLS_PER_TURN = 5
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
                if tool_name in ["diary_search_tool", "conversation_memory_search_tool", "add_to_notepad", "update_notepad", "delete_from_notepad", "read_full_notepad", "edit_memory", "add_secret_diary_entry"]:
                    tool_args["character_name"] = state.get("character_name")
                    print(f"    - 引数に正しいキャラクター名 '{tool_args['character_name']}' を注入/上書きしました。")
                if tool_name in ["diary_search_tool", "conversation_memory_search_tool", "summarize_and_save_core_memory"]:
                    tool_args["api_key"] = state.get("api_key")
                    print(f"    - 引数にAPIキーを注入/上書きしました。")
                output = tool_to_call.invoke(tool_args)
            except Exception as e:
                output = f"[エラー：道具'{tool_name}'の実行に失敗しました。詳細: {e}]"
                traceback.print_exc()
        tool_messages.append(ToolMessage(content=str(output), tool_call_id=tool_call_id, name=tool_name))
    current_count = state.get('tool_call_count', 0)
    return {"messages": tool_messages, "tool_call_count": current_count + 1}

# 【新】ルーティング判断ロジック
def should_call_tool(state: AgentState):
    print("--- ルーティング判断 (should_call_tool) 実行 ---")
    MAX_ITERATIONS = 5
    tool_call_count = state.get('tool_call_count', 0)
    print(f"  - 現在のツール実行ループ回数: {tool_call_count}")
    if tool_call_count >= MAX_ITERATIONS:
        print(f"  - 警告: ツール実行ループが上限の {MAX_ITERATIONS} 回に達しました。強制的に最終応答へ。")
        return "final_response"
    last_message = state['messages'][-1] if state['messages'] else None
    if isinstance(last_message, AIMessage) and hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        print("  - 判断: ツール呼び出しあり。call_tool_node へ。")
        return "call_tool"
    else:
        print("  - 判断: ツール呼び出しなし。final_response_node へ。")
        return "final_response"

# 【新】グラフ構築
workflow = StateGraph(AgentState)
workflow.add_node("memory_weaver", memory_weaver_node)
workflow.add_node("tool_router", tool_router_node)
workflow.add_node("call_tool", call_tool_node)
workflow.add_node("final_response", final_response_node)

workflow.add_edge(START, "memory_weaver")
workflow.add_edge("memory_weaver", "tool_router")
workflow.add_conditional_edges(
    "tool_router",
    should_call_tool,
    {
        "call_tool": "call_tool",
        "final_response": "final_response"
    }
)
workflow.add_edge("call_tool", "tool_router")
workflow.add_edge("final_response", END)

app = workflow.compile()
