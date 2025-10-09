import gradio as gr
import shutil
import psutil
import ast
import pandas as pd
from pandas import DataFrame
import json
import traceback
import hashlib
import os
import html
import re
import sys
import locale
import subprocess
from typing import List, Optional, Dict, Any, Tuple, Iterator
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
import gradio as gr
import datetime
from PIL import Image
import threading
import filetype
import base64
import io
import uuid
from tools.image_tools import generate_image as generate_image_tool_func
import pytz
import ijson
import time


import gemini_api, config_manager, alarm_manager, room_manager, utils, constants, chatgpt_importer
from utils import _overwrite_log_file
from tools import timer_tools, memory_tools
from agent.graph import generate_scenery_context
from room_manager import get_room_files_paths, get_world_settings_path
from memory_manager import load_memory_data_safe, save_memory_data
from world_builder import get_world_data, save_world_data

DAY_MAP_EN_TO_JA = {"mon": "月", "tue": "火", "wed": "水", "thu": "木", "fri": "金", "sat": "土", "sun": "日"}
DAY_MAP_JA_TO_EN = {v: k for k, v in DAY_MAP_EN_TO_JA.items()}


def _get_location_choices_for_ui(room_name: str) -> list:
    """
    UIの移動先Dropdown用の、エリアごとにグループ化された選択肢リストを生成する。
    """
    if not room_name: return []

    world_settings_path = get_world_settings_path(room_name)
    world_data = utils.parse_world_file(world_settings_path)

    if not world_data: return []

    choices = []
    for area_name in sorted(world_data.keys()):
        choices.append((f"[{area_name}]", f"__AREA_HEADER_{area_name}"))

        places = world_data[area_name]
        for place_name in sorted(places.keys()):
            if place_name.startswith("__"): continue
            choices.append((f"\u00A0\u00A0→ {place_name}", place_name))

    return choices

def _create_redaction_df_from_rules(rules: List[Dict]) -> pd.DataFrame:
    """
    ルールの辞書リストから、UI表示用のDataFrameを作成するヘルパー関数。
    この関数で、キーと列名のマッピングを完結させる。
    """
    if not rules:
        return pd.DataFrame(columns=["元の文字列 (Find)", "置換後の文字列 (Replace)"])
    df_data = [{"元の文字列 (Find)": r.get("find", ""), "置換後の文字列 (Replace)": r.get("replace", "")} for r in rules]
    return pd.DataFrame(df_data)

