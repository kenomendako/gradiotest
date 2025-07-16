# agent/graph.py の内容を、以下のコードで完全に置き換えてください

import os
import traceback
from typing import TypedDict, Annotated, List
from langchain_core.messages import SystemMessage, HumanMessage, BaseMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END, START, add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from datetime import datetime

from agent.prompts import MEMORY_WEAVER_PROMPT_TEMPLATE, ACTOR_PROMPT_TEMPLATE
from tools.space_tools import set_current_location, find_location_id_by_name
from tools.memory_tools import read_memory_by_path, edit_memory, add_secret_diary_entry, summarize_and_save_core_memory
from tools.notepad_tools import add_to_notepad, update_notepad, delete_from_notepad, read_full_notepad
from tools.web_tools import web_search_tool, read_url_tool
from rag_manager import diary_search_tool, conversation_memory_search_tool
import rag_manager
import config_manager
import mem0_manager

# --- 1. ツールと状態の定義 ---
all_tools = [
    set_current_location, find_location_id_by_name, read_memory_by_path, edit_memory,
    add_secret_diary_entry, summarize_and_save_core_memory, add_to_notepad,
    update_notepad, delete_from_notepad, read_full_notepad, web_search_tool,
    read_url_tool, diary_search_tool, conversation_memory_search_tool
]
tool_node = ToolNode(all_tools)

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    character_name: str
    api_key: str
    tavily_api_key: str

# --- 2. モデル初期化 ---
def get_configured_llm(model_name: str, api_key: str):
    return ChatGoogleGenerativeAI(model=model_name, google_api_key=api_key, convert_system_message_to_human=False)

# --- 3. グラフのノード定義 ---

def context_generator_node(state: AgentState):
    """【舞台裏】思考の前に、状況サマリーと情景描写を生成・統合するノード"""
    print("--- コンテキスト生成ノード (context_generator_node) 実行 ---")
    character_name = state['character_name']
    api_key = state['api_key']
    messages = state['messages']

    # 既存のメッセージから古いコンテキスト(SystemMessage)をクリア
    history_messages = [msg for msg in messages if not isinstance(msg, SystemMessage)]

    llm_flash = get_configured_llm("gemini-2.5-flash", api_key)

    # 記憶の織り手
    last_message_obj = next((msg for msg in reversed(history_messages) if not isinstance(msg, SystemMessage)), None)
    search_query = str(last_message_obj.content) if last_message_obj else "直近の出来事"
    long_term_memories_str = rag_manager.search_conversation_memory_for_summary(character_name=character_name, query=search_query, api_key=api_key)
    history_for_summary = history_messages[-config_manager.initial_memory_weaver_history_count_global:]
    recent_history_str = "\n".join([f"- {msg.type}: {str(msg.content)}" for msg in history_for_summary])
    summarizer_prompt = MEMORY_WEAVER_PROMPT_TEMPLATE.format(character_name=character_name, long_term_memories=long_term_memories_str, recent_history=recent_history_str)
    summary_text = llm_flash.invoke(summarizer_prompt).content

    # 時空の編纂者
    location_from_file = "living_space"
    try:
        location_file_path = os.path.join("characters", character_name, "current_location.txt")
        if os.path.exists(location_file_path):
            with open(location_file_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content: location_from_file = content
    except Exception as e: print(f"  - 警告: 現在地ファイル読込エラー: {e}")
    found_id = find_location_id_by_name.invoke({"location_name": location_from_file, "character_name": character_name})
    space_def = read_memory_by_path.invoke({"path": f"living_space.{found_id if found_id and not found_id.startswith('【エラー】') else location_from_file}", "character_name": character_name})
    now = datetime.now()
    scenery_prompt = f"空間定義:{space_def}\n時刻:{now.strftime('%H:%M')}\n季節:{now.month}月\n対話状況:{summary_text}\n以上の情報から1-2文で簡潔かつ美しい情景を描写:"
    scenery_text = llm_flash.invoke(scenery_prompt).content

    # キャラクタープロンプトとコアメモリ
    char_prompt_path = os.path.join("characters", character_name, "SystemPrompt.txt")
    core_memory_path = os.path.join("characters", character_name, "core_memory.txt")
    character_prompt = ""
    if os.path.exists(char_prompt_path):
        with open(char_prompt_path, 'r', encoding='utf-8') as f: character_prompt = f.read().strip()
    core_memory = ""
    if os.path.exists(core_memory_path):
        with open(core_memory_path, 'r', encoding='utf-8') as f: core_memory = f.read().strip()

    final_system_prompt_text = f"""
{ACTOR_PROMPT_TEMPLATE.format(character_name=character_name, character_prompt=character_prompt, core_memory=core_memory)}
---
【現在の状況サマリー】
{summary_text}
【現在の情景】
{scenery_text}
---
"""
    return {"messages": [SystemMessage(content=final_system_prompt_text)] + history_messages}

def actor_node(state: AgentState):
    """【主演俳優】コンテキストに基づき、ツール使用or応答生成を行うノード"""
    print("--- 主演ノード (actor_node) 実行 ---")
    llm_pro = get_configured_llm("gemini-2.5-pro", state['api_key'])
    llm_with_tools = llm_pro.bind_tools(all_tools)

    response = llm_with_tools.invoke(state['messages'])
    return {"messages": [response]}

def tool_executor_node(state: AgentState):
    """【舞台装置】AIが要求したツールを、必要なAPIキーと共に実行するノード"""
    print("--- ツール実行ノード (tool_executor_node) 実行 ---")
    tool_calls = state["messages"][-1].tool_calls
    if not tool_calls:
        return {}

    tool_outputs = []
    for call in tool_calls:
        tool_name = call["name"]
        tool_args = call["args"]
        print(f"  - 実行対象: {tool_name}, 引数: {tool_args}")

        tool_args['character_name'] = state['character_name']
        if tool_name == "web_search_tool":
            tool_args["api_key"] = state['tavily_api_key']
        else:
            tool_args["api_key"] = state['api_key']

        found_tool = False
        for tool in all_tools:
            if tool.name == tool_name:
                try:
                    output = tool.invoke(tool_args)
                    tool_outputs.append(ToolMessage(content=str(output), tool_call_id=call["id"]))
                except Exception as e:
                    tool_outputs.append(ToolMessage(content=f"ツール実行エラー: {e}", tool_call_id=call["id"]))
                found_tool = True
                break
        if not found_tool:
            tool_outputs.append(ToolMessage(content=f"エラー: ツール '{tool_name}' が見つかりません。", tool_call_id=call["id"]))
    return {"messages": tool_outputs}

# --- 4. グラフ構築 ---
workflow = StateGraph(AgentState)
workflow.add_node("context_generator", context_generator_node)
workflow.add_node("actor", actor_node)
workflow.add_node("tool_executor", tool_node)

workflow.add_edge(START, "context_generator")
workflow.add_edge("context_generator", "actor")

workflow.add_conditional_edges(
    "actor",
    tools_condition,
    {
        "tools": "tool_executor",
        END: END, # ツールが不要なら、グラフを終了
    },
)
# ツール実行後、再度コンテキスト生成からやり直すことで、変化した現実を反映する
workflow.add_edge("tool_executor", "context_generator")

app = workflow.compile()
print("--- 最終版：リアクティブ・単一アクターモデルのグラフがコンパイルされました ---")
