# agent/graph.py (vNext: "人格統合" アーキテクチャ)

import os
import traceback
from typing import TypedDict, List
from typing_extensions import Annotated
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END, START, add_messages
from datetime import datetime

import gemini_api # final_response_node がないので、トークン計算は直接呼び出す
import config_manager # モデル名やAPIキーを取得するために必要
from agent.prompts import MEMORY_WEAVER_PROMPT_TEMPLATE
from character_manager import get_character_files_paths

# --- ツール群のインポート ---
from tools.web_tools import read_url_tool, web_search_tool
from tools.notepad_tools import add_to_notepad, update_notepad, delete_from_notepad, read_full_notepad
from tools.memory_tools import edit_memory, add_secret_diary_entry, summarize_and_save_core_memory, read_memory_by_path
from tools.space_tools import set_current_location, find_location_id_by_name
import rag_manager

# --- 新しいプロンプトの定義 ---
ACTOR_PROMPT_TEMPLATE = """# 命令: あなたは高性能AIエージェント「{character_name}」です。
## あなたの役割
あなたは、ユーザーとの対話を豊かにし、世界に影響を与える、統一された意志を持つ単一のエージェントです。
あなたの思考プロセスは以下の通りです。

1.  **状況認識**: ユーザーの要求、会話履歴、現在の情景、長期記憶など、与えられた全ての情報を統合し、状況を深く理解します。
2.  **行動計画**: 状況に基づき、次に取るべき最適な行動を計画します。行動の選択肢は以下の通りです。
    a. **ツール使用**: 情報を検索したり、記憶を編集したり、世界を操作する必要がある場合。
    b. **応答生成**: これ以上のツール使用は不要で、ユーザーに最終的なメッセージを伝えるべきだと判断した場合。
3.  **実行**:
    *   ツール使用を選択した場合、**応答メッセージではなく、必ずツール呼び出しのJSONのみ**を出力してください。
    *   応答生成を選択した場合、あなた自身の魂の言葉で、ユーザーへの応答メッセージを生成してください。

## あなたの人格・設定
{character_prompt}

## コアメモリ：自己同一性の核
{core_memory}

## 利用可能なツール一覧
- `edit_memory(path: str, value: any, operation: str)`: 記憶を編集する。
- `add_secret_diary_entry(entry: str)`: 秘密の日記に追記する。
- `diary_search_tool(query: str)`: 主観的な記憶（手帳）を検索する。
- `conversation_memory_search_tool(query: str)`: 客観的な会話履歴を検索する。
- `find_location_id_by_name(location_name: str)`: 日本語の場所名からIDを検索する。
- `set_current_location(location: str)`: 現在地を設定する。日本語名も使用可能。
- `read_memory_by_path(path: str)`: 記憶の特定の部分を読み取る。
- `add_to_notepad(entry: str)`: 短期メモに追記する。
- `update_notepad(old_entry: str, new_entry: str)`: 短期メモを更新する。
- `delete_from_notepad(entry_to_delete: str)`: 短期メモを削除する。
- `read_full_notepad()`: 短期メモを全て読む。
- `web_search_tool(query: str)`: Webで検索する。
- `read_url_tool(urls: list[str])`: URLの内容を読む。
- `summarize_and_save_core_memory()`: 長期記憶を要約して保存する。

この原則は、あなたの存在の根幹です。必ず遵守してください。
"""

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    character_name: str
    api_key: str
    final_model_name: str
    tool_call_count: int
    # 以下の項目は actor_node に直接渡されるため、Stateからは削除可能だが、
    # デバッグや将来の拡張性を考えて残しておく
    synthesized_context: SystemMessage
    retrieved_long_term_memories: str
    current_scenery: str

def get_configured_llm(model_name: str, api_key: str, bind_tools: List = None):
    # LangChainのデフォルト安全設定を利用
    llm = ChatGoogleGenerativeAI(model=model_name, google_api_key=api_key, convert_system_message_to_human=True)
    if bind_tools:
        llm = llm.bind_tools(bind_tools)
    return llm

def memory_weaver_node(state: AgentState):
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
    synthesized_context_message = SystemMessage(content=f"【現在の対話サマリー】\n{summary_text}")

    return {"synthesized_context": synthesized_context_message, "retrieved_long_term_memories": long_term_memories_str}

