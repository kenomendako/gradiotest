# agent/graph.py

# 1. ファイルの先頭に必要なモジュールを追加
import os
import re
import traceback
import json
import pytz # ★ 追加
from datetime import datetime # ★ 追加
from typing import TypedDict, Annotated, List, Literal, Optional, Tuple # ★ OptionalとTupleを追加

# 2. 既存のインポートの下に、新しいインポートを追加
from langchain_core.messages import SystemMessage, BaseMessage, ToolMessage, AIMessage
from langchain_google_genai import HarmCategory, HarmBlockThreshold
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END, START, add_messages
from langgraph.prebuilt import ToolNode

# --- 必要なモジュールやツールのインポート ---
from agent.prompts import CORE_PROMPT_TEMPLATE
from tools.space_tools import (
    set_current_location, update_location_content, add_new_location, read_world_settings
)
from tools.memory_tools import read_memory_by_path, edit_memory, add_secret_diary_entry, summarize_and_save_core_memory, read_full_memory
from tools.notepad_tools import add_to_notepad, update_notepad, delete_from_notepad, read_full_notepad
from tools.web_tools import web_search_tool, read_url_tool
from tools.image_tools import generate_image
from tools.alarm_tools import set_personal_alarm
# ▼▼▼ 新しいタイマーツールをインポート ▼▼▼
from tools.timer_tools import set_timer, set_pomodoro_timer
from rag_manager import diary_search_tool, conversation_memory_search_tool
from character_manager import get_world_settings_path
from memory_manager import load_memory_data_safe
import utils # ★ utilsを直接インポート
import config_manager

all_tools = [
    set_current_location, read_memory_by_path, edit_memory,
    add_secret_diary_entry, summarize_and_save_core_memory, add_to_notepad,
    update_notepad, delete_from_notepad, read_full_notepad, web_search_tool,
    read_url_tool, diary_search_tool, conversation_memory_search_tool,
    generate_image, read_full_memory, set_personal_alarm,
    update_location_content, add_new_location,
    set_timer, set_pomodoro_timer,
    read_world_settings
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
    send_notepad: bool
    location_name: str
    scenery_text: str
    debug_mode: bool

def get_configured_llm(
    model_name: str,
    api_key: str,
    generation_config_from_state: dict,
    system_prompt_text: str  # ★★★ システムプロンプトの「テキスト」を直接受け取るように変更 ★★★
):
    """
    キャラクターごとの設定を含む、LangChain用のLLMインスタンスを生成する。
    【v4: 魂の事前注入・最終確定版】
    """
    threshold_map = {
        "BLOCK_NONE": HarmBlockThreshold.BLOCK_NONE,
        "BLOCK_LOW_AND_ABOVE": HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
        "BLOCK_MEDIUM_AND_ABOVE": HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
        "BLOCK_ONLY_HIGH": HarmBlockThreshold.BLOCK_ONLY_HIGH,
    }

    generation_params = {
        "temperature": generation_config_from_state.get("temperature", 0.8),
        "top_p": generation_config_from_state.get("top_p", 0.95),
        "max_output_tokens": generation_config_from_state.get("max_output_tokens", 8192),
    }

    safety_settings = {
        HarmCategory.HARM_CATEGORY_HARASSMENT: threshold_map.get(generation_config_from_state.get("safety_block_threshold_harassment")),
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: threshold_map.get(generation_config_from_state.get("safety_block_threshold_hate_speech")),
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: threshold_map.get(generation_config_from_state.get("safety_block_threshold_sexually_explicit")),
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: threshold_map.get(generation_config_from_state.get("safety_block_threshold_dangerous_content")),
    }

    return ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=api_key,
        # ★★★ ここからが修正の核心 ★★★
        system_instruction=system_prompt_text, # 専用の引数で魂を注入
        convert_system_message_to_human=False, # 不要になった古い設定はFalseに戻す
        # ★★★ 修正ここまで ★★★
        max_retries=6,
        safety_settings=safety_settings,
        **generation_params
    )

# 3. ファイルのクラスや関数定義の前に、新しい「情景生成」関数を追加
def get_location_list(character_name: str) -> List[str]:
    """
    利用可能なすべての場所のリストを「[エリア名] 場所名」の形式で生成する。
    """
    if not character_name: return []
    world_settings_path = get_world_settings_path(character_name)
    if not world_settings_path or not os.path.exists(world_settings_path): return []

    # 新しいパーサーを使用
    world_data = utils.parse_world_file(world_settings_path)
    if not world_data: return []

    locations = []
    for area_name, places in world_data.items():
        for place_name in places.keys():
            # 特殊なキーは除外
            if place_name == "__area_description__": continue
            locations.append(f"[{area_name}] {place_name}")

    return sorted(locations)


