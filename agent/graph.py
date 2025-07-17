# agent/graph.py の、内容を、以下の、最終版で、完全に、置き換えてください

import os
import traceback
from typing import TypedDict, Annotated, List
from langchain_core.messages import SystemMessage, HumanMessage, BaseMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END, START, add_messages
from langgraph.prebuilt import tools_condition
from datetime import datetime

from agent.prompts import ACTOR_PROMPT_TEMPLATE
from tools.space_tools import set_current_location, find_location_id_by_name
from tools.memory_tools import read_memory_by_path, edit_memory, add_secret_diary_entry, summarize_and_save_core_memory, read_full_memory
from tools.notepad_tools import add_to_notepad, update_notepad, delete_from_notepad, read_full_notepad
from tools.web_tools import web_search_tool, read_url_tool
from tools.image_tools import generate_image
from rag_manager import diary_search_tool, conversation_memory_search_tool
import config_manager
import mem0_manager

# --- 1. ツール定義 ---
all_tools = [
    set_current_location, find_location_id_by_name, read_memory_by_path, edit_memory,
    add_secret_diary_entry, summarize_and_save_core_memory, add_to_notepad,
    update_notepad, delete_from_notepad, read_full_notepad, web_search_tool,
    read_url_tool, diary_search_tool, conversation_memory_search_tool,
    generate_image, read_full_memory # ★★★ この行を修正 ★★★
]

# --- 2. 状態定義 ---
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    character_name: str
    api_key: str
    tavily_api_key: str
    model_name: str
    system_prompt: SystemMessage

# --- 3. モデル初期化 ---
def get_configured_llm(model_name: str, api_key: str):
    return ChatGoogleGenerativeAI(model=model_name, google_api_key=api_key, convert_system_message_to_human=False)

# --- 4. グラフのノード定義 ---
def context_generator_node(state: AgentState):
    print("--- コンテキスト生成ノード (context_generator_node) 実行 ---")
    character_name = state['character_name']
    api_key = state['api_key']
    scenery_text = "（現在の場所の情景描写は、取得できませんでした）"
    try:
        llm_flash = get_configured_llm("gemini-1.5-flash", api_key)
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

        if "エラー" not in space_def:
            now = datetime.now()
            scenery_prompt = f"空間定義:{space_def}\n時刻:{now.strftime('%H:%M')}\n季節:{now.month}月\n以上の情報から2-3文で、人物描写を排し気温・湿度・音・匂い・感触まで伝わるような精緻で写実的な情景を描写:"
            scenery_text = llm_flash.invoke(scenery_prompt).content
            print(f"  - 生成された情景描写: {scenery_text}")
        else:
            print(f"  - 警告: 場所「{location_from_file}」の定義が見つかりません。")

    except Exception as e:
        print(f"--- 警告: 情景描写の生成中にエラーが発生しました ---\n{traceback.format_exc()}")

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
【現在の情景】
{scenery_text}
---
"""
    return {"system_prompt": SystemMessage(content=final_system_prompt_text)}

def actor_node(state: AgentState):
    print("--- 主演ノード (actor_node) 実行 ---")
    llm = get_configured_llm(state['model_name'], state['api_key'])
    llm_with_tools = llm.bind_tools(all_tools)
    messages_for_actor = [state['system_prompt']] + state['messages']
    response = llm_with_tools.invoke(messages_for_actor)
    return {"messages": [response]}

def tool_executor_node(state: AgentState):
    print("--- ツール実行ノード (tool_executor_node) 実行 ---")
    tool_calls = state["messages"][-1].tool_calls
    if not tool_calls:
        print("  - 警告: tool_callsが空のため、ツール実行をスキップします。")
        return {}

    tool_outputs = []
    for call in tool_calls:
        tool_name, tool_args = call["name"], call["args"]
        print(f"  - 実行対象: {tool_name}, 引数: {tool_args}")
        tool_args.update({'character_name': state['character_name'], 'api_key': state['api_key']})
        if tool_name == "web_search_tool":
            tool_args["api_key"] = state['tavily_api_key']

        found_tool = next((t for t in all_tools if t.name == tool_name), None)
        if found_tool:
            try:
                output = found_tool.invoke(tool_args)
                tool_outputs.append(ToolMessage(content=str(output), tool_call_id=call["id"]))
            except Exception as e:
                print(f"  - エラー: ツール '{tool_name}' の実行中にエラーが発生しました: {e}")
                traceback.print_exc()
                tool_outputs.append(ToolMessage(content=f"ツール実行エラー: {e}", tool_call_id=call["id"]))
        else:
            print(f"  - エラー: ツール '{tool_name}' が見つかりません。")
            tool_outputs.append(ToolMessage(content=f"エラー: ツール '{tool_name}' が見つかりません。", tool_call_id=call["id"]))
    return {"messages": tool_outputs}

# --- 5. グラフ構築 ---
workflow = StateGraph(AgentState)
workflow.add_node("context_generator", context_generator_node)
workflow.add_node("actor", actor_node)
workflow.add_node("tool_executor", tool_executor_node)

workflow.add_edge(START, "context_generator")
workflow.add_edge("context_generator", "actor")

workflow.add_conditional_edges(
    "actor",
    tools_condition,
    {"tools": "tool_executor", END: END}
)
workflow.add_edge("tool_executor", "context_generator")

app = workflow.compile()
print("--- 最終版v7：記憶の全文閲覧ツールを統合したグラフがコンパイルされました ---")
