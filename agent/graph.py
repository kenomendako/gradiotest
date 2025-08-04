# agent/graph.py を、このコードで完全に置き換えてください

import os
import re
import traceback
import json
import pytz
from typing import TypedDict, Annotated, List, Literal
from langchain_core.messages import SystemMessage, BaseMessage, ToolMessage, AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END, START, add_messages
from datetime import datetime
from langgraph.prebuilt import ToolNode

# --- 1. 正しいツールとプロンプトのインポート ---
from agent.prompts import CORE_PROMPT_TEMPLATE
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

# --- 3. 状態(State)の定義 ---
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    character_name: str
    api_key: str
    tavily_api_key: str
    model_name: str
    system_prompt: SystemMessage
    send_core_memory: bool
    send_scenery: bool
    send_notepad: bool # ★★★ この行を追加 ★★★
    location_name: str
    scenery_text: str

# --- 4. モデル初期化関数の修正 ---
def get_configured_llm(model_name: str, api_key: str):
    # ★★★ ここが修正点です ★★★
    # レート制限エラーに対応するため、リトライ回数を増やす
    return ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=api_key,
        convert_system_message_to_human=False,
        max_retries=6 # デフォルト(2)から増やすことで、待機時間が長くなりエラーを回避しやすくなる
    )

def context_generator_node(state: AgentState):
    # --- パス1: 空間描写がOFFの場合 ---
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

        notepad_section = ""
        if state.get("send_notepad", True):
            try:
                from character_manager import get_character_files_paths
                _, _, _, _, notepad_path = get_character_files_paths(state['character_name'])
                if notepad_path and os.path.exists(notepad_path):
                    with open(notepad_path, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                        notepad_content = content if content else "（メモ帳は空です）"
                else:
                    notepad_content = "（メモ帳ファイルが見つかりません）"
                notepad_section = f"\n### 短期記憶（メモ帳）\n{notepad_content}\n"
            except Exception as e:
                print(f"--- 警告: メモ帳の読み込み中にエラー: {e}")
                notepad_section = "\n### 短期記憶（メモ帳）\n（メモ帳の読み込み中にエラーが発生しました）\n"

        tools_list_str = "\n".join([f"- `{tool.name}({', '.join(tool.args.keys())})`: {tool.description}" for tool in all_tools])
        class SafeDict(dict):
            def __missing__(self, key): return f'{{{key}}}'
        prompt_vars = {
            'character_name': state['character_name'], 'character_prompt': character_prompt,
            'core_memory': core_memory, 'notepad_section': notepad_section, 'tools_list': tools_list_str
        }
        formatted_core_prompt = CORE_PROMPT_TEMPLATE.format_map(SafeDict(prompt_vars))
        final_system_prompt_text = (f"{formatted_core_prompt}\n\n---\n" f"【現在の場所と情景】\n" f"- 場所の名前: （空間描写OFF）\n" f"- 場所の定義: （空間描写OFF）\n" f"- 今の情景: （空間描写OFF）\n" "---")
        return {"system_prompt": SystemMessage(content=final_system_prompt_text), "location_name": "（空間描写OFF）", "scenery_text": "（空間描写は設定により無効化されています）"}

    # --- パス2: 空間描写がONの場合 ---
    character_name = state['character_name']; api_key = state['api_key']
    scenery_text = "（現在の場所の情景描写は、取得できませんでした）"
    space_def = "（現在の場所の定義・設定は、取得できませんでした）"
    location_display_name = "（不明な場所）"

    try:
        location_id_to_process = None
        last_tool_message = next((msg for msg in reversed(state['messages']) if isinstance(msg, ToolMessage)), None)
        if last_tool_message and "Success: Current location has been set to" in last_tool_message.content:
            match = re.search(r"'(.*?)'", last_tool_message.content)
            if match:
                location_id_to_process = match.group(1)

        if not location_id_to_process:
            location_file_path = os.path.join("characters", character_name, "current_location.txt")
            if os.path.exists(location_file_path):
                with open(location_file_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content: location_id_to_process = content

        if not location_id: location_id = "living_space"

        world_settings_path = get_world_settings_path(character_name)
        space_data = {}
        if world_settings_path and os.path.exists(world_settings_path):
            world_settings = load_memory_data_safe(world_settings_path)
            if "error" not in world_settings:
                from character_manager import find_space_data_by_id_recursive
                space_data = find_space_data_by_id_recursive(world_settings, location_id)

        if space_data and isinstance(space_data, dict):
            location_display_name = space_data.get("name", location_id)
            space_def = json.dumps(space_data, ensure_ascii=False, indent=2)

        if not space_def.startswith("（"):
            llm_flash = get_configured_llm("gemini-2.5-flash", api_key)

            # ★★★ UTCで現在時刻を取得し、日本時間に変換 ★★★
            utc_now = datetime.now(pytz.utc)
            jst_now = utc_now.astimezone(pytz.timezone('Asia/Tokyo'))

            scenery_prompt = (f"空間定義:{space_def}\n時刻:{jst_now.strftime('%H:%M')} / 季節:{jst_now.month}月\n\n以上の情報から、あなたはこの空間の「今この瞬間」を切り取る情景描写の専門家です。\n【ルール】\n- 人物やキャラクターの描写は絶対に含めないでください。\n- 1〜2文の簡潔な文章にまとめてください。\n- 窓の外の季節感や時間帯、室内の空気感や陰影など、五感に訴えかける精緻で写実的な描写を重視してください。")
            scenery_text = llm_flash.invoke(scenery_prompt).content
        else:
            scenery_text = "（場所の定義がないため、情景を描写できません）"

    except Exception as e:
        print(f"--- 警告: 情景描写の生成中にエラーが発生しました ---\n{traceback.format_exc()}"); location_display_name = "（エラー）"; scenery_text = "（情景描写の生成中にエラーが発生しました）"

    char_prompt_path = os.path.join("characters", character_name, "SystemPrompt.txt")
    core_memory_path = os.path.join("characters", character_name, "core_memory.txt")
    character_prompt = "";
    if os.path.exists(char_prompt_path):
        with open(char_prompt_path, 'r', encoding='utf-8') as f: character_prompt = f.read().strip()
    core_memory = ""
    if state.get("send_core_memory", True):
        if os.path.exists(core_memory_path):
            with open(core_memory_path, 'r', encoding='utf-8') as f: core_memory = f.read().strip()

    notepad_section = ""
    if state.get("send_notepad", True):
        try:
            from character_manager import get_character_files_paths
            _, _, _, _, notepad_path = get_character_files_paths(character_name)
            if notepad_path and os.path.exists(notepad_path):
                with open(notepad_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    notepad_content = content if content else "（メモ帳は空です）"
            else:
                notepad_content = "（メモ帳ファイルが見つかりません）"
            notepad_section = f"\n### 短期記憶（メモ帳）\n{notepad_content}\n"
        except Exception as e:
            print(f"--- 警告: メモ帳の読み込み中にエラー: {e}")
            notepad_section = "\n### 短期記憶（メモ帳）\n（メモ帳の読み込み中にエラーが発生しました）\n"

    tools_list_str = "\n".join([f"- `{tool.name}({', '.join(tool.args.keys())})`: {tool.description}" for tool in all_tools])
    class SafeDict(dict):
        def __missing__(self, key): return f'{{{key}}}'
    prompt_vars = {'character_name': character_name, 'character_prompt': character_prompt, 'core_memory': core_memory, 'notepad_section': notepad_section, 'tools_list': tools_list_str}
    formatted_core_prompt = CORE_PROMPT_TEMPLATE.format_map(SafeDict(prompt_vars))
    final_system_prompt_text = (
        f"{formatted_core_prompt}\n\n---\n"
        f"【現在の場所と情景】\n"
        f"- 場所の名前: {location_display_name}\n"
        f"- 場所の定義: {space_def}\n"
        f"- 今の情景: {scenery_text}\n"
        "---"
    )

    return {"system_prompt": SystemMessage(content=final_system_prompt_text), "location_name": location_display_name, "scenery_text": scenery_text}

# --- 6. ノードの定義 ---
def agent_node(state: AgentState):
    print("--- エージェントノード (agent_node) 実行 ---")
    # ★★★ ここから2行追加 ★★★
    print(f"  - 使用モデル: {state['model_name']}")
    print(f"  - システムプロンプト長: {len(state['system_prompt'].content)} 文字")
    # ★★★ ここまで ★★★
    llm = get_configured_llm(state['model_name'], state['api_key'])
    llm_with_tools = llm.bind_tools(all_tools)
    messages_for_agent = [state['system_prompt']] + state['messages']
    response = llm_with_tools.invoke(messages_for_agent)
    return {"messages": [response]}

def safe_tool_executor(state: AgentState):
    """stateからAPIキーを取得し、安全にツールを実行するカスタムノード"""
    print("--- カスタムツール実行ノード (safe_tool_executor) 実行 ---")
    messages = state['messages']
    last_message = messages[-1]
    tool_invocations = last_message.tool_calls

    api_key = state.get('api_key')
    tavily_api_key = state.get('tavily_api_key')

    tool_outputs = []
    for tool_call in tool_invocations:
        tool_name = tool_call["name"]
        print(f"  - 準備中のツール: {tool_name} | 引数: {tool_call['args']}")

        # APIキーを必要とするツールに自動でキーを渡す
        if tool_name == 'generate_image' or tool_name == 'summarize_and_save_core_memory':
            tool_call['args']['api_key'] = api_key
            print(f"    - 'api_key' を引数に追加しました。")
        elif tool_name == 'web_search_tool':
            tool_call['args']['api_key'] = tavily_api_key
            print(f"    - 'tavily_api_key' を引数に追加しました。")

        # all_toolsリストからツールを名前で検索
        selected_tool = next((t for t in all_tools if t.name == tool_name), None)
        if not selected_tool:
            output = f"Error: Tool '{tool_name}' not found."
        else:
            try:
                output = selected_tool.invoke(tool_call['args'])
            except Exception as e:
                output = f"Error executing tool '{tool_name}': {e}"
                traceback.print_exc()

        tool_outputs.append(
            ToolMessage(content=str(output), tool_call_id=tool_call["id"])
        )

    return {"messages": tool_outputs}

# --- 7. ルーターの定義 ---
def route_after_agent(state: AgentState) -> Literal["__end__", "safe_tool_node"]:
    print("--- エージェント後ルーター (route_after_agent) 実行 ---")
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        print("  - ツール呼び出しあり。ツール実行ノードへ。")
        for tool_call in last_message.tool_calls: print(f"    🛠️ ツール呼び出し: {tool_call['name']} | 引数: {tool_call['args']}")
        return "safe_tool_node"
    print("  - ツール呼び出しなし。思考完了と判断し、グラフを終了します。")
    return "__end__"

def route_after_tools(state: AgentState) -> Literal["context_generator", "agent"]:
    print("--- ツール後ルーター (route_after_tools) 実行 ---")
    last_ai_message_index = -1
    for i in range(len(state["messages"]) - 1, -1, -1):
        if isinstance(state["messages"][i], AIMessage): last_ai_message_index = i; break
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

# --- 8. グラフの構築 ---
workflow = StateGraph(AgentState)
workflow.add_node("context_generator", context_generator_node)
workflow.add_node("agent", agent_node)
workflow.add_node("safe_tool_node", safe_tool_executor) # 変更点：ToolNodeの代わりにカスタム関数を使用

workflow.add_edge(START, "context_generator")
workflow.add_edge("context_generator", "agent")

workflow.add_conditional_edges(
    "agent",
    route_after_agent,
    {
        "safe_tool_node": "safe_tool_node", # 変更点：参照先を新しいノード名に
        "__end__": END,
    },
)
workflow.add_conditional_edges(
    "safe_tool_node", # 変更点：参照元を新しいノード名に
    route_after_tools,
    {"context_generator": "context_generator", "agent": "agent"},
)

app = workflow.compile()
print("--- 統合グラフ(v5)がコンパイルされました ---")