def generate_scenery_context(character_name: str, api_key: str, force_regenerate: bool = False) -> Tuple[str, str, str]:
    """
    指定されたキャラクターの現在の場所に基づいて、情景を描写し、
    場所の名前、自由記述テキスト、描写テキストのタプルを返す。
    force_regenerate=True の場合、キャッシュを無視して必ず再生成する。
    """
    scenery_text = "（現在の場所の情景描写は、取得できませんでした）"
    space_def = "（現在の場所の定義・設定は、取得できませんでした）"
    location_display_name = "（不明な場所）"

    try:
        # 1. 現在の場所名を取得
        current_location_name = utils.get_current_location(character_name)
        if not current_location_name:
            current_location_name = "リビング" # デフォルト値
            location_display_name = "リビング"

        # 2. 世界設定をパース
        world_settings_path = get_world_settings_path(character_name)
        world_data = utils.parse_world_file(world_settings_path)

        # 3. 場所名に対応する定義(自由記述テキスト)を探す
        found_location = False
        for area, places in world_data.items():
            if current_location_name in places:
                space_def = places[current_location_name]
                location_display_name = f"[{area}] {current_location_name}"
                found_location = True
                break

        if not found_location:
            space_def = f"（場所「{current_location_name}」の定義が見つかりません）"

        # 4. キャッシュロジック
        from utils import get_season, get_time_of_day, load_scenery_cache, save_scenery_cache
        import hashlib
        # キャッシュキーは場所名と内容のハッシュ、季節、時間帯から生成
        content_hash = hashlib.md5(space_def.encode('utf-8')).hexdigest()[:8]
        now = datetime.now()
        cache_key = f"{current_location_name}_{content_hash}_{get_season(now.month)}_{get_time_of_day(now.hour)}"

        if not force_regenerate:
            scenery_cache = load_scenery_cache(character_name)
            if cache_key in scenery_cache:
                cached_data = scenery_cache[cache_key]
                print(f"--- [有効な情景キャッシュを発見] ({cache_key})。APIコールをスキップします ---")
                # キャッシュから返す場合も、最新の表示名を返す
                return location_display_name, space_def, cached_data["scenery_text"]

        # 5. 情景生成
        if not space_def.startswith("（"):
            log_message = "情景を強制的に再生成します" if force_regenerate else "情景をAPIで生成します"
            print(f"--- {log_message} ({cache_key}) ---")

            effective_settings = config_manager.get_effective_settings(character_name)
            llm_flash = get_configured_llm("gemini-2.5-flash", api_key, effective_settings)
            jst_now = datetime.now(pytz.timezone('Asia/Tokyo'))
            scenery_prompt = (
                f"空間定義（自由記述テキスト）:\n---\n{space_def}\n---\n\n"
                f"時刻:{jst_now.strftime('%H:%M')} / 季節:{jst_now.month}月\n\n"
                "以上の情報から、あなたはこの空間の「今この瞬間」を切り取る情景描写の専門家です。\n"
                "【ルール】\n- 人物やキャラクターの描写は絶対に含めないでください。\n"
                "- 1〜2文の簡潔な文章にまとめてください。\n"
                "- 窓の外の季節感や時間帯、室内の空気感や陰影など、五感に訴えかける精緻で写実的な描写を重視してください。"
            )
            scenery_text = llm_flash.invoke(scenery_prompt).content
            save_scenery_cache(character_name, cache_key, location_display_name, scenery_text)
        else:
            scenery_text = "（場所の定義がないため、情景を描写できません）"

    except Exception as e:
        print(f"--- 警告: 情景描写の生成中にエラーが発生しました ---\n{traceback.format_exc()}")
        location_display_name = "（エラー）"
        scenery_text = "（情景描写の生成中にエラーが発生しました）"
        space_def = "（エラー）"

    return location_display_name, space_def, scenery_text


