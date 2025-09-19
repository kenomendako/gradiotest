# agent/graph.py (v21: Smart Retry)

import os
import re
import traceback
import json
import time
from datetime import datetime
from typing import TypedDict, Annotated, List, Literal, Tuple

from langchain_core.messages import SystemMessage, BaseMessage, ToolMessage, AIMessage, HumanMessage
from google.api_core import exceptions as google_exceptions
from gemini_api import get_configured_llm
from langgraph.graph import StateGraph, END, START, add_messages

from agent.prompts import CORE_PROMPT_TEMPLATE
from tools.space_tools import set_current_location, read_world_settings, plan_world_edit, _apply_world_edits
from tools.memory_tools import read_full_memory, plan_memory_edit, _apply_memory_edits
from tools.notepad_tools import read_full_notepad, plan_notepad_edit, _write_notepad_file
from tools.web_tools import web_search_tool, read_url_tool
from tools.image_tools import generate_image
from tools.alarm_tools import set_personal_alarm
from tools.timer_tools import set_timer, set_pomodoro_timer
from tools.knowledge_tools import search_knowledge_graph
from room_manager import get_world_settings_path
import utils
import config_manager
import constants
import pytz

all_tools = [
    set_current_location, read_world_settings, plan_world_edit,
    read_full_memory, plan_memory_edit,
    read_full_notepad, plan_notepad_edit,
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
    tools_list_str = "\n".join([f"- `{tool.name}({', '.join(tool.args.keys())})`: {tool.description}" for tool in all_tools])
    if len(all_participants) > 1:
        tools_list_str = "（グループ会話中はツールを使用できません）"
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

# ▼▼▼ 以下の関数で、既存の location_report_node を置き換えてください ▼▼▼
def generate_tool_report_node(state: AgentState):
    """
    ツールの実行が完了したことを受け、その結果を自然な対話としてユーザーに報告するための
    最終応答を生成するノード。
    """
    print("--- ツール完了報告ノード (generate_tool_report_node) 実行 ---")

    last_tool_message = next((msg for msg in reversed(state['messages']) if isinstance(msg, ToolMessage)), None)

    if not last_tool_message:
        return {"messages": [AIMessage(content="（ツールの実行結果が見つかりませんでした。処理を続けます。）")]}

    tool_name = last_tool_message.name
    tool_result = str(last_tool_message.content)

    base_system_prompt = state['system_prompt'].content
    reporting_instruction = (
        f"\n\n---\n【現在の状況】\n"
        f"あなたはたった今、ツールの実行を完了しました。\n"
        f"- 実行したツール: `{tool_name}`\n"
        f"- 実行結果の概要: 「{tool_result}」\n\n"
        f"【あなたのタスク】\n"
        f"この事実を、自然な会話の中でユーザーに伝えてください。\n"
        f"ツールの実行を計画した際の、以前のあなたの発言（「これから〜します」など）を繰り返すのではなく、\n"
        f"あくまで「完了した」という事実を基に応答を生成してください。"
    )

    final_prompt_message = SystemMessage(content=base_system_prompt + reporting_instruction)

    history_messages = [msg for msg in state['messages'] if not isinstance(msg, SystemMessage)]
    messages_for_reporting = [final_prompt_message] + history_messages

    if state.get("debug_mode", False):
        print("--- [DEBUG MODE] ツール完了報告ノードの最終プロンプト ---")
        print(final_prompt_message.content)
        print("-------------------------------------------------")

    effective_settings = config_manager.get_effective_settings(state['room_name'])
    llm = get_configured_llm(state['model_name'], state['api_key'], effective_settings)

    response = llm.invoke(messages_for_reporting)
    return {"messages": [response]}

def route_after_context(state: AgentState) -> Literal["generate_tool_report_node", "agent"]:
    print("--- コンテキスト後ルーター (route_after_context) 実行 ---")
    last_message = state["messages"][-1]
    if isinstance(last_message, ToolMessage):
        print(f"  - ツール ({last_message.name}) の完了を検知。報告生成ノードへ。")
        return "generate_tool_report_node"
    print("  - 通常のコンテキスト生成。エージェントの思考へ。")
    return "agent"

def safe_tool_executor(state: AgentState):
    """
    AIのツール呼び出しを仲介し、計画されたファイル編集タスクを実行する。
    APIのレート制限エラーに対して、賢くリトライまたは中断を行う。
    """
    print("--- ツール実行ノード (safe_tool_executor) 実行 ---")
    last_message = state['messages'][-1]
    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        return {}

    tool_call = last_message.tool_calls[0]
    tool_name = tool_call["name"]
    tool_args = tool_call["args"]
    room_name = state.get('room_name')
    api_key = state.get('api_key')

    is_plan_memory = tool_name == "plan_memory_edit"
    is_plan_notepad = tool_name == "plan_notepad_edit"
    is_plan_world = tool_name == "plan_world_edit"

    if is_plan_memory or is_plan_notepad or is_plan_world:
        try:
            print(f"  - ファイル編集プロセスを開始: {tool_name}")

            read_tool = None
            if is_plan_memory: read_tool = read_full_memory
            elif is_plan_notepad: read_tool = read_full_notepad
            elif is_plan_world: read_tool = read_world_settings

            current_content = read_tool.invoke({"room_name": room_name})

            print(f"  - ペルソナAI ({state['model_name']}) に編集タスクを依頼します。")
            llm_persona = get_configured_llm(state['model_name'], state['api_key'], state['generation_config'])

            instruction_templates = {
                "plan_memory_edit": (
                    "【最重要指示：これは『対話』ではなく『設計タスク』です】\n"
                    "あなたは今、自身の記憶を更新するための『設計図』を作成しています。\n"
                    "提示された【既存のデータ】とあなたの【変更要求】に基づき、完璧な【差分指示のリスト】を生成してください。\n\n"
                    "【既存のデータ（memory.json全文）】\n---\n{current_content}\n---\n\n"
                    "【あなたの変更要求】\n「{modification_request}」\n\n"
                    "【絶対的な出力ルール】\n"
                    "- 思考や挨拶は含めず、【差分指示のリスト】（有効なJSON配列）のみを出力してください。\n"
                    "- 各指示は \"operation\" ('set', 'append', 'delete'), \"path\" (\"key.subkey\"形式), \"value\" のキーを持つ辞書です。\n"
                    "- 出力は ` ```json ` と ` ``` ` で囲んでください。"
                ),
                "plan_world_edit": (
                    "【最重要指示：これは『対話』ではなく『世界構築タスク』です】\n"
                    "あなたは今、世界設定を更新するための『設計図』を作成しています。\n"
                    "提示された【既存のデータ】とあなたの【変更要求】に基づき、完璧な【差分指示のリスト】を生成してください。\n\n"
                    "【既存のデータ（world_settings.txt全文）】\n---\n{current_content}\n---\n\n"
                    "【あなたの変更要求】\n「{modification_request}」\n\n"
                    "【絶対的な出力ルール】\n"
                    "- 思考や挨拶は含めず、【差分指示のリスト】（有効なJSON配列）のみを出力してください。\n"
                    "- 各指示は \"operation\" ('update_place_description', 'add_place', 'delete_place'), \"area_name\", \"place_name\", \"value\" のキーを持つ辞書です。\n"
                    "- 出力は ` ```json ` と ` ``` ` で囲んでください。"
                ),
                "plan_notepad_edit": (
                    "【最重要指示：これは『対話』ではなく『編集タスク』です】\n"
                    "あなたは今、自身のメモ帳を更新しています。\n"
                    "提示された【既存のデータ】とあなたの【変更要求】に基づき、最終的にファイルに書き込むべき、完璧な【全文】を生成してください。\n\n"
                    "【既存のデータ（notepad.md全文）】\n---\n{current_content}\n---\n\n"
                    "【あなたの変更要求】\n「{modification_request}」\n\n"
                    "【絶対的な出力ルール】\n"
                    "- 思考や挨拶は含めず、最終的なファイル全文のみを出力してください。"
                )
            }
            formatted_instruction = instruction_templates[tool_name].format(
                current_content=current_content,
                modification_request=tool_args.get('modification_request')
            )
            edit_instruction_message = HumanMessage(content=formatted_instruction)

            messages_for_editing = [msg for msg in state['messages'] if msg is not last_message]
            messages_for_editing.append(edit_instruction_message)
            final_context_for_editing = [state['system_prompt']] + messages_for_editing

            # ▼▼▼【ここからがスマートリトライ機構の核心】▼▼▼
            edited_content_document = None
            max_retries = 5
            base_delay = 5
            for attempt in range(max_retries):
                try:
                    response = llm_persona.invoke(final_context_for_editing)
                    edited_content_document = response.content.strip()
                    break # 成功したらループを抜ける
                except google_exceptions.ResourceExhausted as e:
                    error_str = str(e)
                    # 1. 回復不能なエラー（日間上限など）かチェック
                    if "PerDay" in error_str or "Daily" in error_str:
                        print(f"  - 致命的エラー: 回復不能なAPI上限（日間など）に達しました。処理を中断します。")
                        raise RuntimeError("回復不能なAPIレート上限（日間など）に達したため、処理を中断しました。") from e

                    # 2. 回復可能なエラーの場合、推奨待機時間を抽出
                    wait_time = base_delay * (2 ** attempt) # デフォルトの待機時間
                    match = re.search(r"retry_delay {\s*seconds: (\d+)\s*}", error_str)
                    if match:
                        # APIが推奨する待機時間があれば、それに従う (+1秒のバッファ)
                        wait_time = int(match.group(1)) + 1
                        print(f"  - APIレート制限: APIの推奨に従い {wait_time}秒 待機します...")
                    else:
                        print(f"  - APIレート制限: 指数バックオフで {wait_time}秒 待機します...")

                    if attempt < max_retries - 1:
                        time.sleep(wait_time)
                    else:
                        # 全てのリトライが失敗した場合
                        raise e
                except (google_exceptions.ServiceUnavailable, google_exceptions.InternalServerError) as e:
                    # 503サーバーエラーなどの場合
                    if attempt < max_retries - 1:
                        wait_time = base_delay * (2 ** attempt)
                        print(f"  - 警告: 編集AIが応答不能です ({e.args[0]})。{wait_time}秒待機して再試行します... ({attempt + 1}/{max_retries})")
                        time.sleep(wait_time)
                    else:
                        raise e
            # ▲▲▲【スマートリトライ機構ここまで】▲▲▲

            if edited_content_document is None:
                raise RuntimeError("編集AIからの応答が、リトライ後も得られませんでした。")

            print("  - AIからの応答を受け、ファイル書き込みを実行します。")

            if is_plan_memory or is_plan_world:
                json_match = re.search(r'```json\s*([\s\S]*?)\s*```', edited_content_document, re.DOTALL)
                content_to_process = json_match.group(1).strip() if json_match else edited_content_document
                instructions = json.loads(content_to_process)
                if is_plan_memory:
                    output = _apply_memory_edits(instructions=instructions, room_name=room_name)
                else:
                    output = _apply_world_edits(instructions=instructions, room_name=room_name)
            else:
                text_match = re.search(r'```(?:.*\n)?([\s\S]*?)```', edited_content_document, re.DOTALL)
                content_to_process = text_match.group(1).strip() if text_match else edited_content_document
                output = _write_notepad_file(full_content=content_to_process, room_name=room_name, modification_request=tool_args.get('modification_request'))

        except Exception as e:
            output = f"ファイル編集プロセス中にエラーが発生しました ('{tool_name}'): {e}"
            traceback.print_exc()
    else:
        print(f"  - 通常ツール実行: {tool_name}")
        tool_args['room_name'] = room_name
        if tool_name in ['generate_image']:
            tool_args['api_key'] = api_key

        selected_tool = next((t for t in all_tools if t.name == tool_name), None)
        if not selected_tool:
            output = f"Error: Tool '{tool_name}' not found."
        else:
            try:
                output = selected_tool.invoke(tool_args)
            except Exception as e:
                output = f"Error executing tool '{tool_name}': {e}"
                traceback.print_exc()

    return {"messages": [ToolMessage(content=str(output), tool_call_id=tool_call["id"], name=tool_name)]}

def route_after_agent(state: AgentState) -> Literal["__end__", "safe_tool_node"]:
    print("--- エージェント後ルーター (route_after_agent) 実行 ---")
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        print("  - ツール呼び出しあり。ツール実行ノードへ。")
        for tool_call in last_message.tool_calls: print(f"    🛠️ ツール呼び出し: {tool_call['name']} | 引数: {tool_call['args']}")
        return "safe_tool_node"
    print("  - ツール呼び出しなし。思考完了と判断し、グラフを終了します。")
    return "__end__"

def route_after_tools(state: AgentState) -> Literal["context_generator"]:
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

    print("  - ツールの実行が完了したため、コンテキスト再生成へ。")
    return "context_generator"

# ▼▼▼ ファイル末尾のグラフ定義ブロックを、以下で置き換えてください ▼▼▼
workflow = StateGraph(AgentState)
workflow.add_node("context_generator", context_generator_node)
workflow.add_node("agent", agent_node)
workflow.add_node("safe_tool_node", safe_tool_executor)
workflow.add_node("generate_tool_report_node", generate_tool_report_node)

workflow.add_edge(START, "context_generator")
workflow.add_conditional_edges(
    "context_generator",
    route_after_context,
    {"generate_tool_report_node": "generate_tool_report_node", "agent": "agent"},
)
workflow.add_conditional_edges(
    "agent",
    route_after_agent,
    {"safe_tool_node": "safe_tool_node", "__end__": END},
)
workflow.add_conditional_edges(
    "safe_tool_node",
    route_after_tools,
    {"context_generator": "context_generator"},
)
workflow.add_edge("generate_tool_report_node", END)
app = workflow.compile()
print("--- 統合グラフ(The Final Covenant)がコンパイルされました ---")
