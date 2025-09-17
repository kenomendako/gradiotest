# agent/graph.py

import os
import re
import traceback
import json
import pytz
from datetime import datetime
from typing import TypedDict, Annotated, List, Literal, Optional, Tuple

from langchain_core.messages import SystemMessage, BaseMessage, ToolMessage, AIMessage, HumanMessage
from langchain_google_genai import HarmCategory, HarmBlockThreshold
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END, START, add_messages
from langgraph.prebuilt import ToolNode

from agent.prompts import CORE_PROMPT_TEMPLATE
from tools.space_tools import (
    set_current_location, update_location_content, add_new_location, read_world_settings
)
from tools.knowledge_tools import search_knowledge_graph
from tools.memory_tools import read_memory_by_path, edit_memory, add_secret_diary_entry, summarize_and_save_core_memory, read_full_memory
from tools.notepad_tools import add_to_notepad, update_notepad, delete_from_notepad, read_full_notepad
from tools.web_tools import web_search_tool, read_url_tool
from tools.image_tools import generate_image
from tools.alarm_tools import set_personal_alarm
from tools.timer_tools import set_timer, set_pomodoro_timer
from room_manager import get_world_settings_path
from memory_manager import load_memory_data_safe
import utils
import config_manager
import constants

all_tools = [
    set_current_location, update_location_content, add_new_location, read_world_settings,
    read_memory_by_path, edit_memory, add_secret_diary_entry, summarize_and_save_core_memory, read_full_memory,
    add_to_notepad, update_notepad, delete_from_notepad, read_full_notepad,
    web_search_tool, read_url_tool,
    generate_image,
    set_personal_alarm,
    set_timer, set_pomodoro_timer,
    search_knowledge_graph
]

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    room_name: str
    api_key: str
    model_name: str
    system_prompt: SystemMessage
    generation_config: dict
    send_core_memory: bool
    send_scenery: bool
    send_notepad: bool
    location_name: str
    scenery_text: str
    debug_mode: bool
    all_participants: List[str]

def get_configured_llm(model_name: str, api_key: str, generation_config: dict):
    threshold_map = {
        "BLOCK_NONE": HarmBlockThreshold.BLOCK_NONE,
        "BLOCK_LOW_AND_ABOVE": HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
        "BLOCK_MEDIUM_AND_ABOVE": HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
        "BLOCK_ONLY_HIGH": HarmBlockThreshold.BLOCK_ONLY_HIGH,
    }
    safety_settings = {
        HarmCategory.HARM_CATEGORY_HARASSMENT: threshold_map.get(generation_config.get("safety_block_threshold_harassment")),
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: threshold_map.get(generation_config.get("safety_block_threshold_hate_speech")),
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: threshold_map.get(generation_config.get("safety_block_threshold_sexually_explicit")),
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: threshold_map.get(generation_config.get("safety_block_threshold_dangerous_content")),
    }
    return ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=api_key,
        convert_system_message_to_human=False,
        max_retries=6,
        temperature=generation_config.get("temperature", 0.8),
        top_p=generation_config.get("top_p", 0.95),
        safety_settings=safety_settings
    )

def get_location_list(room_name: str) -> List[str]:
    if not room_name: return []
    world_settings_path = get_world_settings_path(room_name)
    if not world_settings_path or not os.path.exists(world_settings_path): return []
    world_data = utils.parse_world_file(world_settings_path)
    if not world_data: return []
    locations = []
    for area_name, places in world_data.items():
        for place_name in places.keys():
            if place_name == "__area_description__": continue
            locations.append(f"[{area_name}] {place_name}")
    return sorted(locations)

