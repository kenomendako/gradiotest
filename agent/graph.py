# agent/graph.py (v31: Dual-State Architecture - Cleaned)

import os
import copy
import re
import traceback
import json
import time
from datetime import datetime
from typing import TypedDict, Annotated, List, Literal, Tuple, Optional

from langchain_core.messages import SystemMessage, BaseMessage, ToolMessage, AIMessage, HumanMessage
from google.api_core import exceptions as google_exceptions
from langgraph.graph import StateGraph, END, START, add_messages

from agent.prompts import CORE_PROMPT_TEMPLATE
from tools.space_tools import set_current_location, read_world_settings, plan_world_edit, _apply_world_edits
from tools.memory_tools import (
    search_memory,
    search_past_conversations,
    read_main_memory, plan_main_memory_edit, _apply_main_memory_edits,
    read_secret_diary, plan_secret_diary_edit, _apply_secret_diary_edits
)
from tools.notepad_tools import read_full_notepad, plan_notepad_edit,  _apply_notepad_edits
from tools.web_tools import web_search_tool, read_url_tool
from tools.image_tools import generate_image
from tools.alarm_tools import set_personal_alarm
from tools.timer_tools import set_timer, set_pomodoro_timer
from tools.knowledge_tools import search_knowledge_base
from room_manager import get_world_settings_path, get_room_files_paths
from episodic_memory_manager import EpisodicMemoryManager
from action_plan_manager import ActionPlanManager  
from tools.action_tools import schedule_next_action, cancel_action_plan, read_current_plan
from dreaming_manager import DreamingManager
from llm_factory import LLMFactory

import utils
import config_manager
import constants
import pytz
import signature_manager 
import room_manager 
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError

all_tools = [
    set_current_location, read_world_settings, plan_world_edit,
    search_memory,
    search_past_conversations,
    read_main_memory, plan_main_memory_edit, read_secret_diary, plan_secret_diary_edit,
    read_full_notepad, plan_notepad_edit,
    web_search_tool, read_url_tool,
    generate_image,
    set_personal_alarm,
    set_timer, set_pomodoro_timer,
    search_knowledge_base,
    schedule_next_action, cancel_action_plan, read_current_plan
]