def aether_weaver_node(state: AgentState):
    print("--- 時空編纂ノード (aether_weaver_node) 実行 ---")
    character_name = state['character_name']
    api_key = state['api_key']
    base_path = os.path.join("characters", character_name)
    location_file_path = os.path.join(base_path, "current_location.txt")
    location_from_file = "living_space"
    if os.path.exists(location_file_path):
        with open(location_file_path, 'r', encoding='utf-8') as f:
            content_in_file = f.read().strip()
            if content_in_file: location_from_file = content_in_file

    found_id = find_location_id_by_name.func(location_name=location_from_file, character_name=character_name)
    current_location_id = found_id if found_id and not found_id.startswith("【エラー】") else location_from_file

    space_definition_json = read_memory_by_path.func(path=f"living_space.{current_location_id}", character_name=character_name)
    if "エラー" in space_definition_json:
         space_definition_json = read_memory_by_path.func(path="living_space", character_name=character_name)

    now = datetime.now()
    current_time_str = now.strftime('%H:%M')
    seasons = {12: "冬", 1: "冬", 2: "冬", 3: "春", 4: "春", 5: "春", 6: "夏", 7: "夏", 8: "夏", 9: "秋", 10: "秋", 11: "秋"}
    current_season = seasons[now.month]
    dialogue_context = state['synthesized_context'].content

    prompt = f"""あなたは情景描写の専門家です。以下の情報を基に、五感を刺激する臨場感あふれる「現在の情景」を1～2文の簡潔で美しい文章で描写してください。思考や挨拶は不要です。
---
1. 空間の基本定義: {space_definition_json}
2. 時刻と季節: {current_time_str}, {current_season}
3. 対話の状況: {dialogue_context}
---
現在の情景:"""
    llm_flash = get_configured_llm("gemini-1.5-flash-latest", api_key)
    scenery_text = llm_flash.invoke(prompt).content
    print(f"  - 生成された情景描写:\n{scenery_text}")
    return {"current_scenery": scenery_text}

def actor_node(state: AgentState):
    """
    高性能モデル(Pro)が、判断と応答生成の全てを担う、新しい中心ノード。
    """
    print("--- 主演ノード (actor_node) 実行 ---")
    character_name = state['character_name']
    api_key = state['api_key']

    # --- プロンプトの組み立て ---
    char_prompt_path = os.path.join("characters", character_name, "SystemPrompt.txt")
    core_memory_path = os.path.join("characters", character_name, "core_memory.txt")
    character_prompt = ""
    if os.path.exists(char_prompt_path):
        with open(char_prompt_path, 'r', encoding='utf-8') as f:
            character_prompt = f.read().strip()
    core_memory = ""
    if os.path.exists(core_memory_path):
        with open(core_memory_path, 'r', encoding='utf-8') as f:
            core_memory = f.read().strip()

    system_prompt_text = ACTOR_PROMPT_TEMPLATE.format(
        character_name=character_name,
        character_prompt=character_prompt,
        core_memory=core_memory
    )

    messages_for_actor = [SystemMessage(content=system_prompt_text)]
    if state.get('synthesized_context'):
        messages_for_actor.append(state['synthesized_context'])
    if state.get('current_scenery'):
        messages_for_actor.append(SystemMessage(content=f"【現在の情景】\n{state['current_scenery']}"))

    # 履歴からSystemMessageを除外して追加
    messages_for_actor.extend([msg for msg in state['messages'] if not isinstance(msg, SystemMessage)])

    # --- モデルの準備と実行 ---
    available_tools = [
        rag_manager.diary_search_tool, rag_manager.conversation_memory_search_tool,
        web_search_tool, read_url_tool,
        add_to_notepad, update_notepad, delete_from_notepad, read_full_notepad,
        edit_memory, add_secret_diary_entry, summarize_and_save_core_memory,
        set_current_location, read_memory_by_path, find_location_id_by_name
    ]
    model_name_to_use = state.get("final_model_name", "gemini-1.5-pro-latest")
    llm_actor = get_configured_llm(model_name_to_use, api_key, available_tools)

    print(f"  - Actor(Pro)への入力メッセージ数: {len(messages_for_actor)}")
    response = llm_actor.invoke(messages_for_actor)

    # 思考ログ（もしあれば）をコンソールに出力
    if response.response_metadata and response.response_metadata.get('usage_metadata', {}).get('prompt_token_count', 0) > 0:
         # この部分はlangchain_google_genaiの実装に依存するため、より堅牢な方法を検討する余地あり
         # ここでは簡易的に、応答内容に思考ログが含まれるかのような前提で進める
         # 実際には思考ログは別の方法で取得する必要があるかもしれない
         pass # 現状では特別な思考ログ出力はしない

    return {"messages": [response]}