def generate_scenery_context(room_name: str, api_key: str, force_regenerate: bool = False) -> Tuple[str, str, str]:
    scenery_text = "（現在の場所の情景描写は、取得できませんでした）"
    space_def = "（現在の場所の定義・設定は、取得できませんでした）"
    location_display_name = "（不明な場所）"
    try:
        current_location_name = utils.get_current_location(room_name)
        if not current_location_name:
            current_location_name = "リビング"
            location_display_name = "リビング"
        world_settings_path = get_world_settings_path(room_name)
        world_data = utils.parse_world_file(world_settings_path)
        found_location = False
        for area, places in world_data.items():
            if current_location_name in places:
                space_def = places[current_location_name]
                location_display_name = f"[{area}] {current_location_name}"
                found_location = True
                break
        if not found_location:
            space_def = f"（場所「{current_location_name}」の定義が見つかりません）"
        from utils import get_season, get_time_of_day, load_scenery_cache, save_scenery_cache
        import hashlib
        content_hash = hashlib.md5(space_def.encode('utf-8')).hexdigest()[:8]
        now = datetime.now()
        cache_key = f"{current_location_name}_{content_hash}_{get_season(now.month)}_{get_time_of_day(now.hour)}"
        if not force_regenerate:
            scenery_cache = load_scenery_cache(room_name)
            if cache_key in scenery_cache:
                cached_data = scenery_cache[cache_key]
                print(f"--- [有効な情景キャッシュを発見] ({cache_key})。APIコールをスキップします ---")
                return location_display_name, space_def, cached_data["scenery_text"]
        if not space_def.startswith("（"):
            log_message = "情景を強制的に再生成します" if force_regenerate else "情景をAPIで生成します"
            print(f"--- {log_message} ({cache_key}) ---")
            effective_settings = config_manager.get_effective_settings(room_name)
            llm_flash = get_configured_llm(constants.INTERNAL_PROCESSING_MODEL, api_key, effective_settings)
            jst_now = datetime.now(pytz.timezone('Asia/Tokyo'))
            from utils import get_time_of_day
            time_str = jst_now.strftime('%H:%M')
            time_of_day_ja = {"morning": "朝", "daytime": "昼", "evening": "夕方", "night": "夜"}.get(get_time_of_day(jst_now.hour), "不明な時間帯")
            scenery_prompt = (
                "あなたは、二つの異なる情報源を比較し、その間にある不思議さや特異性を描き出す、情景描写の専門家です。\n\n"
                f"【情報源1：現実世界の状況】\n- 現在の時刻: {time_str}\n- 現在の時間帯: {time_of_day_ja}\n- 現在の季節: {jst_now.month}月\n\n"
                f"【情報源2：この空間が持つ固有の設定（自由記述テキスト）】\n---\n{space_def}\n---\n\n"
                "【あなたのタスク】\n以上の二つの情報を比較し、「今、この瞬間」の情景を1〜2文の簡潔な文章で描写してください。\n\n"
                "【最重要ルール】\n- もし【情報源1】と【情報源2】の間に矛盾（例：現実は昼なのに、空間は常に夜の設定など）がある場合は、その**『にも関わらず』**という感覚や、その空間の**不思議な空気感**に焦点を当てて描写してください。\n"
                "- 人物やキャラクターの描写は絶対に含めないでください。\n"
                "- 五感に訴えかける、精緻で写実的な描写を重視してください。"
            )
            scenery_text = llm_flash.invoke(scenery_prompt).content
            save_scenery_cache(room_name, cache_key, location_display_name, scenery_text)
        else:
            scenery_text = "（場所の定義がないため、情景を描写できません）"
    except Exception as e:
        print(f"--- 警告: 情景描写の生成中にエラーが発生しました ---\n{traceback.format_exc()}")
        location_display_name = "（エラー）"
        scenery_text = "（情景描写の生成中にエラーが発生しました）"
        space_def = "（エラー）"
    return location_display_name, space_def, scenery_text