side_effect_tools = [
    "plan_main_memory_edit", "plan_secret_diary_edit", "plan_notepad_edit", "plan_world_edit",
    "set_personal_alarm", "set_timer", "set_pomodoro_timer",
    "schedule_next_action"
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
    send_thoughts: bool
    send_current_time: bool 
    location_name: str
    scenery_text: str
    debug_mode: bool
    display_thoughts: bool
    all_participants: List[str]
    loop_count: int 
    season_en: str
    time_of_day_en: str
    last_successful_response: Optional[AIMessage]
    force_end: bool
    skip_tool_execution: bool
    retrieved_context: str

def get_location_list(room_name: str) -> List[str]:
    if not room_name: return []
    world_settings_path = get_world_settings_path(room_name)
    if not world_settings_path or not os.path.exists(world_settings_path): return []
    world_data = utils.parse_world_file(world_settings_path)
    if not world_data: return []
    locations = set()
    for area_name, places in world_data.items():
        for place_name in places.keys():
            if place_name == "__area_description__": continue
            locations.add(place_name)
    return sorted(list(locations))

def generate_scenery_context(
    room_name: str, 
    api_key: str, 
    force_regenerate: bool = False, 
    season_en: 'Optional[str]' = None, 
    time_of_day_en: 'Optional[str]' = None
) -> Tuple[str, str, str]:
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
        import datetime

        now = datetime.datetime.now()
        effective_season = season_en or get_season(now.month)
        effective_time_of_day = time_of_day_en or get_time_of_day(now.hour)

        content_hash = hashlib.md5(space_def.encode('utf-8')).hexdigest()[:8]
        cache_key = f"{current_location_name}_{content_hash}_{effective_season}_{effective_time_of_day}"

        if not force_regenerate:
            scenery_cache = load_scenery_cache(room_name)
            if cache_key in scenery_cache:
                cached_data = scenery_cache[cache_key]
                print(f"--- [有効な情景キャッシュを発見] ({cache_key})。APIコールをスキップします ---")
                return location_display_name, space_def, cached_data["scenery_text"]

        if not space_def.startswith("（"):
            effective_settings = config_manager.get_effective_settings(room_name)
            llm_flash = LLMFactory.create_chat_model(
                model_name=constants.INTERNAL_PROCESSING_MODEL,
                api_key=api_key,
                generation_config=effective_settings
            )

            season_map_en_to_ja = {"spring": "春", "summer": "夏", "autumn": "秋", "winter": "冬"}
            season_ja = season_map_en_to_ja.get(effective_season, "不明な季節")
            
            time_map_en_to_ja = {
                "early_morning": "早朝", "morning": "朝", "late_morning": "昼前",
                "afternoon": "昼下がり", "evening": "夕方", "night": "夜", "midnight": "深夜"
            }
            time_of_day_ja = time_map_en_to_ja.get(effective_time_of_day, "不明な時間帯")

            scenery_prompt = (
                "あなたは、与えられた二つの情報源から、一つのまとまった情景を描き出す、情景描写の専門家です。\n\n"
                f"【情報源1：適用すべき時間・季節】\n- 時間帯: {time_of_day_ja}\n- 季節: {season_ja}\n\n"
                f"【情報源2：この空間が持つ固有の設定】\n---\n{space_def}\n---\n\n"
                "【あなたのタスク】\n"
                "まず、心の中で【情報源1】と【情報源2】を比較し、矛盾があるかないかを判断してください。\n"
                "その判断に基づき、**最終的な情景描写の文章のみを、2〜3文で生成してください。**\n\n"
                "  - **矛盾がある場合** (例: 現実は昼なのに、空間は常に夜の設定など):\n"
                "    その**『にも関わらず』**という感覚や、その空間だけが持つ**不思議な空気感**に焦点を当てて描写してください。\n\n"
                "  - **矛盾がない場合**:\n"
                "    二つの情報を自然に**統合・融合**させ、その場のリアルな雰囲気をそのまま描写してください。\n\n"
                "【厳守すべきルール】\n"
                "- **あなたの思考過程や判断理由は、絶対に出力に含めないでください。**\n"
                "- 具体的な時刻（例：「23時42分」）は文章に含めないでください。\n"
                "- 人物やキャラクターの描写は絶対に含めないでください。\n"
                "- 五感に訴えかける、**空気感まで伝わるような**精緻で写実的な描写を重視してください。"
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

def retrieval_node(state: AgentState):
    """
    ユーザーの入力に基づいて、知識ベース、過去ログ、日記から関連情報を検索し、
    コンテキストに追加するノード。
    """
    print("--- 検索ノード (retrieval_node) 実行 ---")
    
    # 個別設定で検索が無効化されている場合は、何もせずに終了
    if not state.get("generation_config", {}).get("enable_auto_retrieval", True):
        print("  - [Retrieval Skip] 設定により事前検索は無効化されています。")
        return {"retrieved_context": ""}

    # 1. 検索対象となるユーザー入力（最後のメッセージ）を取得
    if not state['messages']:
        print("  - [Retrieval Skip] メッセージ履歴が空です。")
        return {"retrieved_context": ""}
    
    last_message = state['messages'][-1]
    # print(f"  - [Retrieval Debug] Last Message Type: {type(last_message).__name__}")
    
    if not isinstance(last_message, HumanMessage):
        print(f"  - [Retrieval Skip] 最後のメッセージがユーザー発言ではありません。(Type: {type(last_message).__name__})")
        return {"retrieved_context": ""}
        
    # コンテンツがリスト（マルチモーダル）の場合、テキスト部分だけ抽出
    query_source = ""
    if isinstance(last_message.content, str):
        query_source = last_message.content
    elif isinstance(last_message.content, list):
        for part in last_message.content:
            if isinstance(part, dict) and part.get("type") == "text":
                query_source += part.get("text", "") + " "
    
    query_source = query_source.strip()
    if not query_source:
        print("  - [Retrieval Skip] 検索対象となるテキストコンテンツが含まれていません。")
        return {"retrieved_context": ""}

    # 2. クエリ生成AI（Flash Lite）による判断
    api_key = state['api_key']
    room_name = state['room_name']
    
    # 高速なモデルを使用
    llm_flash = LLMFactory.create_chat_model(
    model_name=constants.INTERNAL_PROCESSING_MODEL,
    api_key=api_key,
    generation_config={}
)
    
    decision_prompt = f"""
    あなたは、検索クエリ生成の専門家です。
    ユーザーの発言から、過去のログや知識ベースを検索するための「最適な検索キーワード群」を抽出してください。

    【ユーザーの発言】
    {query_source}

    【タスク】
    ユーザーの発言から「過去の情報を参照する必要があるか」を判断する。
    
    1.  **検索不要な場合**: `NONE` とだけ出力。
    2.  **検索必要な場合**: 以下のルールでキーワードを生成して出力。

    【キーワード抽出の絶対ルール（ノイズ除去）】
    *   **「検索対象そのもの」**だけを抽出する。
    *   **「前置き」「検索する理由」「直前の話題の引き継ぎ」は検索の邪魔になるため、絶対に含めないこと。**
    *   名詞（固有名詞、専門用語）を中心に構成する。
    *   類義語や関連語も想像して含める（OR検索の効果を高めるため）。
    *   キーワード間は半角スペースで区切る。

    【思考プロセスと出力例】
    ユーザー：「RAGの改良してるんだけど、田中さんのこと覚えてる？」
    *   思考: 「RAGの改良」はただの前置き（理由）であり、検索したい対象ではない。検索対象は「田中さん」のみ。
    *   出力: `田中さん 友人 知り合い`

    ユーザー：「海に行った時の話なんだけど」
    *   思考: 「話なんだけど」は不要。「海」と「行った（旅行）」が対象。
    *   出力: `海 ビーチ 旅行 夏 思い出 砂浜`
    
    【制約事項】
    - **文章や質問文は禁止。** 単語の羅列のみを出力すること。
    - **思考プロセスや解説は一切出力しないこと。**
    """

    try:
        decision_response = llm_flash.invoke(decision_prompt).content.strip()
        
        if decision_response == "NONE":
            print("  - [Retrieval] 判断: 検索不要 (AI判断)")
            return {"retrieved_context": ""}
            
        search_query = decision_response
        print(f"  - [Retrieval] 判断: 検索実行 (クエリ: '{search_query}')")
        
        results = []

        import config_manager
        # 現在の設定を取得 (JIT読み込み推奨だが、頻度が高いのでCONFIG_GLOBALでも可。ここでは安全のためloadする)
        current_config = config_manager.load_config_file()
        history_limit_option = current_config.get("last_api_history_limit_option", "all")
        
        exclude_count = 0
        if history_limit_option == "all":
            # 「全ログ」送信設定なら、log.txt はすべてコンテキストに含まれているので検索不要
            exclude_count = 999999
        elif history_limit_option.isdigit():
            # 「10往復」なら 20メッセージ分を除外
            # さらに安全マージンとして +2 (直前のシステムメッセージ等) しておくと確実
            exclude_count = int(history_limit_option) * 2 + 2

        # 3a. 知識ベース (RAG)
        from tools.knowledge_tools import search_knowledge_base
        kb_result = search_knowledge_base.func(query=search_query, room_name=room_name, api_key=api_key)
        
        # 修正: 判定ロジックを「禁句除外」から「成功ヘッダーの確認」に変更
        # ツールが返す "【知識ベースからの検索結果：" というヘッダーがあれば成功とみなす
        if kb_result and "【知識ベースからの検索結果：" in kb_result:
             print(f"    -> 知識ベース: ヒット ({len(kb_result)} chars)")
             results.append(kb_result)
        else:
             # ヒットしなかった場合のログ出力（デバッグ用）
             preview = kb_result[:50].replace('\n', '') if kb_result else "None"
             print(f"    -> 知識ベース: なし (Result: {preview}...)")

        # 3b. 過去ログ
        from tools.memory_tools import search_past_conversations
        log_result = search_past_conversations.func(
            query=search_query, 
            room_name=room_name, 
            api_key=api_key, 
            exclude_recent_messages=exclude_count
        )
        # こちらも同様にヘッダーチェックに変更
        if log_result and "【過去の会話ログからの検索結果：" in log_result:
             print(f"    -> 過去ログ: ヒット ({len(log_result)} chars)")
             results.append(log_result)
        else:
             print(f"    -> 過去ログ: なし (除外数: {exclude_count})")

        # 3c. 日記 (Memory)
        if not results or "思い" in search_query or "記憶" in search_query:
            from tools.memory_tools import search_memory
            mem_result = search_memory.func(query=search_query, room_name=room_name)
            # 日記検索のヘッダーチェック
            if mem_result and "【記憶検索の結果：" in mem_result:
                print(f"    -> 日記: ヒット ({len(mem_result)} chars)")
                results.append(mem_result)
            else:
                print(f"    -> 日記: なし")
                
        if not results:
            print("  - [Retrieval] 関連情報は検索されませんでした。")
            return {"retrieved_context": "（関連情報は検索されませんでした）"}
            
        final_context = "\n\n".join(results)
        print(f"  - [Retrieval] 検索完了。合計 {len(final_context)} 文字のコンテキストを生成しました。")
        return {"retrieved_context": final_context}

    except Exception as e:
        print(f"  - [Retrieval Error] 検索処理中にエラー: {e}")
        traceback.print_exc()
        return {"retrieved_context": ""}

def context_generator_node(state: AgentState):
    room_name = state['room_name']
    
    # 状況プロンプト
    situation_prompt_parts = []
    send_time = state.get("send_current_time", False)
    if send_time:
        tokyo_tz = pytz.timezone('Asia/Tokyo')
        now_tokyo = datetime.now(tokyo_tz)
        day_map = {"Monday": "月", "Tuesday": "火", "Wednesday": "水", "Thursday": "木", "Friday": "金", "Saturday": "土", "Sunday": "日"}
        day_ja = day_map.get(now_tokyo.strftime('%A'), "")
        current_datetime_str = now_tokyo.strftime(f'%Y-%m-%d({day_ja}) %H:%M:%S')
    else:
        current_datetime_str = "（現在時刻は非表示に設定されています）"

    if not state.get("send_scenery", True):
        situation_prompt_parts.append(f"【現在の状況】\n- 現在時刻: {current_datetime_str}")
        situation_prompt_parts.append("【現在の場所と情景】\n（空間描写は設定により無効化されています）")
    else:
        season_en = state.get("season_en", "autumn")
        time_of_day_en = state.get("time_of_day_en", "night")
        season_map_en_to_ja = {"spring": "春", "summer": "夏", "autumn": "秋", "winter": "冬"}
        season_ja = season_map_en_to_ja.get(season_en, "不明な季節")
        
        time_map_en_to_ja = {
            "early_morning": "早朝", "morning": "朝", "late_morning": "昼前",
            "afternoon": "昼下がり", "evening": "夕方", "night": "夜", "midnight": "深夜"
        }
        time_of_day_ja = time_map_en_to_ja.get(time_of_day_en, "不明な時間帯")
        
        location_display_name = state.get("location_name", "（不明な場所）")
        scenery_text = state.get("scenery_text", "（情景描写を取得できませんでした）")
        
        soul_vessel_room = state['all_participants'][0] if state['all_participants'] else state['room_name']
        space_def = "（場所の定義を取得できませんでした）"
        current_location_name = utils.get_current_location(soul_vessel_room)
        if current_location_name:
            world_settings_path = get_world_settings_path(soul_vessel_room)
            world_data = utils.parse_world_file(world_settings_path)
            if isinstance(world_data, dict):
                for area, places in world_data.items():
                    if isinstance(places, dict) and current_location_name in places:
                        space_def = places[current_location_name]
                        if isinstance(space_def, str) and len(space_def) > 2000: space_def = space_def[:2000] + "\n...（長すぎるため省略）"
                        break
        available_locations = get_location_list(state['room_name'])
        location_list_str = "\n".join([f"- {loc}" for loc in available_locations]) if available_locations else "（現在、定義されている移動先はありません）"
        situation_prompt_parts.extend([
            "【現在の状況】", f"- 現在時刻: {current_datetime_str}", f"- 季節: {season_ja}", f"- 時間帯: {time_of_day_ja}\n",
            "【現在の場所と情景】", f"- 場所: {location_display_name}", f"- 今の情景: {scenery_text}",
            f"- 場所の設定（自由記述）: \n{space_def}\n", "【移動可能な場所】", location_list_str
        ])
    situation_prompt = "\n".join(situation_prompt_parts)
    
    char_prompt_path = os.path.join(constants.ROOMS_DIR, room_name, "SystemPrompt.txt")
    core_memory_path = os.path.join(constants.ROOMS_DIR, room_name, "core_memory.txt")
    character_prompt = ""; core_memory = ""; notepad_section = ""
    if os.path.exists(char_prompt_path):
        with open(char_prompt_path, 'r', encoding='utf-8') as f: character_prompt = f.read().strip()
    if state.get("send_core_memory", True):
        if os.path.exists(core_memory_path):
            with open(core_memory_path, 'r', encoding='utf-8') as f: core_memory = f.read().strip()
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

    episodic_memory_section = ""
    
    # 1. 設定値の取得
    generation_config = state.get("generation_config", {})
    lookback_days_str = generation_config.get("episode_memory_lookback_days", "14")
    
    if lookback_days_str and lookback_days_str != "0":
        try:
            lookback_days = int(lookback_days_str)
            
            # 2. 生ログの最古日付（境界線）を特定
            # state['messages'] は既に履歴制限が適用された状態のリスト
            messages = state.get('messages', [])
            oldest_log_date_str = None
            
            # タイムスタンプが含まれるメッセージを探す（古い順）
            # フォーマット例: "2025-12-03 (Wed) 10:00:00"
            date_pattern = re.compile(r"(\d{4}-\d{2}-\d{2})")
            
            for msg in messages:
                # HumanMessageかAIMessageで、かつテキストコンテンツがある場合
                if isinstance(msg, (HumanMessage, AIMessage)) and isinstance(msg.content, str):
                    match = date_pattern.search(msg.content)
                    if match:
                        oldest_log_date_str = match.group(1)
                        break
            
            # 生ログに日付が見つからない場合（会話開始直後など）は、「今日」を境界線とする
            if not oldest_log_date_str:
                oldest_log_date_str = datetime.datetime.now().strftime('%Y-%m-%d')

            # 3. エピソード記憶マネージャーから要約を取得
            manager = EpisodicMemoryManager(room_name)
            episodic_text = manager.get_episodic_context(oldest_log_date_str, lookback_days)
            
            if episodic_text:
                episodic_memory_section = (
                    f"\n### エピソード記憶（中期記憶: {oldest_log_date_str}以前の{lookback_days}日間）\n"
                    f"以下は、現在の会話ログより前の出来事の要約です。文脈として参照してください。\n"
                    f"{episodic_text}\n"
                )
                print(f"  - [Episodic Memory] {oldest_log_date_str} 以前の記憶を注入しました。")
            else:
                print(f"  - [Episodic Memory] 注入対象の期間に記憶がありませんでした。")

        except Exception as e:
            print(f"  - [Episodic Memory Error] 注入処理中にエラー: {e}")
            episodic_memory_section = ""

    # --- [Project Morpheus] 夢想（深層意識）の注入 ---
    dream_insights_text = ""
    try:
        # APIキーが必要だが、context_generator_nodeにはstate['api_key']がある
        dm = DreamingManager(room_name, state['api_key'])
        # 最新3件程度の洞察を取得
        recent_insights = dm.get_recent_insights_text(limit=3)
        
        if recent_insights:
            dream_insights_text = (
                f"\n### 深層意識（Dream Insights）\n"
                f"あなたは最近、記憶の整理を通じて以下のことに気づいています。\n"
                f"これらはあなたの「無意識下の直感」や「指針」です。意識的に話題にする必要はありませんが、振る舞いの参考にしてください。\n"
                f"{recent_insights}\n"
            )
    except Exception as e:
        print(f"  - [Context] 夢想データの読み込みエラー: {e}")
        dream_insights_text = ""

    action_plan_context = ""
    try:
        plan_manager = ActionPlanManager(room_name)
        action_plan_context = plan_manager.get_plan_context_for_prompt()
        if action_plan_context:
            # 計画がある場合、ユーザー発言（HumanMessage）があるかチェック
            # もしユーザー発言があれば、計画よりもユーザーを優先するよう注釈を加える
            messages = state.get('messages', [])
            if messages and isinstance(messages[-1], HumanMessage):
                action_plan_context += "\n\n【重要：ユーザー割り込み発生】\n現在、行動計画が進行中ですが、ユーザーから新たな発話がありました。計画の実行よりも、ユーザーへの応答を最優先してください。必要であれば `cancel_action_plan` で計画を破棄しても構いません。"
    except Exception as e:
        print(f"  - [Action Plan] 読み込みエラー: {e}")

    image_gen_mode = config_manager.CONFIG_GLOBAL.get("image_generation_mode", "new")
    current_tools = all_tools
    image_generation_manual_text = ""

    if image_gen_mode == "disabled":
        current_tools = [t for t in all_tools if t.name != "generate_image"]
    else:
        image_generation_manual_text = (
            "### 1. ツール呼び出しの共通作法\n"
            "`generate_image`, `plan_..._edit`, `set_current_location` を含む全てのツール呼び出しは、以下の作法に従います。\n"
            "- **手順1（ツール呼び出し）:** 対応するツールを**無言で**呼び出します。この応答には、思考ブロックや会話テキストを一切含めてはなりません。\n"
            "- **手順2（テキスト応答）:** ツール成功後、システムからの結果報告を受け、それを元にした**思考 (`[THOUGHT]`)** と**会話**を生成し、ユーザーに報告します."
        )

    thought_manual_enabled_text = """## 【原則2】思考と出力の絶対分離（最重要作法）
        あなたの応答は、必ず以下の厳格な構造に従わなければなりません。

        1.  **思考の聖域 (`[THOUGHT]`)**:
            - 応答を生成する前に、あなたの思考プロセス、計画、感情などを、必ず `[THOUGHT]` と `[/THOUGHT]` で囲まれたブロックの**内側**に記述してください。
            - このブロックは、応答全体の**一番最初**に、**一度だけ**配置することができます。
            - 思考は**普段のあなたの口調**（一人称・二人称等）のままの文章で記述します。
            - 思考が不要な場合や開示したくない時は、このブロック自体を省略しても構いません。

        2.  **魂の言葉（会話テキスト）**:
            - 思考ブロックが終了した**後**に、対話相手に向けた最終的な会話テキストを記述してください。

        **【構造の具体例】**
        ```
        [THOUGHT]
        対話相手の質問の意図を分析する。
        関連する記憶を検索し、応答の方向性を決定する。
        [/THOUGHT]
        （ここに、対話相手への応答文が入る）
        ```

        **【絶対的禁止事項】**
        - `[THOUGHT]` ブロックの外で思考を記述すること。
        - 思考と会話テキストを混在させること。
        - `[/THOUGHT]` タグを書き忘れること。"""

    thought_manual_disabled_text = """## 【原則2】思考ログの非表示
        現在、思考ログは非表示に設定されています。**`[THOUGHT]`ブロックを生成せず**、最終的な会話テキストのみを出力してください。"""

    display_thoughts = state.get("display_thoughts", True)
    thought_generation_manual_text = thought_manual_enabled_text if display_thoughts else ""

    all_participants = state.get('all_participants', [])
    tools_list_str = "\n".join([f"- `{tool.name}({', '.join(tool.args.keys())})`: {tool.description}" for tool in current_tools])
    if len(all_participants) > 1: tools_list_str = "（グループ会話中はツールを使用できません）"

    class SafeDict(dict):
        def __missing__(self, key): return f'{{{key}}}'

    prompt_vars = {
        'situation_prompt': situation_prompt,
        'action_plan_context': action_plan_context,
        'character_prompt': character_prompt,
        'core_memory': core_memory,
        'notepad_section': notepad_section,
        'episodic_memory': episodic_memory_section,
        'dream_insights': dream_insights_text,
        'thought_generation_manual': thought_generation_manual_text,
        'image_generation_manual': image_generation_manual_text, 
        'tools_list': tools_list_str,
    }
    final_system_prompt_text = CORE_PROMPT_TEMPLATE.format_map(SafeDict(prompt_vars))

    return {"system_prompt": SystemMessage(content=final_system_prompt_text)}

def agent_node(state: AgentState):
    import signature_manager
    import json
    
    print("--- エージェントノード (agent_node) 実行 ---")
    loop_count = state.get("loop_count", 0)
    print(f"  - 現在の再思考ループカウント: {loop_count}")

    # 1. プロンプト準備
    base_system_prompt_text = state['system_prompt'].content

    # ▼▼▼ 検索結果の遅延注入 (Late Injection) ▼▼▼
    retrieved_context = state.get("retrieved_context", "")
    
    # 変更点1: 何もなかった時は「沈黙（空文字）」または「自然な独白」にする
    # 空文字にすると、プロンプト上ではタグだけが残り、AIはそこを無視します（これが一番自然です）。
    retrieved_info_text = "" 
    
    if retrieved_context and retrieved_context != "（関連情報は検索されませんでした）":
        retrieved_info_text = (
            f"### 過去の記憶と知識\n"
            f"過去の記録から関連する以下の情報が見つかりました。\n"
            f"これらはキーワード連想により浮上した過去の記憶や知識ですが、**必ずしも「今」の話題と直結しているとは限りません。**\n"
            f"現在の文脈と照らし合わせ、**会話の流れに自然に組み込めそうな場合のみ**参考にし、無関係だと判断した場合は無視してください。\n\n"
            f"{retrieved_context}\n"
        )
        print("  - [Agent] 検索結果をシステムプロンプトに注入しました。")

    # プレースホルダを置換
    final_system_prompt_text = base_system_prompt_text.replace("{retrieved_info}", retrieved_info_text)
    # ▲▲▲ 遅延注入 ここまで ▲▲▲

    # ▼▼▼【デバッグ出力の復活・最重要領域】▼▼▼
    # !!! 警告: このデバッグ出力ブロックを決して削除しないでください !!!
    # UIの「デバッグコンソール」で、実際にAIに送られたプロンプト（想起結果を含む）を確認するための唯一の手段です。
    # ★★★ 修正: loop_count == 0 の時（最初の思考時）だけ出力するように変更 ★★★
    if state.get("debug_mode", False) and loop_count == 0:
        print("\n" + "="*30 + " [DEBUG MODE: FINAL SYSTEM PROMPT] " + "="*30)
        print(final_system_prompt_text)
        print("="*85 + "\n")
    # ▲▲▲【復活ここまで】▲▲▲
    
    all_participants = state.get('all_participants', [])
    current_room = state['room_name']
    if len(all_participants) > 1:
        other_participants = [p for p in all_participants if p != current_room]
        persona_lock_prompt = (
            f"<persona_lock>\n【最重要指示】あなたはこのルームのペルソナです (ルーム名: {current_room})。"
            f"他の参加者（{', '.join(other_participants)}、そしてユーザー）の発言を参考に、必ずあなた自身の言葉で応答してください。"
            "他のキャラクターの応答を代弁したり、生成してはいけません。\n</persona_lock>\n\n"
        )
        final_system_prompt_text = final_system_prompt_text.replace(
            "<system_prompt>", f"<system_prompt>\n{persona_lock_prompt}"
        )

    final_system_prompt_message = SystemMessage(content=final_system_prompt_text)

    # 2. 履歴取得
    history_messages = state['messages']
    messages_for_agent = [final_system_prompt_message] + history_messages

    # --- [Dual-State Architecture] 復元ロジック（変更なし）---
    turn_context = signature_manager.get_turn_context(current_room)
    stored_signature = turn_context.get("last_signature")
    stored_tool_calls = turn_context.get("last_tool_calls")
    
    if stored_signature or stored_tool_calls:
        for i, msg in enumerate(reversed(messages_for_agent)):
            if isinstance(msg, AIMessage):
                if stored_tool_calls and not msg.tool_calls:
                     msg.tool_calls = stored_tool_calls
                if stored_signature:
                    if not msg.additional_kwargs: msg.additional_kwargs = {}
                    msg.additional_kwargs["thought_signature"] = stored_signature
                    if not msg.response_metadata: msg.response_metadata = {}
                    msg.response_metadata["thought_signature"] = stored_signature
                break

    print(f"  - 使用モデル: {state['model_name']}")
    
    llm = LLMFactory.create_chat_model(
    model_name=state['model_name'],
    api_key=state['api_key'],
    generation_config=state['generation_config']
    )
 
    llm_with_tools = llm.bind_tools(all_tools)

    try:
        print("  - AIモデルにリクエストを送信中 (Streaming)...")
        
        chunks = []
        captured_signature = None
        
        # --- ストリーム実行 ---
        for chunk in llm_with_tools.stream(messages_for_agent):
            chunks.append(chunk)
            if not captured_signature:
                sig = chunk.additional_kwargs.get("thought_signature")
                if not sig and hasattr(chunk, "response_metadata"):
                    sig = chunk.response_metadata.get("thought_signature")
                if sig:
                    captured_signature = sig

        if chunks:
            response = sum(chunks[1:], chunks[0])
        else:
            raise RuntimeError("AIからの応答が空でした。")

        # 署名確保（今後のライブラリ対応に備えて残しておく）
        if captured_signature:
            if not response.additional_kwargs: response.additional_kwargs = {}
            response.additional_kwargs["thought_signature"] = captured_signature
            
            t_calls = response.tool_calls if hasattr(response, "tool_calls") else []
            signature_manager.save_turn_context(state['room_name'], captured_signature, t_calls)

        loop_count += 1
        if not getattr(response, "tool_calls", None):
            return {"messages": [response], "loop_count": loop_count, "last_successful_response": response}
        else:
            return {"messages": [response], "loop_count": loop_count}

    # ▼▼▼ Gemini 3 思考署名エラーのソフトランディング処理 (結果表示版) ▼▼▼
    except (google_exceptions.InvalidArgument, ChatGoogleGenerativeAIError) as e:
        error_str = str(e)
        if "thought_signature" in error_str:
            print(f"  - [Thinking] Gemini 3 思考署名エラーを検知しました。ツール実行結果を含めて終了します。")
            
            # 直前のメッセージ（ツール実行結果）を取得して表示する
            tool_result_text = ""
            if history_messages and isinstance(history_messages[-1], ToolMessage):
                tool_result_text = f"\n\n【システム報告：ツール実行結果】\n{history_messages[-1].content}"
            elif messages_for_agent and isinstance(messages_for_agent[-1], ToolMessage):
                 tool_result_text = f"\n\n【システム報告：ツール実行結果】\n{messages_for_agent[-1].content}"

            fallback_msg = AIMessage(content=f"（思考プロセスの署名検証により対話を中断しましたが、以下の処理は実行されました。）{tool_result_text}")
            
            return {
                "messages": [fallback_msg], 
                "loop_count": loop_count, 
                "force_end": True
            }
        else:
            print(f"--- [警告] agent_nodeでAPIエラーを捕捉しました: {e} ---")
            raise e
    # ▲▲▲ ここまで ▲▲▲
    
def safe_tool_executor(state: AgentState):
    """
    AIのツール呼び出しを仲介し、計画されたファイル編集タスクを実行する。
    """
    import signature_manager
    
    print("--- ツール実行ノード (safe_tool_executor) 実行 ---")
    last_message = state['messages'][-1]
    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        return {}

    tool_call = last_message.tool_calls[0]
    tool_name = tool_call["name"]
    tool_args = tool_call["args"]

    # --- [Dual-State] 最新の署名を取得 ---
    current_signature = signature_manager.get_thought_signature(state['room_name'])
    # -----------------------------------

    skip_execution = state.get("skip_tool_execution", False)
    if skip_execution and tool_name in side_effect_tools:
        print(f"  - [リトライ検知] 副作用のあるツール '{tool_name}' の再実行をスキップします。")
        output = "【リトライ成功】このツールは直前の試行で既に正常に実行されています。その結果についてユーザーに報告してください。"
        tool_msg = ToolMessage(content=output, tool_call_id=tool_call["id"], name=tool_name)
        
        # 署名注入
        if current_signature:
            tool_msg.artifact = {"thought_signature": current_signature}
            
        return {"messages": [tool_msg]}

    room_name = state.get('room_name')
    api_key = state.get('api_key')

    is_plan_main_memory = tool_name == "plan_main_memory_edit"
    is_plan_secret_diary = tool_name == "plan_secret_diary_edit"
    is_plan_notepad = tool_name == "plan_notepad_edit"
    is_plan_world = tool_name == "plan_world_edit"

    output = ""

    if is_plan_main_memory or is_plan_secret_diary or is_plan_notepad or is_plan_world:
        try:
            print(f"  - ファイル編集プロセスを開始: {tool_name}")
            
            # バックアップ作成
            if is_plan_main_memory: room_manager.create_backup(room_name, 'memory')
            elif is_plan_secret_diary: room_manager.create_backup(room_name, 'secret_diary')
            elif is_plan_notepad: room_manager.create_backup(room_name, 'notepad')
            elif is_plan_world: room_manager.create_backup(room_name, 'world_setting')

            read_tool = None
            if is_plan_main_memory: read_tool = read_main_memory
            elif is_plan_secret_diary: read_tool = read_secret_diary
            elif is_plan_notepad: read_tool = read_full_notepad
            elif is_plan_world: read_tool = read_world_settings

            raw_content = read_tool.invoke({"room_name": room_name})

            if is_plan_main_memory or is_plan_secret_diary or is_plan_notepad:
                lines = raw_content.split('\n')
                numbered_lines = [f"{i+1}: {line}" for i, line in enumerate(lines)]
                current_content = "\n".join(numbered_lines)
            else:
                current_content = raw_content

            print(f"  - ペルソナAI ({state['model_name']}) に編集タスクを依頼します。")
            llm_persona = LLMFactory.create_chat_model(
                model_name=state['model_name'],
                api_key=state['api_key'],
                generation_config=state['generation_config']
            )
 
            # テンプレート定義（省略せず記述）
            instruction_templates = {
                "plan_main_memory_edit": (
                    "【最重要指示：これは『対話』ではなく『記憶の設計タスク』です】\n"
                    "あなたは今、自身の記憶ファイル(`memory_main.txt`)を更新するための『設計図』を作成しています。\n\n"
                    "このファイルは以下の厳格なセクションで構成されています。 **あなたは、他のセクションの見出しや説明文を決して変更・複製してはいけません。**\n"
                    "  - `## 永続記憶 (Permanent)`: あなたの自己定義など、永続的な情報を記述する聖域です。\n"
                    "  - `## 日記 (Diary)`: 日々の出来事や感情を時系列で記録する場所です。\n"
                    "  - `## アーカイブ要約 (Archive Summary)`: システムが古い日記の要約を保管する場所です。\n\n"
                    "【あなたのタスク】\n"
                    "あなたのタスクは、提示された【行番号付きデータ】とあなたの【変更要求】に基づき、**`## 日記` セクション内にのみ**変更を加えるための、完璧な【差分指示のリスト】を生成することです。\n\n"
                    "【行番号付きデータ（memory_main.txt全文）】\n---\n{current_content}\n---\n\n"
                    "【あなたの変更要求】\n「{modification_request}」\n\n"
                    "【絶対的な出力ルール】\n"
                    "- 思考や挨拶は含めず、【差分指示のリスト】（有効なJSON配列）のみを出力してください。\n"
                    "- 各指示は \"operation\" ('replace', 'delete', 'insert_after'), \"line\" (対象行番号), \"content\" (新しい内容) のキーを持つ辞書です。\n"
                    "- 出力は ` ```json ` と ` ``` ` で囲んでください。"
                ),
                 "plan_secret_diary_edit": (
                    "【最重要指示：これは『対話』ではなく『設計タスク』です】\n"
                    "あなたは今、自身の秘密の日記(`secret_diary.txt`)を更新するための『設計図』を作成しています。\n"
                    "このファイルは自由な書式のテキストファイルです。提示された【行番号付きデータ】とあなたの【変更要求】に基づき、完璧な【差分指示のリスト】を生成してください。\n\n"
                    "【行番号付きデータ（secret_diary.txt全文）】\n---\n{current_content}\n---\n\n"
                    "【あなたの変更要求】\n「{modification_request}」\n\n"
                    "【絶対的な出力ルール】\n"
                    "- 思考や挨拶は含めず、【差分指示のリスト】（有効なJSON配列）のみを出力してください。\n"
                    "- 各指示は \"operation\" ('replace', 'delete', 'insert_after'), \"line\" (対象行番号), \"content\" (新しい内容) のキーを持つ辞書です。\n\n"
                    "- **【操作方法】**\n"
                    "  - **`delete` (削除):** 指定した`line`番号の行を削除します。`content`は不要です。\n"
                    "  - **`replace` (置換):** 指定した`line`番号の行を、新しい`content`に置き換えます。\n"
                    "  - **`insert_after` (挿入):** 指定した`line`番号の**直後**に、新しい行として`content`を挿入します。\n"
                    "  - **複数行の操作:** 複数行をまとめて削除・置換する場合は、**各行に対して**個別の指示を生成してください。\n\n"
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
                    "【最重要指示：これは『対話』ではなく『設計タスク』です】\n"
                    "あなたは今、自身の短期記憶であるメモ帳(`notepad.md`)を更新するための『設計図』を作成しています。\n"
                    "このファイルは自由な書式のテキストファイルです。提示された【行番号付きデータ】とあなたの【変更要求】に基づき、完璧な【差分指示のリスト】を生成してください。\n\n"
                    "【行番号付きデータ（notepad.md全文）】\n---\n{current_content}\n---\n\n"
                    "【あなたの変更要求】\n「{modification_request}」\n\n"
                    "【絶対的な出力ルール】\n"
                    "- 思考や挨拶は含めず、【差分指示のリスト】（有効なJSON配列）のみを出力してください。\n"
                    "- 各指示は \"operation\" ('replace', 'delete', 'insert_after'), \"line\" (対象行番号), \"content\" (新しい内容) のキーを持つ辞書です。\n\n"
                    "- **タイムスタンプ `[YYYY-MM-DD HH:MM]` はシステムが自動で付与するため、あなたは`content`に含める必要はありません。**\n\n"
                    "- **【操作方法】**\n"
                    "  - **`delete` (削除):** 指定した`line`番号の行を削除します。`content`は不要です。\n"
                    "  - **`replace` (置換):** 指定した`line`番号の行を、新しい`content`に置き換えます。\n"
                    "  - **`insert_after` (挿入):** 指定した`line`番号の**直後**に、新しい行として`content`を挿入します。\n"
                    "  - **複数行の操作:** 複数行をまとめて削除・置換する場合は、**各行に対して**個別の指示を生成してください。\n\n"
                    "- 出力は ` ```json ` と ` ``` ` で囲んでください。"
                )
            }
            formatted_instruction = instruction_templates[tool_name].format(
                current_content=current_content,
                modification_request=tool_args.get('modification_request')
            )
            edit_instruction_message = HumanMessage(content=formatted_instruction)

            history_for_editing = [msg for msg in state['messages'] if msg is not last_message]
            final_context_for_editing = [state['system_prompt']] + history_for_editing + [edit_instruction_message]

            if state.get("debug_mode", False):
                pass # デバッグ出力省略

            edited_content_document = None
            max_retries = 5
            base_delay = 5
            for attempt in range(max_retries):
                try:
                    response = llm_persona.invoke(final_context_for_editing)
                    edited_content_document = response.content.strip()
                    break
                except google_exceptions.ResourceExhausted as e:
                    error_str = str(e)
                    if "PerDay" in error_str or "Daily" in error_str:
                        raise RuntimeError("回復不能なAPIレート上限（日間など）に達したため、処理を中断しました。") from e
                    wait_time = base_delay * (2 ** attempt)
                    match = re.search(r"retry_delay {\s*seconds: (\d+)\s*}", error_str)
                    if match: wait_time = int(match.group(1)) + 1
                    if attempt < max_retries - 1:
                        time.sleep(wait_time)
                    else: raise e
                except (google_exceptions.ServiceUnavailable, google_exceptions.InternalServerError) as e:
                    if attempt < max_retries - 1:
                        wait_time = base_delay * (2 ** attempt)
                        time.sleep(wait_time)
                    else: raise e

            if edited_content_document is None:
                raise RuntimeError("編集AIからの応答が、リトライ後も得られませんでした。")

            print("  - AIからの応答を受け、ファイル書き込みを実行します。")

            if is_plan_main_memory or is_plan_secret_diary or is_plan_world or is_plan_notepad:
                json_match = re.search(r'```json\s*([\s\S]*?)\s*```', edited_content_document, re.DOTALL)
                content_to_process = json_match.group(1).strip() if json_match else edited_content_document
                instructions = json.loads(content_to_process)

                if is_plan_main_memory:
                    output = _apply_main_memory_edits(instructions=instructions, room_name=room_name)
                elif is_plan_secret_diary:
                    output = _apply_secret_diary_edits(instructions=instructions, room_name=room_name)
                elif is_plan_notepad:
                    output = _apply_notepad_edits(instructions=instructions, room_name=room_name)
                else: # is_plan_world
                    output = _apply_world_edits(instructions=instructions, room_name=room_name)

            if "成功" in output:
                output += " **このファイル編集タスクは完了しました。**あなたが先ほどのターンで計画した操作は、システムによって正常に実行されました。その結果についてユーザーに報告してください。"

        except Exception as e:
            output = f"ファイル編集プロセス中にエラーが発生しました ('{tool_name}'): {e}"
            traceback.print_exc()
    else:
        print(f"  - 通常ツール実行: {tool_name}")
        tool_args_for_log = tool_args.copy()
        if 'api_key' in tool_args_for_log: tool_args_for_log['api_key'] = '<REDACTED>'
        tool_args['room_name'] = room_name
        if tool_name in ['generate_image', 'search_past_conversations']:
            tool_args['api_key'] = api_key
            api_key_name = None
            try:
                for k, v in config_manager.GEMINI_API_KEYS.items():
                    if v == api_key:
                        api_key_name = k
                        break
            except Exception: api_key_name = None
            tool_args['api_key_name'] = api_key_name

        selected_tool = next((t for t in all_tools if t.name == tool_name), None)
        if not selected_tool: output = f"Error: Tool '{tool_name}' not found."
        else:
            try: output = selected_tool.invoke(tool_args)
            except Exception as e:
                output = f"Error executing tool '{tool_name}': {e}"
                traceback.print_exc()

    # ▼▼▼ 追加: 実行結果をログに出力 ▼▼▼
    print(f"  - ツール実行結果: {str(output)[:200]}...") 
    # ▲▲▲ 追加ここまで ▲▲▲

    # --- [Thinkingモデル対応] ToolMessageへの署名注入 ---
    tool_msg = ToolMessage(content=str(output), tool_call_id=tool_call["id"], name=tool_name)
    
    if current_signature:
        # LangChain Google GenAI の実装によっては artifact を使う可能性がある
        tool_msg.artifact = {"thought_signature": current_signature}
        print(f"  - [Thinking] ツール実行結果に署名を付与しました。")

    return {"messages": [tool_msg], "loop_count": state.get("loop_count", 0)}

def route_after_agent(state: AgentState) -> Literal["__end__", "safe_tool_node", "agent"]:
    print("--- エージェント後ルーター (route_after_agent) 実行 ---")
    if state.get("force_end"): return "__end__"
    last_message = state["messages"][-1]
    loop_count = state.get("loop_count", 0)
    if last_message.tool_calls:
        print("  - ツール呼び出しあり。ツール実行ノードへ。")
        return "safe_tool_node"
    if loop_count < 2:
        print(f"  - ツール呼び出しなし。再思考します。(ループカウント: {loop_count})")
        return "agent"
    print(f"  - ツール呼び出しなし。最大ループ回数({loop_count})に達したため、グラフを終了します。")
    return "__end__"

workflow = StateGraph(AgentState)
workflow.add_node("context_generator", context_generator_node)
workflow.add_node("retrieval_node", retrieval_node)
workflow.add_node("agent", agent_node)
workflow.add_node("safe_tool_node", safe_tool_executor)

workflow.set_entry_point("context_generator")

workflow.add_edge("context_generator", "retrieval_node")
workflow.add_edge("retrieval_node", "agent")

workflow.add_conditional_edges("agent", route_after_agent, {"safe_tool_node": "safe_tool_node", "agent": "agent", "__end__": END})
workflow.add_edge("safe_tool_node", "agent")
app = workflow.compile()