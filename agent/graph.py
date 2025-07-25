# agent/graph.py を、このコードで完全に置き換えてください

import os
import re
import traceback
from typing import TypedDict, Annotated, List, Literal
from langchain_core.messages import SystemMessage, BaseMessage, ToolMessage, AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END, START, add_messages
from datetime import datetime
from langgraph.prebuilt import ToolNode

# --- 1. 正しいツールとプロンプトのインポート ---
from agent.prompts import CORE_PROMPT_TEMPLATE # agent/prompts.py を参照
from tools.space_tools import set_current_location, find_location_id_by_name
from tools.memory_tools import read_memory_by_path, edit_memory, add_secret_diary_entry, summarize_and_save_core_memory, read_full_memory
from tools.notepad_tools import add_to_notepad, update_notepad, delete_from_notepad, read_full_notepad
from tools.web_tools import web_search_tool, read_url_tool
from tools.image_tools import generate_image
from tools.alarm_tools import set_personal_alarm
from rag_manager import diary_search_tool, conversation_memory_search_tool

# --- 2. 正しいツールリストの定義 ---
all_tools = [
    set_current_location, find_location_id_by_name, read_memory_by_path, edit_memory,
    add_secret_diary_entry, summarize_and_save_core_memory, add_to_notepad,
    update_notepad, delete_from_notepad, read_full_notepad, web_search_tool,
    read_url_tool, diary_search_tool, conversation_memory_search_tool,
    generate_image, read_full_memory, set_personal_alarm
]

# --- 3. 正しい状態(State)の定義 ---
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    character_name: str
    api_key: str
    tavily_api_key: str
    model_name: str
    system_prompt: SystemMessage
    send_core_memory: bool
    send_scenery: bool

# --- 4. 正しいモデル初期化関数の定義 ---
def get_configured_llm(model_name: str, api_key: str):
    return ChatGoogleGenerativeAI(model=model_name, google_api_key=api_key, convert_system_message_to_human=False)

