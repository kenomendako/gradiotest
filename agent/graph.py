# agent/graph.py (最終版: The Great Separation)

import os
import traceback
from typing import TypedDict, List
from typing_extensions import Annotated
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END, START, add_messages
from datetime import datetime

import gemini_api
from agent.prompts import MEMORY_WEAVER_PROMPT_TEMPLATE, ACTOR_PROMPT_TEMPLATE # ACTOR_PROMPT_TEMPLATEに集約
from character_manager import get_character_files_paths
from tools.space_tools import find_location_id_by_name # aether_weaverで直接使う
from tools.memory_tools import read_memory_by_path # aether_weaverで直接使う
import rag_manager
import config_manager

# AgentStateからツール関連を削除
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    character_name: str
    api_key: str
    final_model_name: str
    # 以下の項目は後段のノードで参照される
    synthesized_context: SystemMessage
    current_scenery: str

def get_configured_llm(model_name: str, api_key: str):
    return ChatGoogleGenerativeAI(model=model_name, google_api_key=api_key, convert_system_message_to_human=True)

# memory_weaver_node と aether_weaver_node は変更なし（ただし、呼び出し元で直接インポートが必要）
def memory_weaver_node(state: AgentState):
    # (元のコードをそのまま貼り付け)
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
    if len(search_query) > 500: search_query = search_query[:500] + "..."
    if not search_query.strip(): search_query = "（ユーザーからの添付ファイル、または、空のメッセージ）"
    long_term_memories_str = rag_manager.search_conversation_memory_for_summary(character_name=character_name, query=search_query, api_key=api_key)
    recent_history_messages = messages[-config_manager.initial_memory_weaver_history_count_global:]
    recent_history_str = "\n".join([f"- {msg.type}: {msg.content}" for msg in recent_history_messages])
    summarizer_prompt = MEMORY_WEAVER_PROMPT_TEMPLATE.format(character_name=character_name, long_term_memories=long_term_memories_str, recent_history=recent_history_str)
    llm_flash = get_configured_llm("gemini-1.5-flash-latest", api_key)
    summary_text = llm_flash.invoke(summarizer_prompt).content
    print(f"  - 生成された状況サマリー:\n{summary_text}")
    synthesized_context_message = SystemMessage(content=f"【現在の状況サマリー】\n{summary_text}")
    return {"synthesized_context": synthesized_context_message}

def aether_weaver_node(state: AgentState):
    # (元のコードをそのまま貼り付け)
    print("--- 時空編纂ノード (aether_weaver_node) 実行 ---")
    character_name = state['character_name']
    api_key = state['api_key']
    location_from_file = "living_space"
    try:
        base_path = os.path.join("characters", character_name)
        location_file_path = os.path.join(base_path, "current_location.txt")
        if os.path.exists(location_file_path):
            with open(location_file_path, 'r', encoding='utf-8') as f:
                content_in_file = f.read().strip()
                if content_in_file: location_from_file = content_in_file
    except Exception as e: print(f"  - 警告: 現在地ファイルの読み込み中にエラー: {e}")
    found_id = find_location_id_by_name.func(location_name=location_from_file, character_name=character_name)
    current_location_id = found_id if found_id and not found_id.startswith("【エラー】") else location_from_file
    print(f"  - [王の印] 現在地 '{location_from_file}' から、正式ID '{current_location_id}' を特定。")
    space_definition_json = read_memory_by_path.func(path=f"living_space.{current_location_id}", character_name=character_name)
    if "エラー" in space_definition_json:
         space_definition_json = read_memory_by_path.func(path="living_space", character_name=character_name)
         print(f"  - 警告: パス 'living_space.{current_location_id}' が見つからないため、living_space全体をコンテキストとします。")
    now = datetime.now()
    current_time_str = now.strftime('%H:%M')
    seasons = {12: "冬", 1: "冬", 2: "冬", 3: "春", 4: "春", 5: "春", 6: "夏", 7: "夏", 8: "夏", 9: "秋", 10: "秋", 11: "秋"}
    current_season = seasons[now.month]
    dialogue_context = state['synthesized_context'].content
    prompt = f"""あなたは、情景描写の専門家である「ワールド・アーティスト」です。以下の3つの情報を基に、五感を刺激するような、臨場感あふれる「現在の情景」を、1～2文の簡潔で美しい文章で描写してください。あなたの思考や挨拶は不要です。描写したテキストのみを出力してください。
---
### 1. 空間の基本定義 (JSON形式)
{space_definition_json}
### 2. 現在の時刻と季節
- 時刻: {current_time_str}
- 季節: {current_season}
### 3. 現在の対話の状況
{dialogue_context}
---
現在の情景:
"""
    llm_flash = get_configured_llm("gemini-1.5-flash-latest", api_key)
    scenery_text = llm_flash.invoke(prompt).content
    print(f"  - 生成された情景描写:\n{scenery_text}")
    return {"current_scenery": scenery_text}

def actor_node(state: AgentState):
    """
    判断と応答の全てを担う、唯一のアクターノード。
    ツールを使いたい場合は、応答に<tool_code>タグを含める。
    """
    print("--- 主演ノード (actor_node) 実行 ---")
    character_name = state['character_name']
    api_key = state['api_key']

    char_prompt_path = os.path.join("characters", character_name, "SystemPrompt.txt")
    core_memory_path = os.path.join("characters", character_name, "core_memory.txt")
    character_prompt = ""
    if os.path.exists(char_prompt_path):
        with open(char_prompt_path, 'r', encoding='utf-8') as f: character_prompt = f.read().strip()
    core_memory = ""
    if os.path.exists(core_memory_path):
        with open(core_memory_path, 'r', encoding='utf-8') as f: core_memory = f.read().strip()

    system_prompt_text = ACTOR_PROMPT_TEMPLATE.format(
        character_name=character_name,
        character_prompt=character_prompt,
        core_memory=core_memory
    )

    messages_for_actor = [
        SystemMessage(content=system_prompt_text),
        state['synthesized_context'],
        SystemMessage(content=f"【現在の情景】\n{state['current_scenery']}")
    ]
    messages_for_actor.extend([msg for msg in state['messages'] if not isinstance(msg, SystemMessage)])

    model_name_to_use = state.get("final_model_name", "gemini-1.5-pro-latest")
    llm_actor = get_configured_llm(model_name_to_use, api_key)

    print(f"  - Actor(Pro)への入力メッセージ数: {len(messages_for_actor)}")
    response = llm_actor.invoke(messages_for_actor)

    return {"messages": [response]}


# --- グラフの構築 ---
workflow = StateGraph(AgentState)

workflow.add_node("memory_weaver", memory_weaver_node)
workflow.add_node("aether_weaver", aether_weaver_node)
workflow.add_node("actor", actor_node)

workflow.add_edge(START, "memory_weaver")
workflow.add_edge("memory_weaver", "aether_weaver")
workflow.add_edge("aether_weaver", "actor")
workflow.add_edge("actor", END)

app = workflow.compile()