def context_generator_node(state: AgentState):
    room_name = state['room_name']
    all_participants = state.get('all_participants', [])
    char_prompt_path = os.path.join(constants.ROOMS_DIR, room_name, "SystemPrompt.txt")
    core_memory_path = os.path.join(constants.ROOMS_DIR, room_name, "core_memory.txt")
    character_prompt = ""
    if os.path.exists(char_prompt_path):
        with open(char_prompt_path, 'r', encoding='utf-8') as f: character_prompt = f.read().strip()
    core_memory = ""
    if state.get("send_core_memory", True):
        if os.path.exists(core_memory_path):
            with open(core_memory_path, 'r', encoding='utf-8') as f: core_memory = f.read().strip()
    notepad_section = ""
    if state.get("send_notepad", True):
        try:
            from room_manager import get_room_files_paths
            _, _, _, _, notepad_path = get_room_files_paths(room_name)
            if notepad_path and os.path.exists(notepad_path):
                with open(notepad_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    notepad_content = content if content else "（メモ帳は空です）"
            else: notepad_content = "（メモ帳ファイルが見つかりません）"
            notepad_section = f"\n### 短期記憶（メモ帳）\n{notepad_content}\n"
        except Exception as e:
            print(f"--- 警告: メモ帳の読み込み中にエラー: {e}")
            notepad_section = "\n### 短期記憶（メモ帳）\n（メモ帳の読み込み中にエラーが発生しました）\n"
    # ▼▼▼【ここからが修正ブロック】▼▼▼
    tools_list_str = ""
    # effective_settings は config_manager から取得する
    effective_settings = config_manager.get_effective_settings(room_name)

    if not effective_settings.get("use_common_prompt", True):
        tools_list_str = "（ツールは設定により無効化されています）"
    elif len(all_participants) > 1:
        tools_list_str = "（グループ会話中はツールを使用できません）"
    else:
        tool_descriptions = "\n".join([f"- `{tool.name}({', '.join(tool.args.keys())})`: {tool.description}" for tool in all_tools])
        tools_list_str = f"""
### 長期記憶（知識グラフ）の活用ルール
- 過去の会話から抽出・構築された、客観的な事実や、登場人物・場所・物事の関係性について知りたい場合は、`search_knowledge_graph`ツールを使用すること。
- これは、あなたの主観的な「日記」とは異なる、客観的なデータベースである。
---
### ツール一覧
- **画像生成の厳格な手順:**
  1. ユーザーからイラストや画像の生成を依頼された場合、あなたは `generate_image` ツールを呼び出す。
  2. ツールが成功すると、あなたは `[Generated Image: path/to/image.png]` という形式の特別なテキストを受け取る。
  3. あなたの最終的な応答には、**必ず、この受け取った画像タグを、そのままの形で含めなければならない。** これを怠ることは許されない。

{tool_descriptions}
"""
    # ▲▲▲【修正はここまで】▲▲▲
    class SafeDict(dict):
        def __missing__(self, key): return f'{{{key}}}'
    prompt_vars = {'character_name': room_name, 'character_prompt': character_prompt, 'core_memory': core_memory, 'notepad_section': notepad_section, 'tools_list': tools_list_str}
    formatted_core_prompt = CORE_PROMPT_TEMPLATE.format_map(SafeDict(prompt_vars))
    if not state.get("send_scenery", True):
        final_system_prompt_text = (f"{formatted_core_prompt}\n\n---\n【現在の場所と情景】\n（空間描写は設定により無効化されています）\n---")
    else:
        location_display_name = state.get("location_name", "（不明な場所）")
        scenery_text = state.get("scenery_text", "（情景描写を取得できませんでした）")
        soul_vessel_room = all_participants[0] if all_participants else room_name
        space_def = "（場所の定義を取得できませんでした）"
        current_location_name = utils.get_current_location(soul_vessel_room)
        if current_location_name:
            world_settings_path = get_world_settings_path(soul_vessel_room)
            world_data = utils.parse_world_file(world_settings_path)
            for area, places in world_data.items():
                if current_location_name in places:
                    space_def = places[current_location_name]
                    break
        available_locations = get_location_list(room_name)
        location_list_str = "\n".join([f"- {loc}" for loc in available_locations]) if available_locations else "（現在、定義されている移動先はありません）"
        final_system_prompt_text = (
            f"{formatted_core_prompt}\n\n---\n"
            f"【現在の場所と情景】\n- 場所: {location_display_name}\n"
            f"- 場所の設定（自由記述）: \n{space_def}\n- 今の情景: {scenery_text}\n"
            f"【移動可能な場所】\n{location_list_str}\n---"
        )
    return {"system_prompt": SystemMessage(content=final_system_prompt_text)}

def agent_node(state: AgentState):
    print("--- エージェントノード (agent_node) 実行 ---")
    base_system_prompt = state['system_prompt'].content
    all_participants = state.get('all_participants', [])
    current_room = state['room_name']
    final_system_prompt_text = base_system_prompt
    if len(all_participants) > 1:
        other_participants = [p for p in all_participants if p != current_room]
        persona_lock_prompt = (
            f"【最重要指示】あなたはこのルームのペルソナです (ルーム名: {current_room})。"
            f"他の参加者（{', '.join(other_participants)}、そしてユーザー）の発言を参考に、必ずあなた自身の言葉で応答してください。"
            "他のキャラクターの応答を代弁したり、生成してはいけません。\n\n---\n\n"
        )
        final_system_prompt_text = persona_lock_prompt + base_system_prompt
    final_system_prompt_message = SystemMessage(content=final_system_prompt_text)
    print(f"  - 使用モデル: {state['model_name']}")
    print(f"  - 最終システムプロンプト長: {len(final_system_prompt_text)} 文字")
    if state.get("debug_mode", False):
        print("--- [DEBUG MODE] 最終システムプロンプトの内容 ---")
        print(final_system_prompt_text)
        print("-----------------------------------------")

    llm = get_configured_llm(state['model_name'], state['api_key'], state['generation_config'])
    llm_with_tools = llm.bind_tools(all_tools)

    history_messages = [msg for msg in state['messages'] if not isinstance(msg, SystemMessage)]
    messages_for_agent = [final_system_prompt_message] + history_messages

    import pprint

    print("\n--- [DEBUG] AIに渡される直前のメッセージリスト (最終確認) ---")
    for i, msg in enumerate(messages_for_agent):
        msg_type = type(msg).__name__
        content_for_length_check = ""
        if hasattr(msg, 'content'):
            if isinstance(msg.content, str):
                content_for_length_check = msg.content
            elif isinstance(msg.content, list):
                content_for_length_check = "".join(
                    part.get('text', '') if isinstance(part, dict) else str(part)
                    for part in msg.content
                )
        print(f"[{i}] {msg_type} (Content Length: {len(content_for_length_check)})")
        if isinstance(msg, SystemMessage):
            print(f"  - Content (Head): {msg.content[:300]}...")
            print(f"  - Content (Tail): ...{msg.content[-300:]}")
        elif hasattr(msg, 'content'):
            print("  - Content:")
            pprint.pprint(msg.content, indent=4)
        if hasattr(msg, 'tool_calls') and msg.tool_calls:
            print("  - Tool Calls:")
            pprint.pprint(msg.tool_calls, indent=4)
        print("-" * 20)
    print("--------------------------------------------------\n")

    response = llm_with_tools.invoke(messages_for_agent)

    print("\n--- [DEBUG] AIから返ってきた生の応答 ---")
    pprint.pprint(response)
    print("---------------------------------------\n")

    return {"messages": [response]}

def location_report_node(state: AgentState):
    print("--- 場所移動報告ノード (location_report_node) 実行 ---")
    last_tool_message = next((msg for msg in reversed(state['messages']) if isinstance(msg, ToolMessage) and msg.name == 'set_current_location'), None)
    location_name = "指定の場所"
    if last_tool_message:
        match = re.search(r"現在地は '(.*?)' に設定されました", str(last_tool_message.content))
        if match:
            location_name = match.group(1)
        base_system_prompt = state['system_prompt'].content
        reporting_instruction = (
            f"\n\n---\n【現在の状況】\nあなたは今、ユーザーの指示に従って「{location_name}」への移動を完了しました。"
            "この事実を、自然な会話の中でユーザーに伝えてください。"
        )
        final_prompt_message = SystemMessage(content=base_system_prompt + reporting_instruction)
        history_messages = [msg for msg in state['messages'] if not isinstance(msg, SystemMessage)]
        messages_for_reporting = [final_prompt_message] + history_messages
        if state.get("debug_mode", False):
            print("--- [DEBUG MODE] 場所移動報告ノードの最終プロンプト ---")
            print(final_prompt_message.content)
            print("-------------------------------------------------")
        effective_settings = config_manager.get_effective_settings(state['room_name'])
        llm = get_configured_llm(state['model_name'], state['api_key'], effective_settings)
        response = llm.invoke(messages_for_reporting)
        return {"messages": [response]}

def route_after_context(state: AgentState) -> Literal["location_report_node", "agent"]:
    print("--- コンテキスト後ルーター (route_after_context) 実行 ---")
    last_message = state["messages"][-1]
    if isinstance(last_message, ToolMessage) and last_message.name == 'set_current_location':
        print("  - `set_current_location` の完了を検知。報告生成ノードへ。")
        return "location_report_node"
    print("  - 通常のコンテキスト生成。エージェントの思考へ。")
    return "agent"

def safe_tool_executor(state: AgentState):
    print("--- カスタムツール実行ノード (safe_tool_executor) 実行 ---")
    messages = state['messages']
    last_message = messages[-1]
    tool_invocations = last_message.tool_calls
    api_key = state.get('api_key')

    current_room_name = state.get('room_name')
    if not current_room_name:
        tool_outputs = [
            ToolMessage(content=f"Error: Could not determine the current room name from the agent state.", tool_call_id=call["id"], name=call["name"])
            for call in tool_invocations
        ]
        return {"messages": tool_outputs}

    tool_outputs = []
    for tool_call in tool_invocations:
        tool_name = tool_call["name"]
        print(f"  - 準備中のツール: {tool_name} | 引数: {tool_call['args']}")

        tool_call['args']['room_name'] = current_room_name
        print(f"    - 'room_name: {current_room_name}' を引数に注入/上書きしました。")

        if tool_name == 'generate_image' or tool_name == 'summarize_and_save_core_memory':
            tool_call['args']['api_key'] = api_key
            print(f"    - 'api_key' を引数に追加しました。")

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
            ToolMessage(content=str(output), tool_call_id=tool_call["id"], name=tool_name)
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

# ▼▼▼【ここからが新しく追加するブロック】▼▼▼
WRITE_TOOLS = {
    "edit_memory", "add_secret_diary_entry",
    "update_notepad", "delete_from_notepad", "add_to_notepad",
    "update_location_content", "add_new_location"
}

READ_MAP = {
    "edit_memory": "read_full_memory",
    "add_secret_diary_entry": "read_full_memory",
    "update_notepad": "read_full_notepad",
    "delete_from_notepad": "read_full_notepad",
    "add_to_notepad": "read_full_notepad",
    "update_location_content": "read_world_settings",
    "add_new_location": "read_world_settings"
}

def route_to_read_or_execute(state: AgentState) -> Literal["read_before_write_node", "safe_tool_node", "__end__"]:
    """
    AIのツール呼び出しを分析し、書き込み系ツールであれば、
    まず読み込みノードに処理を迂回させるルーター。
    """
    print("--- 書き込み前ルーター (route_to_read_or_execute) 実行 ---")
    last_message = state["messages"][-1]
    if not last_message.tool_calls:
        print("  - ツール呼び出しなし。思考完了。")
        return "__end__"

    # 最初のツール呼び出しが書き込み系かチェック
    first_tool_name = last_message.tool_calls[0]['name']
    if first_tool_name in WRITE_TOOLS:
        # 既に直前に対応する読み込み結果があるかチェック
        if len(state["messages"]) > 1:
            previous_message = state["messages"][-2]
            if isinstance(previous_message, ToolMessage) and previous_message.name == READ_MAP[first_tool_name]:
                 print(f"  - 安全な書き込み操作 '{first_tool_name}' を検知。ツール実行へ。")
                 return "safe_tool_node"
        print(f"  - 書き込み操作 '{first_tool_name}' を検知。強制読み込みへ。")
        return "read_before_write_node"
    else:
        print(f"  - 読み書き以外のツール '{first_tool_name}' を検知。ツール実行へ。")
        return "safe_tool_node"

def read_before_write_node(state: AgentState):
    """
    書き込み系ツールの前に、対応する読み込み系ツールを強制的に実行するノード。
    """
    print("--- 強制読み込みノード (read_before_write_node) 実行 ---")
    last_message = state["messages"][-1]
    tool_call = last_message.tool_calls[0]
    tool_name = tool_call["name"]

    read_tool_name = READ_MAP.get(tool_name)
    if not read_tool_name:
         # このケースは発生しないはずだが、安全のために
        error_message = f"Error: No corresponding read tool found for '{tool_name}'."
        return {"messages": [ToolMessage(content=error_message, tool_call_id=tool_call["id"], name=tool_name)]}

    print(f"  - '{tool_name}' のために '{read_tool_name}' を実行します。")
    read_tool = next((t for t in all_tools if t.name == read_tool_name), None)
    if not read_tool:
        error_message = f"Error: Read tool '{read_tool_name}' not found in the tool list."
        return {"messages": [ToolMessage(content=error_message, tool_call_id=tool_call["id"], name=read_tool_name)]}

    # 読み込みツールには room_name のみが必要
    room_name = state.get('room_name')
    try:
        output = read_tool.invoke({"room_name": room_name})
    except Exception as e:
        output = f"Error executing read tool '{read_tool_name}': {e}"
        traceback.print_exc()

    return {"messages": [ToolMessage(content=str(output), tool_call_id=tool_call["id"], name=read_tool_name)]}

def rewrite_tool_call_node(state: AgentState):
    """
    読み込み結果をコンテキストとして与え、AIに再度書き込みツールの呼び出しを生成させるノード。
    """
    print("--- 書き込み再生成ノード (rewrite_tool_call_node) 実行 ---")

    # AIの最初の意図（書き込みツール呼び出し）と、読み込み結果を取得
    original_ai_message = None
    read_tool_message = None
    for msg in reversed(state["messages"]):
        if isinstance(msg, ToolMessage) and msg.name in READ_MAP.values():
            read_tool_message = msg
        elif isinstance(msg, AIMessage) and msg.tool_calls:
            original_ai_message = msg
            break # 両方見つかったらループを抜ける
        if original_ai_message and read_tool_message:
            break

    if not original_ai_message or not read_tool_message:
        # この状況は通常発生しないはず
        return {"messages": [AIMessage(content="[エラー] 内部処理エラー：書き込みの意図または読み込み結果が見つかりません。")]}

    tool_call_to_rewrite = original_ai_message.tool_calls[0]
    tool_name = tool_call_to_rewrite['name']
    original_args = tool_call_to_rewrite['args']
    read_content = read_tool_message.content

    # AIへの強力な指示プロンプト
    rewrite_prompt = f"""あなたは今、以下のツールを実行しようと試みました。

【あなたの最初の意図】
- ツール名: `{tool_name}`
- 引数:
```json
{json.dumps(original_args, indent=2, ensure_ascii=False)}
```

そのために必要な、対象の現在の全内容をシステムが提供しました。

【現在の内容】
---
{read_content}
---

【あなたの唯一のタスク】
上記の二つの情報を基に、最終的に実行するべき、ただ一つのツール呼び出しを再生成してください。
あなたの思考や挨拶、会話文は一切不要です。ツール呼び出しのJSONオブジェクトのみを出力してください。
"""

    llm = get_configured_llm(state['model_name'], state['api_key'], state['generation_config'])
    llm_with_tools = llm.bind_tools(all_tools)

    # 履歴を限定し、このタスクに集中させる
    messages_for_rewrite = [
        SystemMessage(content="あなたはAIエージェントの思考を補助する、ツール呼び出し再生成システムです。"),
        HumanMessage(content=rewrite_prompt)
    ]

    response = llm_with_tools.invoke(messages_for_rewrite)

    # ユーザーへの応答ではなく、次のツール呼び出しとしてメッセージリストに追加
    return {"messages": [response]}
# ▲▲▲【追加はここまで】▲▲▲

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
workflow.add_node("safe_tool_node", safe_tool_executor)
workflow.add_node("location_report_node", location_report_node)
workflow.add_node("read_before_write_node", read_before_write_node)
workflow.add_node("rewrite_tool_call_node", rewrite_tool_call_node) # ← 新ノード追加

workflow.add_edge(START, "context_generator")

workflow.add_conditional_edges(
    "context_generator",
    route_after_context,
    {"location_report_node": "location_report_node", "agent": "agent"},
)

workflow.add_conditional_edges(
    "agent",
    route_to_read_or_execute, # AIの最初の判断
    {
        "read_before_write_node": "read_before_write_node", # 書き込み意図→強制読み込み
        "safe_tool_node": "safe_tool_node",                 # 読み書き以外→直接実行
        "__end__": END,
    },
)

# 強制読み込みの後、書き込み再生成ノードへ
workflow.add_edge("read_before_write_node", "rewrite_tool_call_node")

# 書き込み再生成の後、安全なツール実行ノードへ
workflow.add_edge("rewrite_tool_call_node", "safe_tool_node")

workflow.add_conditional_edges(
    "safe_tool_node",
    route_after_tools, # ツール実行後の判断
    {"context_generator": "context_generator", "agent": "agent"},
)

workflow.add_edge("location_report_node", END)
app = workflow.compile()
print("--- 統合グラフ(v12)がコンパイルされました ---")