def _update_chat_tab_for_room_change(room_name: str, api_key_name: str):
    """
    【v3】チャットタブと、それに付随する設定UIの更新のみを担当するヘルパー関数。
    戻り値の数は `initial_load_chat_outputs` の36個と一致する。
    """
    if not room_name:
        room_list = room_manager.get_room_list_for_ui()
        room_name = room_list[0][1] if room_list else "Default"

    effective_settings = config_manager.get_effective_settings(room_name)
    chat_history, mapping_list = reload_chat_log(
        room_name=room_name,
        api_history_limit_value=config_manager.initial_api_history_limit_option_global,
        add_timestamp=effective_settings.get("add_timestamp", False)
    )
    _, _, img_p, mem_p, notepad_p = get_room_files_paths(room_name)
    memory_str = ""
    if mem_p and os.path.exists(mem_p):
        with open(mem_p, "r", encoding="utf-8") as f:
            memory_str = f.read()
    profile_image = img_p if img_p and os.path.exists(img_p) else None
    notepad_content = load_notepad_content(room_name)
    api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)
    locations_for_ui = _get_location_choices_for_ui(room_name)
    valid_location_ids = [value for _name, value in locations_for_ui]
    current_location_from_file = utils.get_current_location(room_name)
    location_dd_val = current_location_from_file
    if current_location_from_file and current_location_from_file not in valid_location_ids:
        gr.Warning(f"最後にいた場所「{current_location_from_file}」が見つかりません。移動先を選択し直してください。")
        location_dd_val = None
    season_en, time_of_day_en = _get_current_time_context(room_name)
    _, _, scenery_text = generate_scenery_context(
        room_name, api_key,
        season_en=season_en, time_of_day_en=time_of_day_en
    )
    scenery_image_path = utils.find_scenery_image(
        room_name, location_dd_val,
        season_en=season_en, time_of_day_en=time_of_day_en
    )
    voice_display_name = config_manager.SUPPORTED_VOICES.get(effective_settings.get("voice_id", "iapetus"), list(config_manager.SUPPORTED_VOICES.values())[0])
    voice_style_prompt_val = effective_settings.get("voice_style_prompt", "")
    safety_display_map = {
        "BLOCK_NONE": "ブロックしない", "BLOCK_LOW_AND_ABOVE": "低リスク以上をブロック",
        "BLOCK_MEDIUM_AND_ABOVE": "中リスク以上をブロック", "BLOCK_ONLY_HIGH": "高リスクのみブロック"
    }
    temp_val = effective_settings.get("temperature", 0.8)
    top_p_val = effective_settings.get("top_p", 0.95)
    harassment_val = safety_display_map.get(effective_settings.get("safety_block_threshold_harassment"))
    hate_val = safety_display_map.get(effective_settings.get("safety_block_threshold_hate_speech"))
    sexual_val = safety_display_map.get(effective_settings.get("safety_block_threshold_sexually_explicit"))
    dangerous_val = safety_display_map.get(effective_settings.get("safety_block_threshold_dangerous_content"))

    core_memory_content = load_core_memory_content(room_name)

    # このタプルの要素数は36個になる
    return (
        room_name, chat_history, mapping_list,
        gr.update(value={'text': '', 'files': []}),
        profile_image,
        memory_str, notepad_content, load_system_prompt_content(room_name),
        core_memory_content,
        gr.update(choices=room_manager.get_room_list_for_ui(), value=room_name), # room_dropdown
        gr.update(choices=room_manager.get_room_list_for_ui(), value=room_name), # alarm_room_dropdown
        gr.update(choices=room_manager.get_room_list_for_ui(), value=room_name), # timer_room_dropdown
        gr.update(choices=room_manager.get_room_list_for_ui(), value=room_name), # manage_room_selector
        gr.update(choices=locations_for_ui, value=location_dd_val), # location_dropdown
        scenery_text,
        voice_display_name, voice_style_prompt_val,
        effective_settings["enable_typewriter_effect"],
        effective_settings["streaming_speed"],
        temp_val, top_p_val, harassment_val, hate_val, sexual_val, dangerous_val,
        effective_settings["add_timestamp"], effective_settings["send_thoughts"],
        effective_settings["send_notepad"], effective_settings["use_common_prompt"],
        effective_settings["send_core_memory"],
        effective_settings["send_scenery"], # room_send_scenery_checkbox の値
        effective_settings["auto_memory_enabled"],
        f"ℹ️ *現在選択中のルーム「{room_name}」にのみ適用される設定です。*",
        scenery_image_path,
        # --- 新しい戻り値 ---
        effective_settings.get("enable_scenery_system", True), # enable_scenery_system_checkbox の値
        gr.update(visible=effective_settings.get("enable_scenery_system", True)) # profile_scenery_accordion の表示状態
    )

