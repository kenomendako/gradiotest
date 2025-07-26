# agent/graph.py をこのコードで完全に置き換えてください

import os
import re
import traceback
from typing import TypedDict, Annotated, List, Literal
from langchain_core.messages import SystemMessage, BaseMessage, ToolMessage, AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END, START, add_messages
from datetime import datetime
from langgraph.prebuilt import ToolNode

from agent.prompts import CORE_PROMPT_TEMPLATE
from tools.space_tools import set_current_location, find_location_id_by_name
from tools.memory_tools import read_memory_by_path, edit_memory, add_secret_diary_entry, summarize_and_save_core_memory, read_full_memory
from tools.notepad_tools import add_to_notepad, update_notepad, delete_from_notepad, read_full_notepad
from tools.web_tools import web_search_tool, read_url_tool
from tools.image_tools import generate_image
from tools.alarm_tools import set_personal_alarm
from rag_manager import diary_search_tool, conversation_memory_search_tool

all_tools = [
    set_current_location, find_location_id_by_name, read_memory_by_path, edit_memory,
    add_secret_diary_entry, summarize_and_save_core_memory, add_to_notepad,
    update_notepad, delete_from_notepad, read_full_notepad, web_search_tool,
    read_url_tool, diary_search_tool, conversation_memory_search_tool,
    generate_image, read_full_memory, set_personal_alarm
]

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    character_name: str
    api_key: str
    tavily_api_key: str
    model_name: str
    system_prompt: SystemMessage
    send_core_memory: bool
    send_scenery: bool
    current_scenery: str

def get_configured_llm(model_name: str, api_key: str):
    return ChatGoogleGenerativeAI(model=model_name, google_api_key=api_key, convert_system_message_to_human=False)

def context_generator_node(state: AgentState):
    if not state.get("send_scenery", True):
        # ... (早期リターンのロジック) ...
        return {"system_prompt": SystemMessage(content=formatted_core_prompt)}

    print("--- コンテキスト生成ノード (context_generator_node) 実行 ---")
    # ... (場所の特定と情景描写生成のロジック) ...

    # ... (プロンプト変数の準備) ...

    formatted_core_prompt = CORE_PROMPT_TEMPLATE.format_map(SafeDict(prompt_vars))

    final_system_prompt_text = (
        f"{formatted_core_prompt}\n"
        "---\n"
        f"【現在の情景】\n{scenery_text}\n"
        "---"
    )

    if not space_def.startswith("【Error】"):
        print(f"  - 読み込まれた場所の定義:\n```\n{space_def}\n```")

    return {
        "system_prompt": SystemMessage(content=final_system_prompt_text),
        "current_scenery": scenery_text
    }

# ... (agent_node とルーター、グラフ構築は変更なし) ...