def context_generator_node(state: AgentState):
    character_name = state['character_name']
    api_key = state['api_key']

    # --- 共通のプロンプト部品を生成 ---
    char_prompt_path = os.path.join("characters", character_name, "SystemPrompt.txt")
    core_memory_path = os.path.join("characters", character_name, "core_memory.txt")
    character_prompt = ""
    if os.path.exists(char_prompt_path):
        with open(char_prompt_path, 'r', encoding='utf-8') as f: character_prompt = f.read().strip()

    core_memory = ""
    if state.get("send_core_memory", True):
        if os.path.exists(core_memory_path):
            with open(core_memory_path, 'r', encoding='utf-8') as f: core_memory = f.read().strip()

    notepad_section = ""
    if state.get("send_notepad", True):
        # ... (メモ帳の読み込み部分は変更なし) ...
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

    # --- 空間描写がOFFの場合 ---
    if not state.get("send_scenery", True):
        final_system_prompt_text = (
            f"{formatted_core_prompt}\n\n---\n"
            f"【現在の場所と情景】\n"
            f"（空間描写は設定により無効化されています）\n"
            "---"
        )
        return {"system_prompt": SystemMessage(content=final_system_prompt_text), "location_name": "（空間描写OFF）", "scenery_text": "（空間描写は設定により無効化されています）"}

    # --- 空間描写がONの場合 ---
    location_display_name, space_def, scenery_text = generate_scenery_context(character_name, api_key)

    available_locations = get_location_list(character_name)
    if available_locations:
        # get_location_listは "[エリア名] 場所名" のリストを返す
        location_list_str = "\n".join([f"- {loc}" for loc in available_locations])
        locations_section = f"【移動可能な場所】\n{location_list_str}\n"
    else:
        locations_section = "【移動可能な場所】\n（現在、定義されている移動先はありません）\n"

    final_system_prompt_text = (
        f"{formatted_core_prompt}\n\n---\n"
        f"【現在の場所と情景】\n"
        f"- 場所: {location_display_name}\n"
        f"- 場所の設定（自由記述）: \n{space_def}\n"
        f"- 今の情景: {scenery_text}\n"
        f"{locations_section}"
        "---"
    )

    return {"system_prompt": SystemMessage(content=final_system_prompt_text), "location_name": location_display_name, "scenery_text": scenery_text}

def agent_node(state: AgentState):
    print("--- エージェントノード (agent_node) 実行 ---")
    print(f"  - 使用モデル: {state['model_name']}")
    print(f"  - システムプロンプト長: {len(state['system_prompt'].content)} 文字")

    if state.get("debug_mode", False):
        print("--- [DEBUG MODE] システムプロンプトの内容 ---")
        print(state['system_prompt'].content)
        print("-----------------------------------------")

    effective_settings = config_manager.get_effective_settings(state['character_name'])

    # ★★★ ここからが修正の核心 ★★★
    # 1. LLMを初期化する際に、システムプロンプトの「テキスト」を直接渡す
    llm = get_configured_llm(
        state['model_name'],
        state['api_key'],
        effective_settings,
        state['system_prompt'].content # SystemMessageオブジェクトから内容(str)を抽出
    )

    llm_with_tools = llm.bind_tools(all_tools)

    # 2. AIに渡すメッセージリストには、もはやシステムプロンプトを含めない
    messages_for_agent = []
    for msg in state['messages']:
        if isinstance(msg.content, str):
            cleaned_content = re.sub(r"\[ファイル添付:.*?\]", "", msg.content, flags=re.DOTALL).strip()
            if cleaned_content:
                msg.content = cleaned_content
                messages_for_agent.append(msg)
        else:
            messages_for_agent.append(msg)
    # ★★★ 修正ここまで ★★★

    response = llm_with_tools.invoke(messages_for_agent)
    return {"messages": [response]}

def safe_tool_executor(state: AgentState):
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

        if tool_name == 'generate_image' or tool_name == 'summarize_and_save_core_memory':
            tool_call['args']['api_key'] = api_key
            print(f"    - 'api_key' を引数に追加しました。")
        elif tool_name == 'web_search_tool':
            tool_call['args']['api_key'] = tavily_api_key
            print(f"    - 'tavily_api_key' を引数に追加しました。")

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

workflow = StateGraph(AgentState)
workflow.add_node("context_generator", context_generator_node)
workflow.add_node("agent", agent_node)
workflow.add_node("safe_tool_node", safe_tool_executor)

workflow.add_edge(START, "context_generator")
workflow.add_edge("context_generator", "agent")

workflow.add_conditional_edges(
    "agent",
    route_after_agent,
    {
        "safe_tool_node": "safe_tool_node",
        "__end__": END,
    },
)
workflow.add_conditional_edges(
    "safe_tool_node",
    route_after_tools,
    {"context_generator": "context_generator", "agent": "agent"},
)

app = workflow.compile()
print("--- 統合グラフ(v5)がコンパイルされました ---")