def _update_all_tabs_for_room_change(room_name: str, api_key_name: str):
    """
    【v4】ルーム切り替え時に、全ての関連タブのUIを更新する。
    戻り値の数は `all_room_change_outputs` の48個と一致する。
    """
    # chat_tab_updatesは36個の更新値を持つ
    chat_tab_updates = _update_chat_tab_for_room_change(room_name, api_key_name)

    wb_state, wb_area_selector, wb_raw_editor = handle_world_builder_load(room_name)
    world_builder_updates = (wb_state, wb_area_selector, wb_raw_editor)

    all_rooms = room_manager.get_room_list_for_ui()
    other_rooms_for_checkbox = sorted(
        [(display, folder) for display, folder in all_rooms if folder != room_name]
    )
    participant_checkbox_update = gr.update(choices=other_rooms_for_checkbox, value=[])
    session_management_updates = ([], "現在、1対1の会話モードです。", participant_checkbox_update)

    rules = config_manager.load_redaction_rules()
    rules_df_for_ui = _create_redaction_df_from_rules(rules)

    archive_dates = _get_date_choices_from_memory(room_name)
    archive_date_dropdown_update = gr.update(choices=archive_dates, value=archive_dates[0] if archive_dates else None)

    time_settings = _load_time_settings_for_room(room_name)
    time_settings_updates = (
        gr.update(value=time_settings.get("mode", "リアル連動")),
        gr.update(value=time_settings.get("fixed_season_ja", "秋")),
        gr.update(value=time_settings.get("fixed_time_of_day_ja", "夜")),
        gr.update(visible=(time_settings.get("mode", "リアル連動") == "選択する"))
    )

    # 戻り値の総数: 36 + 3 + 3 + 2 + 4 = 48個
    return (
        chat_tab_updates +
        world_builder_updates +
        session_management_updates +
        (rules_df_for_ui, archive_date_dropdown_update) +
        time_settings_updates
    )


def handle_initial_load(initial_room_to_load: str, initial_api_key_name: str):
    """
    【v3】UIの初期化処理。戻り値の数は `initial_load_outputs` の47個と一致する。
    """
    print("--- UI初期化処理(handle_initial_load)を開始します ---")
    df_with_ids = render_alarms_as_dataframe()
    display_df, feedback_text = get_display_df(df_with_ids), "アラームを選択してください"

    # chat_tab_updatesは36個の更新値を持つ
    chat_tab_updates = _update_chat_tab_for_room_change(initial_room_to_load, initial_api_key_name)

    rules = config_manager.load_redaction_rules()
    rules_df_for_ui = _create_redaction_df_from_rules(rules)

    token_calc_kwargs = config_manager.get_effective_settings(initial_room_to_load)
    token_count_text = gemini_api.count_input_tokens(
        room_name=initial_room_to_load, api_key_name=initial_api_key_name,
        api_history_limit=config_manager.initial_api_history_limit_option_global,
        parts=[], **token_calc_kwargs
    )

    api_key_choices = list(config_manager.GEMINI_API_KEYS.keys())
    api_key_dd_update = gr.update(choices=api_key_choices, value=initial_api_key_name)

    world_data_for_state = get_world_data(initial_room_to_load)

    # 時間設定UIのための値を取得
    time_settings = _load_time_settings_for_room(initial_room_to_load)
    time_settings_updates = (
        gr.update(value=time_settings.get("mode", "リアル連動")),
        gr.update(value=time_settings.get("fixed_season_ja", "秋")),
        gr.update(value=time_settings.get("fixed_time_of_day_ja", "夜")),
        gr.update(visible=(time_settings.get("mode", "リアル連動") == "選択する"))
    )

    # 戻り値の総数: 3 + 36 + 3 + 1 + 4 = 47個
    return (
        (display_df, df_with_ids, feedback_text) +
        chat_tab_updates +
        (rules_df_for_ui, token_count_text, api_key_dd_update) +
        (world_data_for_state,) +
        time_settings_updates
    )