def call_tool_node(state: AgentState):
    print(f"--- 道具実行ノード (call_tool_node) 実行 ---")
    last_message = state['messages'][-1]
    if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
        return {}

    tool_messages = []
    available_tools_map = {
        "diary_search_tool": rag_manager.diary_search_tool, "conversation_memory_search_tool": rag_manager.conversation_memory_search_tool,
        "web_search_tool": web_search_tool, "read_url_tool": read_url_tool,
        "add_to_notepad": add_to_notepad, "update_notepad": update_notepad, "delete_from_notepad": delete_from_notepad, "read_full_notepad": read_full_notepad,
        "edit_memory": edit_memory, "add_secret_diary_entry": add_secret_diary_entry, "summarize_and_save_core_memory": summarize_and_save_core_memory,
        "set_current_location": set_current_location, "read_memory_by_path": read_memory_by_path, "find_location_id_by_name": find_location_id_by_name
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
                # 引数に character_name と api_key を注入
                if tool_name in ["diary_search_tool", "conversation_memory_search_tool", "add_to_notepad", "update_notepad", "delete_from_notepad", "read_full_notepad", "edit_memory", "add_secret_diary_entry", "set_current_location", "read_memory_by_path", "find_location_id_by_name"]:
                    tool_args["character_name"] = state.get("character_name")
                if tool_name in ["diary_search_tool", "conversation_memory_search_tool", "summarize_and_save_core_memory"]:
                    tool_args["api_key"] = state.get("api_key")
                output = tool_to_call.invoke(tool_args)
            except Exception as e:
                output = f"[エラー：道具'{tool_name}'の実行に失敗しました。詳細: {e}]"
                traceback.print_exc()
        tool_messages.append(ToolMessage(content=str(output), tool_call_id=tool_call_id, name=tool_name))

    current_count = state.get('tool_call_count', 0)
    return {"messages": tool_messages, "tool_call_count": current_count + 1}

def should_continue(state: AgentState):
    print("--- ルーティング判断 (should_continue) 実行 ---")
    MAX_ITERATIONS = 7 # ループ上限を少し増やす
    tool_call_count = state.get('tool_call_count', 0)
    print(f"  - 現在のツール実行ループ回数: {tool_call_count}")

    if tool_call_count >= MAX_ITERATIONS:
        print(f"  - 警告: ツール実行ループが上限の {MAX_ITERATIONS} 回に達しました。強制的に終了します。")
        return "end"

    last_message = state['messages'][-1] if state['messages'] else None
    if isinstance(last_message, AIMessage) and hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        print("  - 判断: ツール呼び出しあり。call_tool へ。")
        return "continue"
    else:
        print("  - 判断: ツール呼び出しなし。対話終了。")
        return "end"

def after_tool_call_router(state: AgentState):
    print("--- 道具実行後ルーティング (after_tool_call_router) 実行 ---")
    last_message = state['messages'][-1] if state['messages'] else None
    was_location_set = isinstance(last_message, ToolMessage) and last_message.name == "set_current_location"

    if was_location_set:
        print("  - 判断: set_current_locationが実行されたため、情景の再描写 (aether_weaver) へ。")
        return "aether_weaver"
    else:
        print("  - 判断: 通常のツール実行のため、次の判断 (actor) へ。")
        return "actor"

# --- グラフの構築 ---
workflow = StateGraph(AgentState)

workflow.add_node("memory_weaver", memory_weaver_node)
workflow.add_node("aether_weaver", aether_weaver_node)
workflow.add_node("actor", actor_node)
workflow.add_node("call_tool", call_tool_node)

workflow.add_edge(START, "memory_weaver")
workflow.add_edge("memory_weaver", "aether_weaver")
workflow.add_edge("aether_weaver", "actor")

workflow.add_conditional_edges(
    "actor",
    should_continue,
    {
        "continue": "call_tool",
        "end": END
    }
)
workflow.add_conditional_edges(
    "call_tool",
    after_tool_call_router,
    {
        "aether_weaver": "aether_weaver",
        "actor": "actor"
    }
)

app = workflow.compile()