# --- 5. ★★★ あなたの修正と新機能を統合した、最終版ノード ★★★ ---
def context_generator_node(state: AgentState):
    if not state.get("send_scenery", True):
        char_prompt_path = os.path.join("characters", state['character_name'], "SystemPrompt.txt")
        core_memory_path = os.path.join("characters", state['character_name'], "core_memory.txt")
        character_prompt = ""
        if os.path.exists(char_prompt_path):
            with open(char_prompt_path, 'r', encoding='utf-8') as f: character_prompt = f.read().strip()
        core_memory = ""
        if state.get("send_core_memory", True):
            if os.path.exists(core_memory_path):
                with open(core_memory_path, 'r', encoding='utf-8') as f:
                    core_memory = f.read().strip()
        tools_list_str = "\n".join([f"- `{tool.name}({', '.join(tool.args.keys())})`: {tool.description}" for tool in all_tools])
        class SafeDict(dict):
            def __missing__(self, key): return f'{{{key}}}'
        prompt_vars = {
            'character_name': state['character_name'], 'character_prompt': character_prompt,
            'core_memory': core_memory, 'space_definition': "（空間描写OFF）", 'tools_list': tools_list_str
        }
        formatted_core_prompt = CORE_PROMPT_TEMPLATE.format_map(SafeDict(prompt_vars))
        final_system_prompt_text = (f"{formatted_core_prompt}\n---\n【現在の情景】\n（空間描写OFF）\n---")
        return {"system_prompt": SystemMessage(content=final_system_prompt_text)}

    print("--- コンテキスト生成ノード (context_generator_node) 実行 ---")
    character_name = state['character_name']
    api_key = state['api_key']
    scenery_text = "（現在の場所の情景描写は、取得できませんでした）"
    space_def = "（現在の場所の定義・設定は、取得できませんでした）"

    try:
        location_to_describe = None
        last_tool_message = next((msg for msg in reversed(state['messages']) if isinstance(msg, ToolMessage)), None)
        if last_tool_message and "Success: Location set to" in last_tool_message.content:
            match = re.search(r"'(.*?)'", last_tool_message.content)
            if match:
                location_to_describe = match.group(1)
                print(f"  - ツール実行結果から最新の場所 '{location_to_describe}' を特定しました。")

        if not location_to_describe:
            try:
                location_file_path = os.path.join("characters", character_name, "current_location.txt")
                if os.path.exists(location_file_path):
                    with open(location_file_path, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                        if content:
                            location_to_describe = content
                            print(f"  - ファイルから現在の場所 '{location_to_describe}' を読み込みました。")
            except Exception as e:
                print(f"  - 警告: 現在地ファイル読込エラー: {e}")

        if not location_to_describe:
            location_to_describe = "living_space"
            print(f"  - 場所が特定できなかったため、デフォルトの '{location_to_describe}' を使用します。")

        llm_flash = get_configured_llm("gemini-2.5-flash", api_key)

        found_id_result = find_location_id_by_name.invoke({"location_name": location_to_describe, "character_name": character_name})
        id_to_use = location_to_describe
        if not found_id_result.startswith("Error:"):
            id_to_use = found_id_result

        space_def = read_memory_by_path.invoke({"path": f"living_space.{id_to_use}", "character_name": character_name})

        # ★★★ ここからが修正点 ★★★
        # 読み込んだ場所の定義を、ここで明確にログ出力する
        if not space_def.startswith("【Error】"):
            print(f"  - 読み込まれた場所の定義:\n```\n{space_def}\n```")
        # ★★★ 修正ここまで ★★★

        if not space_def.startswith("【Error】") and not space_def.startswith("Error:"):
            now = datetime.now()
            scenery_prompt = (
                f"空間定義:{space_def}\n"
                f"時刻:{now.strftime('%H:%M')} / 季節:{now.month}月\n\n"
                "以上の情報から、あなたは情景描写の専門家として、この空間の「今この瞬間」を精緻かつ写実的に切り取ってください。\n"
                "【ルール】\n"
                "- 人物やキャラクターの描写は絶対に含めないでください。\n"
                "- 1〜2文の簡潔な文章にまとめてください。\n"
                "- 気温、湿度、光と影、音、香り、空気の質感など、五感に訴えかける具体的な描写を重視してください。"
            )
            scenery_text = llm_flash.invoke(scenery_prompt).content
            print(f"  - 生成された情景描写: {scenery_text}")
        else:
            print(f"  - 警告: 場所「{location_to_describe}」(ID: {id_to_use}) の定義が見つかりません。")
            space_def = "（現在の場所の定義・設定は、取得できませんでした）"

    except Exception as e:
        print(f"--- 警告: 情景描写の生成中にエラーが発生しました ---\n{traceback.format_exc()}")

    char_prompt_path = os.path.join("characters", character_name, "SystemPrompt.txt")
    core_memory_path = os.path.join("characters", character_name, "core_memory.txt")
    character_prompt = ""
    if os.path.exists(char_prompt_path):
        with open(char_prompt_path, 'r', encoding='utf-8') as f: character_prompt = f.read().strip()
    core_memory = ""
    if state.get("send_core_memory", True):
        if os.path.exists(core_memory_path):
            with open(core_memory_path, 'r', encoding='utf-8') as f:
                core_memory = f.read().strip()

    tools_list_str = "\n".join([f"- `{tool.name}({', '.join(tool.args.keys())})`: {tool.description}" for tool in all_tools])

    class SafeDict(dict):
        def __missing__(self, key):
            return f'{{{key}}}'

    prompt_vars = {
        'character_name': character_name,
        'character_prompt': character_prompt,
        'core_memory': core_memory,
        'space_definition': space_def,
        'tools_list': tools_list_str
    }

    formatted_core_prompt = CORE_PROMPT_TEMPLATE.format_map(SafeDict(prompt_vars))

    final_system_prompt_text = (
        f"{formatted_core_prompt}\n"
        "---\n"
        f"【現在の情景】\n{scenery_text}\n"
        "---"
    )

    # ★★★ 誤解を招く不完全なログ出力を削除 ★★★
    # print(f"  - 生成された最終システムプロンプト (一部): ...") の行を削除

    return {"system_prompt": SystemMessage(content=final_system_prompt_text)}


# --- 6. 残りのノードとグラフ構築（ここはプロジェクトの安定版をそのまま使用） ---
def agent_node(state: AgentState):
    print("--- エージェントノード (agent_node) 実行 ---")
    llm = get_configured_llm(state['model_name'], state['api_key'])
    llm_with_tools = llm.bind_tools(all_tools)
    messages_for_agent = [state['system_prompt']] + state['messages']
    response = llm_with_tools.invoke(messages_for_agent)
    return {"messages": [response]}

def route_after_agent(state: AgentState) -> Literal["__end__", "tool_node"]:
    print("--- エージェント後ルーター (route_after_agent) 実行 ---")
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        print("  - ツール呼び出しあり。ツール実行ノードへ。")
        for tool_call in last_message.tool_calls:
            print(f"    🛠️ ツール呼び出し: {tool_call['name']} | 引数: {tool_call['args']}")
        return "tool_node"
    print("  - ツール呼び出しなし。思考完了と判断し、グラフを終了します。")
    return "__end__"

def route_after_tools(state: AgentState) -> Literal["context_generator", "agent"]:
    print("--- ツール後ルーター (route_after_tools) 実行 ---")
    last_ai_message_index = -1
    for i in range(len(state["messages"]) - 1, -1, -1):
        if isinstance(state["messages"][i], AIMessage):
            last_ai_message_index = i
            break
    if last_ai_message_index != -1:
        new_tool_messages = state["messages"][last_ai_message_index + 1:]
        for msg in new_tool_messages:
            if isinstance(msg, ToolMessage):
                content_to_log = (str(msg.content)[:200] + '...') if len(str(msg.content)) > 200 else str(msg.content)
                print(f"    ✅ ツール実行結果: {msg.name} | 結果: {content_to_log}")

    last_ai_message_with_tool_call = next((msg for msg in reversed(state['messages']) if isinstance(msg, AIMessage) and msg.tool_calls), None)
    if last_ai_message_with_tool_call:
        if any(call['name'] == 'set_current_location' for call in last_ai_message_with_tool_call.tool_calls):
            print("  - `set_current_location` が実行されたため、コンテキスト再生成へ。")
            return "context_generator"
    print("  - 通常のツール実行完了。エージェントの思考へ。")
    return "agent"

workflow = StateGraph(AgentState)
workflow.add_node("context_generator", context_generator_node)
workflow.add_node("agent", agent_node)
tool_node = ToolNode(all_tools)
workflow.add_node("tool_node", tool_node)
workflow.add_edge(START, "context_generator")
workflow.add_edge("context_generator", "agent")
workflow.add_conditional_edges(
    "agent",
    route_after_agent,
    {"tool_node": "tool_node", "__end__": END}
)
workflow.add_conditional_edges(
    "tool_node",
    route_after_tools,
    {"context_generator": "context_generator", "agent": "agent"}
)
app = workflow.compile()
print("--- 最終完成版v37：情景描写機能が強化されたグラフがコンパイルされました ---")