def handle_save_room_settings(
    room_name: str, voice_name: str, voice_style_prompt: str,
    temp: float, top_p: float, harassment: str, hate: str, sexual: str, dangerous: str,
    enable_typewriter_effect: bool,
    streaming_speed: float,
    add_timestamp: bool, send_thoughts: bool, send_notepad: bool,
    use_common_prompt: bool, send_core_memory: bool,
    enable_scenery_system: bool, # room_send_scenery_checkbox から変更
    auto_memory_enabled: bool
):
    if not room_name: gr.Warning("設定を保存するルームが選択されていません。"); return

    safety_value_map = {
        "ブロックしない": "BLOCK_NONE",
        "低リスク以上をブロック": "BLOCK_LOW_AND_ABOVE",
        "中リスク以上をブロック": "BLOCK_MEDIUM_AND_ABOVE",
        "高リスクのみブロック": "BLOCK_ONLY_HIGH"
    }

    new_settings = {
        "voice_id": next((k for k, v in config_manager.SUPPORTED_VOICES.items() if v == voice_name), None),
        "voice_style_prompt": voice_style_prompt.strip(),
        "temperature": temp,
        "top_p": top_p,
        "safety_block_threshold_harassment": safety_value_map.get(harassment),
        "safety_block_threshold_hate_speech": safety_value_map.get(hate),
        "safety_block_threshold_sexually_explicit": safety_value_map.get(sexual),
        "safety_block_threshold_dangerous_content": safety_value_map.get(dangerous),
        "enable_typewriter_effect": bool(enable_typewriter_effect),
        "streaming_speed": float(streaming_speed),
        "add_timestamp": bool(add_timestamp),
        "send_thoughts": bool(send_thoughts),
        "send_notepad": bool(send_notepad),
        "use_common_prompt": bool(use_common_prompt),
        "send_core_memory": bool(send_core_memory),
        # ここで2つの設定を連動させる
        "enable_scenery_system": bool(enable_scenery_system),
        "send_scenery": bool(enable_scenery_system),
        "auto_memory_enabled": bool(auto_memory_enabled),
    }
    try:
        room_config_path = os.path.join(constants.ROOMS_DIR, room_name, "room_config.json")
        config = {}
        if os.path.exists(room_config_path):
             if os.path.getsize(room_config_path) > 0:
                with open(room_config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
        else:
            gr.Warning(f"設定ファイルが見つからなかったため、新しく作成します: {room_config_path}")
            config = {
                "version": 1, "room_name": room_name, "user_display_name": "ユーザー",
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "description": "自動生成された設定ファイルです"
            }

        if "override_settings" not in config: config["override_settings"] = {}
        config["override_settings"].update(new_settings)
        config["last_updated"] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(room_config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        gr.Info(f"「{room_name}」の個別設定を保存しました。")
    except Exception as e: gr.Error(f"個別設定の保存中にエラーが発生しました: {e}"); traceback.print_exc()

def handle_context_settings_change(room_name: str, api_key_name: str, api_history_limit: str, add_timestamp: bool, send_thoughts: bool, send_notepad: bool, use_common_prompt: bool, send_core_memory: bool, enable_scenery_system: bool, *args, **kwargs):
    if not room_name or not api_key_name: return "入力トークン数: -"
    return gemini_api.count_input_tokens(
        room_name=room_name, api_key_name=api_key_name, parts=[],
        api_history_limit=api_history_limit,
        add_timestamp=add_timestamp, send_thoughts=send_thoughts, send_notepad=send_notepad,
        use_common_prompt=use_common_prompt, send_core_memory=send_core_memory,
        send_scenery=enable_scenery_system # ここで連動させる
    )

def _get_updated_scenery_and_image(room_name: str, api_key_name: str, force_text_regenerate: bool = False) -> Tuple[str, Optional[str]]:
    """
    【v7: 機能OFF対応】
    ...
    """
    # --- 新しいガード節 ---
    effective_settings = config_manager.get_effective_settings(room_name)
    if not effective_settings.get("enable_scenery_system", True):
        return "（情景描写システムは、このルームでは無効です）", None
    # --- ここまで ---

    if not room_name or not api_key_name:
        return "（ルームまたはAPIキーが未選択です）", None

    api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)
    if not api_key:
        gr.Warning(f"APIキー '{api_key_name}' が見つかりません。")
        return "（APIキーエラー）", None

    current_location = utils.get_current_location(room_name)
    if not current_location:
        return "（現在地が設定されていません）", None

    # 1. 時間の源から、適用すべき時間コンテキストを取得
    season_en, time_of_day_en = _get_current_time_context(room_name)

    # 2. 情景テキストを生成（またはキャッシュから取得）
    _, _, scenery_text = generate_scenery_context(
        room_name, api_key,
        force_regenerate=force_text_regenerate,
        season_en=season_en, time_of_day_en=time_of_day_en
    )

    # 3. 対応する情景画像を検索
    scenery_image_path = utils.find_scenery_image(
        room_name, current_location, season_en, time_of_day_en
    )

    # 4. 【キャッシュ・ミス時の自動生成】画像が見つからなかった場合
    if scenery_image_path is None:
        gr.Info(f"情景画像キャッシュが見つかりません。新しい画像を自動生成します... (場所: {current_location}, 時期: {season_en}/{time_of_day_en})")
        # handle_generate_or_regenerate_scenery_image はPIL Imageを返すため、
        # ここでは直接呼び出さず、その中の画像生成部分のロジックを再利用する。
        # 今後のリファクタリングで、画像生成部分だけを切り出すのが望ましい。
        try:
            # handle_generate_or_regenerate_scenery_imageを呼び出し、PIL Imageオブジェクトを受け取る
            pil_image = handle_generate_or_regenerate_scenery_image(
                room_name=room_name,
                api_key_name=api_key_name,
                style_choice="写真風 (デフォルト)" # 自動生成時はデフォルトスタイルを使用
            )
            if pil_image:
                # 戻り値はPIL Imageなので、再度パスを検索する必要がある
                scenery_image_path = utils.find_scenery_image(
                    room_name, current_location, season_en, time_of_day_en
                )
            else:
                 gr.Warning("情景画像の自動生成に失敗しました。")
        except Exception as e:
            gr.Error(f"情景画像の自動生成中にエラーが発生しました: {e}")
            traceback.print_exc()


    return scenery_text, scenery_image_path

# ... (rest of file is unchanged, but for completeness) ...
def handle_scenery_refresh(room_name: str, api_key_name: str) -> Tuple[gr.update, str, Optional[str]]:
    """「情景テキストを更新」ボタンのハンドラ。新しい司令塔を呼び出す。"""
    gr.Info(f"「{room_name}」の現在の情景を再生成しています...")
    # 新しい司令塔を呼び出し、テキストの強制再生成フラグを立てる
    new_scenery_text, new_image_path = _get_updated_scenery_and_image(
        room_name, api_key_name, force_text_regenerate=True
    )
    latest_location_id = utils.get_current_location(room_name)
    return gr.update(value=latest_location_id), new_scenery_text, new_image_path

def handle_location_change(room_name: str, selected_value: str, api_key_name: str) -> Tuple[gr.update, str, Optional[str]]:
    """場所が変更されたときのハンドラ。移動処理後、新しい司令塔を呼び出す。"""
    if not selected_value or selected_value.startswith("__AREA_HEADER_"):
        # ドロップダウンのヘッダーがクリックされた場合は何もしない
        latest_location_id = utils.get_current_location(room_name)
        new_scenery_text, new_image_path = _get_updated_scenery_and_image(room_name, api_key_name)
        return gr.update(value=latest_location_id), new_scenery_text, new_image_path

    location_id = selected_value
    print(f"--- UIからの場所変更処理開始: ルーム='{room_name}', 移動先ID='{location_id}' ---")

    from tools.space_tools import set_current_location
    result = set_current_location.func(location_id=location_id, room_name=room_name)
    if "Success" not in result:
        gr.Error(f"場所の変更に失敗しました: {result}")
        latest_location_id = utils.get_current_location(room_name)
        # 失敗した場合でも、現在の場所の情景を司令塔から取得してUIを更新する
        new_scenery_text, new_image_path = _get_updated_scenery_and_image(room_name, api_key_name)
        return gr.update(value=latest_location_id), new_scenery_text, new_image_path

    gr.Info(f"場所を「{location_id}」に移動しました。情景を更新します...")

    # 移動成功後、新しい司令塔を呼び出して情景を更新
    new_scenery_text, new_image_path = _get_updated_scenery_and_image(room_name, api_key_name)

    return gr.update(value=location_id), new_scenery_text, new_image_path

def handle_enable_scenery_system_change(is_enabled: bool) -> Tuple[gr.update, gr.update]:
    """
    【v7】情景描写システムの有効/無効スイッチが変更されたときのイベントハンドラ。
    """
    return (
        gr.update(visible=is_enabled), # 「プロフィール・情景」アコーディオンの表示/非表示
        gr.update(value=is_enabled)    # 「空間描写を送信」チェックボックスの値を連動
    )