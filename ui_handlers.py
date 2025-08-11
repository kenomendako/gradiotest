import shutil
import pandas as pd
import json
import traceback
import hashlib
import os
import re
from typing import List, Optional, Dict, Any, Tuple
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


import gemini_api, config_manager, alarm_manager, character_manager, utils, constants
# ▼▼▼ 新しいタイマーツールをインポート ▼▼▼
from tools import timer_tools
from agent.graph import generate_scenery_context
# from timers import UnifiedTimer # UnifiedTimerは直接使わなくなるので削除
from character_manager import get_character_files_paths, get_world_settings_path
from memory_manager import load_memory_data_safe, save_memory_data
from world_builder import get_world_data, save_world_data

DAY_MAP_EN_TO_JA = {"mon": "月", "tue": "火", "wed": "水", "thu": "木", "fri": "金", "sat": "土", "sun": "日"}
DAY_MAP_JA_TO_EN = {v: k for k, v in DAY_MAP_EN_TO_JA.items()}


def _get_location_choices_for_ui(character_name: str) -> list:
    """
    UIの移動先Dropdown用の、エリアごとにグループ化された選択肢リストを生成する。
    """
    if not character_name: return []

    world_settings_path = get_world_settings_path(character_name)
    world_data = utils.parse_world_file(world_settings_path)

    if not world_data: return []

    choices = []
    for area_name in sorted(world_data.keys()):
        # エリア見出しを追加 (選択不可にするため値は専用ID)
        choices.append((f"[{area_name}]", f"__AREA_HEADER_{area_name}"))

        places = world_data[area_name]
        for place_name in sorted(places.keys()):
            if place_name.startswith("__"): continue
            # シンプルな右矢印記号に変更
            choices.append((f"\u00A0\u00A0→ {place_name}", place_name))

    return choices

def handle_initial_load():
    print("--- UI初期化処理(handle_initial_load)を開始します ---")
    df_with_ids = render_alarms_as_dataframe()
    display_df, feedback_text = get_display_df(df_with_ids), "アラームを選択してください"
    char_dependent_outputs = handle_character_change(config_manager.initial_character_global, config_manager.initial_api_key_name_global)
    return (display_df, df_with_ids, feedback_text) + char_dependent_outputs

def handle_character_change(character_name: str, api_key_name: str):
    if not character_name:
        char_list = character_manager.get_character_list()
        character_name = char_list[0] if char_list else "Default"

    print(f"--- UI更新司令塔(handle_character_change)実行: {character_name} ---")
    config_manager.save_config("last_character", character_name)

    chat_history, mapping_list = reload_chat_log(character_name, config_manager.initial_api_history_limit_option_global)

    _, _, img_p, mem_p, notepad_p = get_character_files_paths(character_name)

    memory_str = json.dumps(load_memory_data_safe(mem_p), indent=2, ensure_ascii=False)
    profile_image = img_p if img_p and os.path.exists(img_p) else None
    notepad_content = load_notepad_content(character_name)
    api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)

    # ▼▼▼ ここからが修正の核心 ▼▼▼
    # まず、UIに表示するための移動先リストを生成する
    locations_for_ui = _get_location_choices_for_ui(character_name)
    valid_location_ids = [value for _name, value in locations_for_ui]

    # 次に、ファイルに保存されている現在地を取得
    current_location_from_file = utils.get_current_location(character_name)
    location_dd_val = current_location_from_file

    # 安全装置：保存されていた場所が、現在の有効な場所リストに存在するかチェック
    if current_location_from_file and current_location_from_file not in valid_location_ids:
        gr.Warning(f"最後にいた場所「{current_location_from_file}」が見つかりません。移動先を選択し直してください。")
        # ドロップダウンの選択を一旦リセット
        location_dd_val = None

    # 情景描写と画像は、UIに設定する有効な場所IDに基づいて取得する
    current_location_name, _, scenery_text = generate_scenery_context(character_name, api_key)
    scenery_image_path = utils.find_scenery_image(character_name, location_dd_val)
    # ▲▲▲ 修正ここまで ▲▲▲

    effective_settings = config_manager.get_effective_settings(character_name)
    all_models = ["デフォルト"] + config_manager.AVAILABLE_MODELS_GLOBAL
    model_val = effective_settings["model_name"] if effective_settings["model_name"] != config_manager.initial_model_global else "デフォルト"
    voice_display_name = config_manager.SUPPORTED_VOICES.get(effective_settings.get("voice_id", "vindemiatrix"), list(config_manager.SUPPORTED_VOICES.values())[0])
    voice_style_prompt_val = effective_settings.get("voice_style_prompt", "")

    # handle_character_change 関数の最後にある return 文を以下に置き換える
    return (
        character_name, chat_history, mapping_list, "", profile_image,
        # ↓↓↓ 3つのエディタに初期値を設定する部分 ↓↓↓
        memory_str, notepad_content, load_system_prompt_content(character_name),
        character_name, character_name,
        gr.update(choices=locations_for_ui, value=location_dd_val),
        current_location_name, scenery_text,
        gr.update(choices=all_models, value=model_val),
        voice_display_name, voice_style_prompt_val,
        effective_settings["add_timestamp"], effective_settings["send_thoughts"],
        effective_settings["send_notepad"], effective_settings["use_common_prompt"],
        effective_settings["send_core_memory"], effective_settings["send_scenery"],
        f"ℹ️ *現在選択中のキャラクター「{character_name}」にのみ適用される設定です。*", scenery_image_path
    )

def handle_save_char_settings(character_name: str, model_name: str, voice_name: str, voice_style_prompt: str, add_timestamp: bool, send_thoughts: bool, send_notepad: bool, use_common_prompt: bool, send_core_memory: bool, send_scenery: bool):
    if not character_name: gr.Warning("設定を保存するキャラクターが選択されていません。"); return
    new_settings = {
        "model_name": model_name if model_name != "デフォルト" else None,
        "voice_id": next((k for k, v in config_manager.SUPPORTED_VOICES.items() if v == voice_name), None),
        "voice_style_prompt": voice_style_prompt.strip(),
        "add_timestamp": bool(add_timestamp), "send_thoughts": bool(send_thoughts), "send_notepad": bool(send_notepad),
        "use_common_prompt": bool(use_common_prompt), "send_core_memory": bool(send_core_memory), "send_scenery": bool(send_scenery),
    }
    try:
        char_config_path = os.path.join(constants.CHARACTERS_DIR, character_name, "character_config.json")
        config = {}
        if os.path.exists(char_config_path) and os.path.getsize(char_config_path) > 0:
            with open(char_config_path, "r", encoding="utf-8") as f: config = json.load(f)
        if "override_settings" not in config: config["override_settings"] = {}
        config["override_settings"].update(new_settings)
        config["last_updated"] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(char_config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        gr.Info(f"「{character_name}」の個別設定を保存しました。")
    except Exception as e: gr.Error(f"個別設定の保存中にエラーが発生しました: {e}"); traceback.print_exc()

def handle_context_settings_change(character_name: str, api_key_name: str, api_history_limit: str, add_timestamp: bool, send_thoughts: bool, send_notepad: bool, use_common_prompt: bool, send_core_memory: bool, send_scenery: bool):
    if not character_name or not api_key_name: return "入力トークン数: -"
    return gemini_api.count_input_tokens(
        character_name=character_name, api_key_name=api_key_name, parts=[],
        api_history_limit=api_history_limit,
        add_timestamp=add_timestamp, send_thoughts=send_thoughts, send_notepad=send_notepad,
        use_common_prompt=use_common_prompt, send_core_memory=send_core_memory, send_scenery=send_scenery
    )

def update_token_count_on_input(character_name: str, api_key_name: str, api_history_limit: str, textbox_content: str, file_list: list, add_timestamp: bool, send_thoughts: bool, send_notepad: bool, use_common_prompt: bool, send_core_memory: bool, send_scenery: bool):
    if not character_name or not api_key_name: return "入力トークン数: -"
    parts_for_api = []
    if textbox_content: parts_for_api.append(textbox_content)
    if file_list:
        for file_obj in file_list: parts_for_api.append(Image.open(file_obj.name))
    return gemini_api.count_input_tokens(
        character_name=character_name, api_key_name=api_key_name, parts=parts_for_api,
        api_history_limit=api_history_limit,
        add_timestamp=add_timestamp, send_thoughts=send_thoughts, send_notepad=send_notepad,
        use_common_prompt=use_common_prompt, send_core_memory=send_core_memory, send_scenery=send_scenery
    )

def handle_message_submission(*args: Any):
    (textbox_content, current_character_name, current_api_key_name_state,
     file_input_list, api_history_limit_state, debug_mode_state) = args
    user_prompt_from_textbox = textbox_content.strip() if textbox_content else ""
    if not user_prompt_from_textbox and not file_input_list:
        chatbot_history, mapping_list = reload_chat_log(current_character_name, api_history_limit_state)
        # 戻り値の数を10個に揃える
        return chatbot_history, mapping_list, gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update()

    effective_settings = config_manager.get_effective_settings(current_character_name)
    add_timestamp_checkbox = effective_settings.get("add_timestamp", False)

    chatbot_history, _ = reload_chat_log(current_character_name, api_history_limit_state)

    log_message_parts = []
    if user_prompt_from_textbox:
        timestamp = f"\n\n{datetime.datetime.now().strftime('%Y-%m-%d (%a) %H:%M:%S')}" if add_timestamp_checkbox else ""
        processed_user_message = user_prompt_from_textbox + timestamp
        chatbot_history.append((processed_user_message, None))
        log_message_parts.append(processed_user_message)
    if file_input_list:
        for file_obj in file_input_list:
            filepath, filename = file_obj.name, os.path.basename(file_obj.name)
            chatbot_history.append(((filepath, filename), None))
            log_message_parts.append(f"[ファイル添付: {filepath}]")

    chatbot_history.append((None, "思考中... ▌"))

    # ▼▼▼ 修正箇所1: yieldで返す値の数を10個にする ▼▼▼
    yield (chatbot_history, [], gr.update(value=""), gr.update(value=None), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update())

    response_data = {}
    try:
        agent_args = (
            textbox_content, current_character_name, current_api_key_name_state,
            file_input_list, api_history_limit_state, debug_mode_state
        )
        response_data = gemini_api.invoke_nexus_agent(*agent_args)
    except Exception as e:
        traceback.print_exc()
        response_data = {"response": f"[UIハンドラエラー: {e}]", "location_name": "（エラー）", "scenery": "（エラー）"}

    # ▼▼▼ ここからが修正の核心 ▼▼▼
    # 返されたデータからツールの使用履歴を取得し、アラートとして表示
    tools_used = response_data.get("tools_used", [])
    if tools_used:
        for tool_info in tools_used:
            gr.Info(tool_info)
    # ▲▲▲ 修正ここまで ▲▲▲
    final_response_text = response_data.get("response", "")
    location_name, scenery_text = response_data.get("location_name", "（取得失敗）"), response_data.get("scenery", "（取得失敗）")

    if final_response_text and final_response_text.strip():
        log_f, _, _, _, _ = get_character_files_paths(current_character_name)
        final_log_message = "\n\n".join(log_message_parts).strip()
        if final_log_message:
            user_header = utils._get_user_header_from_log(log_f, current_character_name)
            utils.save_message_to_log(log_f, user_header, final_log_message)
        utils.save_message_to_log(log_f, f"## {current_character_name}:", final_response_text)

    # 応答処理が完了した後の最終状態でUIを更新
    formatted_history, new_mapping_list = reload_chat_log(current_character_name, api_history_limit_state)
    new_alarm_df_with_ids = render_alarms_as_dataframe()
    new_display_df = get_display_df(new_alarm_df_with_ids)
    scenery_image_path = utils.find_scenery_image(current_character_name, utils.get_current_location(current_character_name))

    # ▼▼▼ 修正箇所2: トークン数を再計算して追加する ▼▼▼
    token_count_text = gemini_api.count_input_tokens(
        character_name=current_character_name,
        api_key_name=current_api_key_name_state,
        api_history_limit=api_history_limit_state,
        parts=[], # 入力ボックスは空なので空リストを渡す
        add_timestamp=effective_settings["add_timestamp"], send_thoughts=effective_settings["send_thoughts"],
        send_notepad=effective_settings["send_notepad"], use_common_prompt=effective_settings["use_common_prompt"],
        send_core_memory=effective_settings["send_core_memory"], send_scenery=effective_settings["send_scenery"]
    )
    # ▲▲▲ 修正ここまで ▲▲▲

    # ▼▼▼ 修正箇所3: 戻り値のタプルに token_count_text を含める ▼▼▼
    yield (formatted_history, new_mapping_list, gr.update(), gr.update(value=None),
           token_count_text, location_name, scenery_text, new_alarm_df_with_ids,
           new_display_df, scenery_image_path)
    # ▲▲▲ 修正ここまで ▲▲▲

def handle_scenery_refresh(character_name: str, api_key_name: str) -> Tuple[str, str, Optional[str]]:
    """「情景を更新」ボタン専用ハンドラ。キャッシュを無視して強制的に再生成する。"""
    if not character_name or not api_key_name:
        return "（キャラクターまたはAPIキーが未選択です）", "（キャラクターまたはAPIキーが未選択です）", None

    api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)
    if not api_key:
        gr.Warning(f"APIキー '{api_key_name}' が見つかりません。")
        return "（APIキーエラー）", "（APIキーエラー）", None

    gr.Info(f"「{character_name}」の現在の情景を強制的に再生成しています...")

    # ▼▼▼ 修正の核心：責務を agent/graph.py に委譲 ▼▼▼
    location_name, _, scenery_text = generate_scenery_context(character_name, api_key, force_regenerate=True)
    # ▲▲▲ 修正ここまで ▲▲▲

    if not location_name.startswith("（"):
        gr.Info("情景を再生成しました。")
        scenery_image_path = utils.find_scenery_image(character_name, utils.get_current_location(character_name))
    else:
        gr.Error("情景の再生成に失敗しました。")
        scenery_image_path = None

    return location_name, scenery_text, scenery_image_path

def handle_location_change(character_name: str, selected_value: str, api_key_name: str) -> Tuple[str, str, Optional[str]]:
    # ▼▼▼ 修正ブロックここから ▼▼▼
    if not selected_value or selected_value.startswith("__AREA_HEADER_"):
        # ヘッダーがクリックされたか、値がない場合は何もしない
        # 現在の状態をそのまま返す
        location_name, _, scenery_text = generate_scenery_context(character_name, config_manager.GEMINI_API_KEYS.get(api_key_name))
        scenery_image_path = utils.find_scenery_image(character_name, utils.get_current_location(character_name))
        return location_name, scenery_text, scenery_image_path

    location_id = selected_value
    # ▲▲▲ 修正ブロックここまで ▲▲▲

    from tools.space_tools import set_current_location
    print(f"--- UIからの場所変更処理開始: キャラクター='{character_name}', 移動先ID='{location_id}' ---")

    # 現在の表示内容を一時的に取得
    scenery_cache = utils.load_scenery_cache(character_name)
    current_loc_name = scenery_cache.get("location_name", "（場所不明）")
    scenery_text = scenery_cache.get("scenery_text", "（情景不明）")
    current_image_path = utils.find_scenery_image(character_name, utils.get_current_location(character_name))

    if not character_name or not location_id:
        gr.Warning("キャラクターと移動先の場所を選択してください。")
        return current_loc_name, scenery_text, current_image_path

    # まず場所のファイルだけを更新
    result = set_current_location.func(location_id=location_id, character_name=character_name)
    if "Success" not in result:
        gr.Error(f"場所の変更に失敗しました: {result}")
        return current_loc_name, scenery_text, current_image_path

    gr.Info(f"場所を「{location_id}」に移動しました。情景を更新します...")

    # ▼▼▼ 修正の核心 ▼▼▼
    # 移動後に、キャッシュを考慮した情景取得関数を呼び出す
    api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)
    if not api_key:
        gr.Warning(f"APIキー '{api_key_name}' が見つかりません。")
        return "（APIキーエラー）", "（APIキーエラー）", None

    new_location_name, _, new_scenery_text = generate_scenery_context(character_name, api_key)
    new_image_path = utils.find_scenery_image(character_name, location_id)
    # ▲▲▲ 修正ここまで ▲▲▲

    return new_location_name, new_scenery_text, new_image_path

def handle_add_new_character(character_name: str):
    char_list = character_manager.get_character_list()
    if not character_name or not character_name.strip():
        gr.Warning("キャラクター名が入力されていません。"); return gr.update(choices=char_list), gr.update(choices=char_list), gr.update(choices=char_list), gr.update(value="")
    safe_name = re.sub(r'[\\/*?:"<>|]', "", character_name).strip()
    if not safe_name:
        gr.Warning("無効なキャラクター名です。"); return gr.update(choices=char_list), gr.update(choices=char_list), gr.update(choices=char_list), gr.update(value="")
    if character_manager.ensure_character_files(safe_name):
        gr.Info(f"新しいキャラクター「{safe_name}」さんを迎えました！"); new_char_list = character_manager.get_character_list(); return gr.update(choices=new_char_list, value=safe_name), gr.update(choices=new_char_list, value=safe_name), gr.update(choices=new_char_list, value=safe_name), gr.update(value="")
    else:
        gr.Error(f"キャラクター「{safe_name}」の準備に失敗しました。"); return gr.update(choices=char_list), gr.update(choices=char_list), gr.update(choices=char_list), gr.update(value=character_name)

def _get_display_history_count(api_history_limit_value: str) -> int: return int(api_history_limit_value) if api_history_limit_value.isdigit() else constants.UI_HISTORY_MAX_LIMIT

def handle_chatbot_selection(character_name: str, api_history_limit_state: str, mapping_list: list, evt: gr.SelectData):
    if not character_name or evt.index is None or not mapping_list: return None, gr.update(visible=False)
    try:
        clicked_ui_index = evt.index[0]
        if not (0 <= clicked_ui_index < len(mapping_list)):
            gr.Warning(f"クリックされたメッセージを特定できませんでした (UI index {clicked_ui_index} out of bounds for mapping list size {len(mapping_list)})."); return None, gr.update(visible=False)

        log_f, _, _, _, _ = get_character_files_paths(character_name)
        raw_history = utils.load_chat_log(log_f, character_name)
        display_turns = _get_display_history_count(api_history_limit_state)
        visible_raw_history = raw_history[-(display_turns * 2):]

        original_log_index = mapping_list[clicked_ui_index]
        if 0 <= original_log_index < len(visible_raw_history):
            return visible_raw_history[original_log_index], gr.update(visible=True)
        else:
            gr.Warning(f"クリックされたメッセージを特定できませんでした (Original log index {original_log_index} out of bounds for visible history size {len(visible_raw_history)})."); return None, gr.update(visible=False)
    except Exception as e:
        print(f"チャットボット選択中のエラー: {e}"); traceback.print_exc()
        return None, gr.update(visible=False)

def handle_delete_button_click(message_to_delete: Optional[Dict[str, str]], character_name: str, api_history_limit: str):
    if not message_to_delete:
        return gr.update(), gr.update(), None, gr.update(visible=False)

    log_f, _, _, _, _ = get_character_files_paths(character_name)
    if utils.delete_message_from_log(log_f, message_to_delete, character_name):
        gr.Info("ログからメッセージを削除しました。")
    else:
        gr.Error("メッセージの削除に失敗しました。詳細はターミナルを確認してください。")

    history, mapping_list = reload_chat_log(character_name, api_history_limit)
    return history, mapping_list, None, gr.update(visible=False)

def reload_chat_log(character_name: Optional[str], api_history_limit_value: str):
    if not character_name:
        return [], []

    log_f,_,_,_,_ = get_character_files_paths(character_name)
    if not log_f or not os.path.exists(log_f):
        return [], []

    full_raw_history = utils.load_chat_log(log_f, character_name)
    display_turns = _get_display_history_count(api_history_limit_value)
    visible_history = full_raw_history[-(display_turns * 2):]
    history, mapping_list = utils.format_history_for_gradio(visible_history, character_name)
    return history, mapping_list

def handle_wb_add_place_button_click(area_selector_value: Optional[str]):
    """場所追加ボタンが押されたとき、エリアが選択されていればフォームを表示する"""
    if not area_selector_value:
        gr.Warning("まず、場所を追加したいエリアを選択してください。")
        # フォームは表示しない
        return "place", gr.update(visible=False), "#### 新しい場所の作成"

    # エリアが選択されていればフォームを表示する
    return "place", gr.update(visible=True), "#### 新しい場所の作成"

def handle_save_memory_click(character_name, json_string_data):
    if not character_name: gr.Warning("キャラクターが選択されていません。"); return gr.update()
    try: return save_memory_data(character_name, json_string_data)
    except Exception as e: gr.Error(f"記憶の保存中にエラーが発生しました: {e}"); return gr.update()

def handle_reload_memory(character_name: str) -> str:
    if not character_name: gr.Warning("キャラクターが選択されていません。"); return "{}"
    gr.Info(f"「{character_name}」の記憶を再読み込みしました。"); _, _, _, memory_json_path, _ = get_character_files_paths(character_name); return json.dumps(load_memory_data_safe(memory_json_path), indent=2, ensure_ascii=False)

def load_notepad_content(character_name: str) -> str:
    if not character_name: return ""
    _, _, _, _, notepad_path = get_character_files_paths(character_name)
    if notepad_path and os.path.exists(notepad_path):
        with open(notepad_path, "r", encoding="utf-8") as f: return f.read()
    return ""

def handle_save_notepad_click(character_name: str, content: str) -> str:
    if not character_name: gr.Warning("キャラクターが選択されていません。"); return content
    _, _, _, _, notepad_path = character_manager.get_character_files_paths(character_name)
    if not notepad_path: gr.Error(f"「{character_name}」のメモ帳パス取得失敗。"); return content
    lines = [f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}] {line.strip()}" if line.strip() and not re.match(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\]", line.strip()) else line.strip() for line in content.strip().split('\n') if line.strip()]
    final_content = "\n".join(lines)
    try:
        with open(notepad_path, "w", encoding="utf-8") as f: f.write(final_content + ('\n' if final_content else ''))
        gr.Info(f"「{character_name}」のメモ帳を保存しました。"); return final_content
    except Exception as e: gr.Error(f"メモ帳の保存エラー: {e}"); return content

def handle_clear_notepad_click(character_name: str) -> str:
    if not character_name: gr.Warning("キャラクターが選択されていません。"); return ""
    _, _, _, _, notepad_path = character_manager.get_character_files_paths(character_name)
    if not notepad_path: gr.Error(f"「{character_name}」のメモ帳パス取得失敗。"); return ""
    try:
        with open(notepad_path, "w", encoding="utf-8") as f: f.write("")
        gr.Info(f"「{character_name}」のメモ帳を空にしました。"); return ""
    except Exception as e: gr.Error(f"メモ帳クリアエラー: {e}"); return f"エラー: {e}"

def handle_reload_notepad(character_name: str) -> str:
    if not character_name: gr.Warning("キャラクターが選択されていません。"); return ""
    content = load_notepad_content(character_name); gr.Info(f"「{character_name}」のメモ帳を再読み込みしました。"); return content

def render_alarms_as_dataframe():
    alarms = sorted(alarm_manager.load_alarms(), key=lambda x: x.get("time", "")); all_rows = []
    for a in alarms:
        schedule_display = "単発"
        if a.get("date"):
            try:
                date_obj, today = datetime.datetime.strptime(a["date"], "%Y-%m-%d").date(), datetime.date.today()
                if date_obj == today: schedule_display = "今日"
                elif date_obj == today + datetime.timedelta(days=1): schedule_display = "明日"
                else: schedule_display = date_obj.strftime("%m/%d")
            except: schedule_display = "日付不定"
        elif a.get("days"): schedule_display = ",".join([DAY_MAP_EN_TO_JA.get(d.lower(), d.upper()) for d in a["days"]])
        all_rows.append({"ID": a.get("id"), "状態": a.get("enabled", False), "時刻": a.get("time"), "予定": schedule_display, "キャラ": a.get("character"), "内容": a.get("context_memo") or ""})
    return pd.DataFrame(all_rows, columns=["ID", "状態", "時刻", "予定", "キャラ", "内容"])

def get_display_df(df_with_id: pd.DataFrame):
    if df_with_id is None or df_with_id.empty: return pd.DataFrame(columns=["状態", "時刻", "予定", "キャラ", "内容"])
    return df_with_id[["状態", "時刻", "予定", "キャラ", "内容"]] if 'ID' in df_with_id.columns else df_with_id

def handle_alarm_selection(evt: gr.SelectData, df_with_id: pd.DataFrame) -> List[str]:
    """
    Dataframeの選択イベントをシンプルに処理し、選択された行のIDを返す。
    """
    # イベントデータ、特にインデックスが存在しない場合は、空のリストを返す
    if not hasattr(evt, 'index') or evt.index is None or df_with_id is None or df_with_id.empty:
        return []

    # GradioのSelectDataから行番号を取得 (evt.indexは (行, 列) のタプル)
    row_index = evt.index[0]

    # 行番号が有効な範囲にあるか確認
    if 0 <= row_index < len(df_with_id):
        # 正しい行のIDを抽出し、リストに入れて返す
        selected_id = str(df_with_id.iloc[row_index]['ID'])
        return [selected_id]

    # 有効な行でなければ空のリストを返す
    return []

def handle_alarm_selection_for_all_updates(evt: gr.SelectData, df_with_id: pd.DataFrame):
    selected_ids = handle_alarm_selection(evt, df_with_id)
    feedback_text = "アラームを選択してください" if not selected_ids else f"{len(selected_ids)} 件のアラームを選択中"

    all_chars = character_manager.get_character_list()
    default_char = all_chars[0] if all_chars else "Default"

    if len(selected_ids) == 1:
        alarm = next((a for a in alarm_manager.load_alarms() if a.get("id") == selected_ids[0]), None)
        if alarm:
            h, m = alarm.get("time", "08:00").split(":")
            days_ja = [DAY_MAP_EN_TO_JA.get(d.lower(), d.upper()) for d in alarm.get("days", [])]

            form_updates = (
                "アラーム更新", alarm.get("context_memo", ""), alarm.get("character", default_char),
                days_ja, alarm.get("is_emergency", False), h, m, selected_ids[0]
            )
            cancel_button_visibility = gr.update(visible=True) # キャンセルボタンを表示
        else: # 念のための安全策
            form_updates = ("アラーム追加", "", default_char, [], False, "08", "00", None)
            cancel_button_visibility = gr.update(visible=False) # キャンセルボタンを非表示
    else: # 選択解除時
        form_updates = ("アラーム追加", "", default_char, [], False, "08", "00", None)
        cancel_button_visibility = gr.update(visible=False) # キャンセルボタンを非表示

    return (selected_ids, feedback_text) + form_updates + (cancel_button_visibility,)

def toggle_selected_alarms_status(selected_ids: list, target_status: bool):
    if not selected_ids: gr.Warning("状態を変更するアラームが選択されていません。")
    else:
        current_alarms = alarm_manager.load_alarms()
        modified = any(a.get("id") in selected_ids and a.update({"enabled": target_status}) is None for a in current_alarms)
        if modified:
            alarm_manager.alarms_data_global = current_alarms; alarm_manager.save_alarms()
            gr.Info(f"{len(selected_ids)}件のアラームの状態を「{'有効' if target_status else '無効'}」に変更しました。")
    new_df_with_ids = render_alarms_as_dataframe(); return new_df_with_ids, get_display_df(new_df_with_ids)

# ▼▼▼ この関数を新しく追加 ▼▼▼
def handle_delete_alarms_and_update_ui(selected_ids: list):
    """【司令塔】選択されたアラームを削除し、UI全体を更新する。"""
    if not selected_ids:
        gr.Warning("削除するアラームが選択されていません。")
        df_with_ids = render_alarms_as_dataframe()
        return df_with_ids, get_display_df(df_with_ids), gr.update(), gr.update()

    deleted_count = 0
    for sid in selected_ids:
        if alarm_manager.delete_alarm(str(sid)):
            deleted_count += 1

    if deleted_count > 0:
        gr.Info(f"{deleted_count}件のアラームを削除しました。")

    new_df_with_ids = render_alarms_as_dataframe()
    display_df = get_display_df(new_df_with_ids)

    new_selected_ids = []
    feedback_text = "アラームを選択してください"

    return new_df_with_ids, display_df, new_selected_ids, feedback_text

def handle_cancel_alarm_edit():
    """アラーム編集をキャンセルし、フォームを初期状態に戻す"""
    all_chars = character_manager.get_character_list()
    default_char = all_chars[0] if all_chars else "Default"

    # フォームと選択状態を完全にリセット
    return (
        "アラーム追加", "", gr.update(choices=all_chars, value=default_char),
        [], False, "08", "00", None, [], "アラームを選択してください",
        gr.update(visible=False) # キャンセルボタン自身を非表示に
    )

def handle_add_or_update_alarm(editing_id, h, m, char, context, days_ja, is_emergency):
    from tools.alarm_tools import set_personal_alarm
    context_memo = context.strip() if context and context.strip() else "時間になりました"
    days_en = [DAY_MAP_JA_TO_EN.get(d) for d in days_ja if d in DAY_MAP_JA_TO_EN]

    if editing_id:
        alarm_manager.delete_alarm(editing_id)
        gr.Info(f"アラームID:{editing_id} を更新しました。")
    else:
        gr.Info(f"新しいアラームを追加しました。")

    set_personal_alarm.func(time=f"{h}:{m}", context_memo=context_memo, character_name=char, days=days_en, date=None, is_emergency=is_emergency)

    new_df_with_ids = render_alarms_as_dataframe()
    all_chars = character_manager.get_character_list()
    default_char = all_chars[0] if all_chars else "Default"

    return (
        new_df_with_ids, get_display_df(new_df_with_ids),
        "アラーム追加", "", gr.update(choices=all_chars, value=default_char),
        [], False, "08", "00", None, [], "アラームを選択してください",
        gr.update(visible=False) # キャンセルボタンを非表示
    )

def handle_timer_submission(timer_type, duration, work, brk, cycles, char, work_theme, brk_theme, api_key_name, normal_theme):
    if not char or not api_key_name:
        return "エラー：キャラクターとAPIキーを選択してください。"

    try:
        if timer_type == "通常タイマー":
            # ▼▼▼ 通常タイマーツールを呼び出す ▼▼▼
            result_message = timer_tools.set_timer.func(
                duration_minutes=int(duration),
                theme=normal_theme or "時間になりました！",
                character_name=char
            )
            gr.Info(f"通常タイマーを設定しました。")
        elif timer_type == "ポモドーロタイマー":
            # ▼▼▼ ポモドーロタイマーツールを呼び出す ▼▼▼
            result_message = timer_tools.set_pomodoro_timer.func(
                work_minutes=int(work),
                break_minutes=int(brk),
                cycles=int(cycles),
                work_theme=work_theme or "作業終了の時間です。",
                break_theme=brk_theme or "休憩終了の時間です。",
                character_name=char
            )
            gr.Info(f"ポモドーロタイマーを設定しました。")
        else:
            result_message = "エラー: 不明なタイマー種別です。"

        # ツールからの成功/エラーメッセージをUIに表示
        return result_message

    except Exception as e:
        traceback.print_exc()
        return f"タイマー開始エラー: {e}"

def handle_rag_update_button_click(character_name: str, api_key_name: str):
    if not character_name or not api_key_name: gr.Warning("キャラクターとAPIキーを選択してください。"); return
    api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"): gr.Warning(f"APIキー '{api_key_name}' が有効ではありません。"); return
    gr.Info(f"「{character_name}」のRAG索引の更新を開始します...")
    import rag_manager
    threading.Thread(target=lambda: rag_manager.create_or_update_index(character_name, api_key)).start()

def _run_core_memory_update(character_name: str, api_key: str):
    print(f"--- [スレッド開始] コアメモリ更新処理を開始します (Character: {character_name}) ---")
    try:
        from tools import memory_tools
        result = memory_tools.summarize_and_save_core_memory.func(character_name=character_name, api_key=api_key)
        print(f"--- [スレッド終了] コアメモリ更新処理完了 --- 結果: {result}")
    except Exception: print(f"--- [スレッドエラー] コアメモリ更新中に予期せぬエラー ---"); traceback.print_exc()

def handle_core_memory_update_click(character_name: str, api_key_name: str):
    if not character_name or not api_key_name: gr.Warning("キャラクターとAPIキーを選択してください。"); return
    api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"): gr.Warning(f"APIキー '{api_key_name}' が有効ではありません。"); return
    gr.Info(f"「{character_name}」のコアメモリ更新をバックグラウンドで開始しました。")
    threading.Thread(target=_run_core_memory_update, args=(character_name, api_key)).start()

def update_model_state(model): config_manager.save_config("last_model", model); return model

def update_api_key_state(api_key_name):
    config_manager.save_config("last_api_key_name", api_key_name)
    gr.Info(f"APIキーを '{api_key_name}' に設定しました。")
    return api_key_name

def update_api_history_limit_state_and_reload_chat(limit_ui_val: str, character_name: Optional[str]):
    key = next((k for k, v in constants.API_HISTORY_LIMIT_OPTIONS.items() if v == limit_ui_val), "all")
    config_manager.save_config("last_api_history_limit_option", key)
    history, mapping_list = reload_chat_log(character_name, key)
    return key, history, mapping_list

def handle_play_audio_button_click(selected_message: Optional[Dict[str, str]], character_name: str, api_key_name: str):
    if not selected_message:
        gr.Warning("再生するメッセージが選択されていません。")
        # ★ ボタンの状態は変更しないので、元の状態を返す
        yield gr.update(visible=False), gr.update(interactive=True), gr.update(interactive=True)
        return

    # ▼▼▼ 修正の核心：yield を使った段階的なUI更新 ▼▼▼
    # 1. まず「生成中」の状態をUIに即時反映させる
    yield (
        gr.update(visible=False), # プレイヤーは一旦隠す
        gr.update(value="音声生成中... ▌", interactive=False), # 再生ボタンを無効化
        gr.update(interactive=False)  # 試聴ボタンも無効化
    )

    try:
        raw_text = utils.extract_raw_text_from_html(selected_message.get("content"))
        text_to_speak = utils.remove_thoughts_from_text(raw_text)
        if not text_to_speak:
            gr.Info("このメッセージには音声で再生できるテキストがありません。")
            return

        effective_settings = config_manager.get_effective_settings(character_name)
        voice_id, voice_style_prompt = effective_settings.get("voice_id", "iapetus"), effective_settings.get("voice_style_prompt", "")
        api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)
        if not api_key:
            gr.Warning(f"APIキー '{api_key_name}' が見つかりません。")
            return

        from audio_manager import generate_audio_from_text
        gr.Info(f"「{character_name}」の声で音声を生成しています...")
        audio_filepath = generate_audio_from_text(text_to_speak, api_key, voice_id, voice_style_prompt)

        if audio_filepath:
            gr.Info("再生します。")
            # 2. 成功したら、プレイヤーを表示して再生を開始
            yield gr.update(value=audio_filepath, visible=True), gr.update(), gr.update()
        else:
            gr.Error("音声の生成に失敗しました。")

    finally:
        # 3. 成功・失敗に関わらず、必ず最後にボタンの状態を元に戻す
        yield (
            gr.update(), # プレイヤーの状態はそのまま
            gr.update(value="🔊 選択した発言を再生", interactive=True), # 再生ボタンを有効化
            gr.update(interactive=True)  # 試聴ボタンを有効化
        )

def handle_voice_preview(selected_voice_name: str, voice_style_prompt: str, text_to_speak: str, api_key_name: str):
    if not selected_voice_name or not text_to_speak or not api_key_name:
        gr.Warning("声、テキスト、APIキーがすべて選択されている必要があります。")
        yield gr.update(visible=False), gr.update(interactive=True), gr.update(interactive=True)
        return

    # ▼▼▼ 修正の核心：yield を使った段階的なUI更新 ▼▼▼
    yield (
        gr.update(visible=False),
        gr.update(interactive=False),
        gr.update(value="生成中...", interactive=False)
    )

    try:
        voice_id = next((key for key, value in config_manager.SUPPORTED_VOICES.items() if value == selected_voice_name), None)
        api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)
        if not voice_id or not api_key:
            gr.Warning("声またはAPIキーが無効です。")
            return

        from audio_manager import generate_audio_from_text
        gr.Info(f"声「{selected_voice_name}」で音声を生成しています...")
        audio_filepath = generate_audio_from_text(text_to_speak, api_key, voice_id, voice_style_prompt)

        if audio_filepath:
            gr.Info("プレビューを再生します。")
            yield gr.update(value=audio_filepath, visible=True), gr.update(), gr.update()
        else:
            gr.Error("音声の生成に失敗しました。")

    finally:
        # 成功・失敗に関わらず、必ず最後にボタンの状態を元に戻す
        yield (
            gr.update(),
            gr.update(interactive=True),
            gr.update(value="試聴", interactive=True)
        )

def handle_generate_or_regenerate_scenery_image(character_name: str, api_key_name: str, style_choice: str) -> Optional[str]:
    """「情景画像を生成/更新」ボタン専用ハンドラ。シーンディレクターAIを起動してプロンプトを生成する。"""
    if not character_name or not api_key_name:
        gr.Warning("キャラクターとAPIキーを選択してください。")
        return None

    api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)
    if not api_key:
        gr.Warning(f"APIキー '{api_key_name}' が見つかりません。")
        return None

    location_id = utils.get_current_location(character_name)
    existing_image_path = utils.find_scenery_image(character_name, location_id)

    if not location_id:
        gr.Warning("現在地が特定できません。")
        return existing_image_path

    final_prompt = ""
    # --- シーンディレクターAIによるプロンプト生成 ---
    gr.Info("シーンディレクターAIがプロンプトを構成しています...")
    try:
        # 1. 現在の状況を定義する
        now = datetime.datetime.now()
        time_of_day = utils.get_time_of_day(now.hour)
        season = utils.get_season(now.month)
        style_prompts = {
            "写真風 (デフォルト)": "An ultra-detailed, photorealistic masterpiece with cinematic lighting.",
            "イラスト風": "A beautiful and detailed anime-style illustration, pixiv contest winner.",
            "アニメ風": "A high-quality screenshot from a modern animated film.",
            "水彩画風": "A gentle and emotional watercolor painting."
        }
        style_choice_text = style_prompts.get(style_choice, style_prompts["写真風 (デフォルト)"])

        # 2. 場所の基本設定テキストを取得
        world_settings_path = character_manager.get_world_settings_path(character_name)
        world_settings = utils.parse_world_file(world_settings_path)
        if not world_settings:
            gr.Error("世界設定の読み込みに失敗しました。")
            return existing_image_path

        space_text = None
        for area, places in world_settings.items():
            if location_id in places:
                space_text = places[location_id]
                break

        if not space_text:
            gr.Error("現在の場所の定義が見つかりません。")
            return existing_image_path

        # 3. シーンディレクターAI（gemini-2.5-flash）を準備
        from agent.graph import get_configured_llm
        scene_director_llm = get_configured_llm("gemini-2.5-flash", api_key)

        # 4. AIへの指示書（プロンプト）を作成
        director_prompt = f"""
You are a master scene director AI for a high-end image generation model.
Your sole purpose is to synthesize all available information into a single, cohesive, and flawless prompt.

**Objective:**
Generate one final, masterful prompt for an image generation AI.

**Core Principles:**
1.  **Foundation First (Absolute Priority):** The 'Base Location Description' is the undeniable truth of the world. Your final prompt **must be a faithful and accurate visual representation** of all objects, furniture, materials, and architectural structures described within it. Do not omit, add, or change these fundamental elements.
2.  **Synthesize, Don't Contradict:** Read the 'Base Location Description' and the 'Current Scene Conditions'. Your final prompt must logically integrate both. If there are contradictions (e.g., the description mentions 'natural light' but the condition is 'night'), you MUST resolve them by prioritizing the 'Current Scene Conditions' while upholding Principle #1.
3.  **Strictly Visual:** The output must be a purely visual and descriptive paragraph in English. Exclude any narrative, metaphors, sounds, or non-visual elements.
4.  **Mandatory Inclusions:** Your final prompt MUST incorporate the specified 'Aspect Ratio' and adhere to the 'Style Definition'.
5.  **Absolute Prohibitions:** Strictly enforce all 'Negative Prompts'.
6.  **Output Format:** Output ONLY the final, single-paragraph prompt. Do not include any of your own thoughts, acknowledgments, or conversational text.

---
**Information Dossier:**

**1. Base Location Description (The ground truth for all structures and objects):**
{space_text}

**2. Current Scene Conditions (This defines the current atmosphere and overrides conflicting light sources):**
- Time of Day: {time_of_day}
- Season: {season}

**3. Style Definition (Incorporate this aesthetic):**
- {style_choice_text}

**4. Mandatory Technical Specs:**
- Aspect Ratio: The final image must have a 16:9 landscape aspect ratio.

**5. Negative Prompts (Strictly enforce these exclusions):**
- Absolutely no text, letters, characters, signatures, or watermarks. Do not include people.
---

**Final Master Prompt:**
"""

        # 5. AIにプロンプト生成を依頼
        final_prompt = scene_director_llm.invoke(director_prompt).content.strip()

    except Exception as e:
        gr.Error(f"シーンディレクターAIによるプロンプト生成中にエラーが発生しました: {e}")
        traceback.print_exc()
        return existing_image_path

    if not final_prompt:
        gr.Error("シーンディレクターAIが有効なプロンプトを生成できませんでした。")
        return existing_image_path

    # --- 画像生成AIへの最終的な依頼 ---
    gr.Info(f"「{style_choice}」で画像を生成します...")
    result = generate_image_tool_func.func(prompt=final_prompt, character_name=character_name, api_key=api_key)

    # --- 生成画像の保存とUI更新 ---
    if "Generated Image:" in result:
        generated_path = result.replace("[Generated Image: ", "").replace("]", "").strip()
        if os.path.exists(generated_path):
            save_dir = os.path.join(constants.CHARACTERS_DIR, character_name, "spaces", "images")
            now = datetime.datetime.now()

            cache_key = f"{location_id}_{utils.get_season(now.month)}_{utils.get_time_of_day(now.hour)}"
            specific_filename = f"{cache_key}.png"
            specific_path = os.path.join(save_dir, specific_filename)

            if os.path.exists(specific_path):
                os.remove(specific_path)

            shutil.move(generated_path, specific_path)
            print(f"--- 情景画像を生成し、保存しました: {specific_path} ---")

            gr.Info("画像を生成/更新しました。")
            return specific_path
        else:
            gr.Error("画像の生成には成功しましたが、一時ファイルの特定に失敗しました。")
            return existing_image_path
    else:
        gr.Error(f"画像の生成/更新に失敗しました。AIの応答: {result}")
        return existing_image_path

def handle_api_connection_test(api_key_name: str):
    """APIキーを使って、Nexus Arkが必要とする全てのモデルへの接続をテストする"""
    if not api_key_name:
        gr.Warning("テストするAPIキーが選択されていません。")
        return

    api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        gr.Error(f"APIキー '{api_key_name}' は無効です。config.jsonを確認してください。")
        return

    gr.Info(f"APIキー '{api_key_name}' を使って、必須モデルへの接続をテストしています...")

    # 正しいSDKをインポート
    import google.genai as genai

    # チェックするモデルのリストを、現在のアプリケーション仕様に更新
    required_models = {
        "models/gemini-2.5-pro": "メインエージェント (agent_node)",
        "models/gemini-2.5-flash": "高速処理 (context_generator)",
        # 注意: 画像生成モデルは 'generate_content' APIではテストできないため、リストから除外。
        # 代わりに、主要なテキストモデルへのアクセスを保証します。
    }

    results = []
    all_ok = True

    try:
        # クライアントの初期化は一度だけ行う
        client = genai.Client(api_key=api_key)

        for model_name, purpose in required_models.items():
            try:
                # 各モデルの情報を取得しようと試みる
                client.models.get(model=model_name)
                results.append(f"✅ **{purpose} ({model_name.split('/')[-1]})**: 利用可能です。")
            except Exception as model_e:
                results.append(f"❌ **{purpose} ({model_name.split('/')[-1]})**: 利用できません。")
                print(f"--- モデル '{model_name}' のチェックに失敗: {model_e} ---")
                all_ok = False

        # 最終的な結果を通知
        result_message = "\n\n".join(results)
        if all_ok:
            gr.Info(f"✅ **全ての必須モデルが利用可能です！**\n\n{result_message}")
        else:
            gr.Warning(f"⚠️ **一部のモデルが利用できません。**\n\n{result_message}\n\nGoogle AI StudioまたはGoogle Cloudコンソールの設定を確認してください。")

    except Exception as e:
        error_message = f"❌ **APIサーバーへの接続自体に失敗しました。**\n\nAPIキーが無効か、ネットワークの問題が発生している可能性があります。\n\n詳細: {str(e)}"
        print(f"--- API接続テストエラー ---\n{traceback.format_exc()}")
        gr.Error(error_message)

#
# ワールド・ビルダー関連の新しいハンドラ群
#
from world_builder import get_world_data, save_world_data

def handle_world_builder_load(character_name: str):
    """ワールド・ビルダータブが選択された時や、キャラクターが変更された時の初期化処理。"""
    if not character_name:
        return {}, gr.update(choices=[], value=None) # 返り値の数を2つに修正

    world_data = get_world_data(character_name)
    area_choices = sorted(world_data.keys())

    # UIの期待通り、2つの値だけを返す
    return world_data, gr.update(choices=area_choices, value=None)

def handle_character_change_for_all_tabs(character_name: str, api_key_name: str):
    """キャラクター変更時にすべてのタブを更新する司令塔。"""
    print(f"--- UI司令塔(handle_character_change_for_all_tabs)実行: {character_name} ---")
    chat_tab_updates = handle_character_change(character_name, api_key_name)
    world_builder_updates = handle_world_builder_load(character_name)
    return chat_tab_updates + world_builder_updates


def handle_wb_area_select(world_data: Dict, area_name: str):
    """エリアが選択された時、場所のドロップダウンを更新する。"""
    if not area_name or area_name not in world_data:
        return gr.update(choices=[], value=None)

    places = sorted(world_data[area_name].keys())
    return gr.update(choices=places, value=None)

def handle_wb_place_select(world_data: Dict, area_name: str, place_name: str):
    """場所が選択された時、内容エディタを更新し、ボタンを表示する。"""
    if not area_name or not place_name:
        # 場所が選択されていない場合は、エディタとボタンを隠す
        return gr.update(value="", visible=False), gr.update(visible=False), gr.update(visible=False)

    # 場所のコンテンツを取得
    content = world_data.get(area_name, {}).get(place_name, "")

    # UIの期待通り、3つの値をタプルで返す
    return (
        gr.update(value=content, visible=True),  # 1. content_editor の内容を更新し、表示する
        gr.update(visible=True),                 # 2. save_button_row を表示
        gr.update(visible=True)                  # 3. delete_place_button を表示
    )

def handle_wb_save(character_name: str, world_data: Dict, area_name: str, place_name: str, content: str):
    """保存ボタンが押された時の処理。"""
    if not character_name or not area_name or not place_name:
        gr.Warning("保存するにはエリアと場所を選択してください。")
        return world_data

    # world_data stateを更新
    if area_name in world_data and place_name in world_data[area_name]:
        world_data[area_name][place_name] = content
        save_world_data(character_name, world_data)
        gr.Info("世界設定を保存しました。")
    else:
        gr.Error("保存対象のエリアまたは場所が見つかりません。")

    return world_data

def handle_wb_add_area(character_name: str, world_data: Dict, area_name: Optional[str]):
    """エリア追加ボタン"""
    if not area_name:
        gr.Warning("新しいエリア名を入力してください。")
        return world_data, gr.update()
    if area_name in world_data:
        gr.Warning(f"エリア '{area_name}' は既に存在します。")
        return world_data, gr.update()

    world_data[area_name] = {}
    save_world_data(character_name, world_data)
    gr.Info(f"新しいエリア '{area_name}' を追加しました。")

    area_choices = sorted(world_data.keys())
    return world_data, gr.update(choices=area_choices, value=area_name)

def handle_wb_add_place(character_name: str, world_data: Dict, area_name: str, place_name: Optional[str]):
    """場所追加ボタン"""
    if not area_name:
        gr.Warning("場所を追加するエリアを選択してください。")
        return world_data, gr.update()
    if not place_name:
        gr.Warning("新しい場所名を入力してください。")
        return world_data, gr.update()
    if place_name in world_data.get(area_name, {}):
        gr.Warning(f"場所 '{place_name}' はエリア '{area_name}' に既に存在します。")
        return world_data, gr.update()

    world_data[area_name][place_name] = "新しい場所です。説明を記述してください。"
    save_world_data(character_name, world_data)
    gr.Info(f"エリア '{area_name}' に新しい場所 '{place_name}' を追加しました。")

    place_choices = sorted(world_data[area_name].keys())
    return world_data, gr.update(choices=place_choices, value=place_name)

def handle_wb_delete_area(character_name: str, world_data: Dict, area_name: str):
    """エリア削除ボタン"""
    if not area_name:
        gr.Warning("削除するエリアを選択してください。")
        return world_data, gr.update(), gr.update(), ""
    if area_name not in world_data:
        gr.Warning(f"エリア '{area_name}' が見つかりません。")
        return world_data, gr.update(), gr.update(), ""

    del world_data[area_name]
    save_world_data(character_name, world_data)
    gr.Info(f"エリア '{area_name}' を削除しました。")

    area_choices = sorted(world_data.keys())
    return world_data, gr.update(choices=area_choices, value=None), gr.update(choices=[], value=None), ""

def handle_wb_delete_place(character_name: str, world_data: Dict, area_name: str, place_name: str):
    """場所削除ボタン"""
    if not area_name or not place_name:
        gr.Warning("削除するエリアと場所を選択してください。")
        return world_data, gr.update(), ""
    if area_name not in world_data or place_name not in world_data[area_name]:
        gr.Warning(f"場所 '{place_name}' がエリア '{area_name}' に見つかりません。")
        return world_data, gr.update(), ""

    del world_data[area_name][place_name]
    save_world_data(character_name, world_data)
    gr.Info(f"場所 '{place_name}' を削除しました。")

    place_choices = sorted(world_data[area_name].keys())
    return world_data, gr.update(choices=place_choices, value=None), ""

def handle_wb_confirm_add(character_name: str, world_data: Dict, selected_area: str, item_type: str, item_name: str):
    """エリアまたは場所の追加を確定するハンドラ。"""
    if not character_name or not item_name:
        gr.Warning("キャラクターが選択されていないか、名前が入力されていません。")
        return world_data, gr.update(), gr.update(), gr.update(visible=True), item_name

    item_name = item_name.strip()
    if not item_name:
        gr.Warning("名前が空です。")
        return world_data, gr.update(), gr.update(), gr.update(visible=True), item_name

    if item_type == "area":
        if item_name in world_data:
            gr.Warning(f"エリア '{item_name}' は既に存在します。")
            return world_data, gr.update(), gr.update(), gr.update(visible=True), item_name

        world_data[item_name] = {}
        save_world_data(character_name, world_data)
        gr.Info(f"新しいエリア '{item_name}' を追加しました。")

        area_choices = sorted(world_data.keys())
        return world_data, gr.update(choices=area_choices, value=item_name), gr.update(choices=[], value=None), gr.update(visible=False), ""

    elif item_type == "place":
        if not selected_area:
            gr.Warning("場所を追加するエリアを選択してください。")
            return world_data, gr.update(), gr.update(), gr.update(visible=True), item_name

        if item_name in world_data.get(selected_area, {}):
            gr.Warning(f"場所 '{item_name}' はエリア '{selected_area}' に既に存在します。")
            return world_data, gr.update(), gr.update(), gr.update(visible=True), item_name

        world_data[selected_area][item_name] = "新しい場所です。説明を記述してください。"
        save_world_data(character_name, world_data)
        gr.Info(f"エリア '{selected_area}' に新しい場所 '{item_name}' を追加しました。")

        place_choices = sorted(world_data[selected_area].keys())
        return world_data, gr.update(), gr.update(choices=place_choices, value=item_name), gr.update(visible=False), ""

    else:
        gr.Error(f"不明なアイテムタイプです: {item_type}")
        return world_data, gr.update(), gr.update(), gr.update(visible=False), ""

def handle_save_gemini_key(key_name, key_value):
    if not key_name or not key_value:
        gr.Warning("キーの名前と値の両方を入力してください。")
        return gr.update(), gr.update()

    config_manager.add_or_update_gemini_key(key_name, key_value)
    gr.Info(f"Gemini APIキー「{key_name}」を保存しました。")

    new_keys = list(config_manager.GEMINI_API_KEYS.keys())
    return pd.DataFrame(new_keys, columns=["Geminiキー名"]), gr.update(choices=new_keys)

def handle_delete_gemini_key(key_name):
    if not key_name:
        gr.Warning("削除するキーの名前を入力してください。")
        return gr.update(), gr.update()

    config_manager.delete_gemini_key(key_name)
    gr.Info(f"Gemini APIキー「{key_name}」を削除しました。")

    new_keys = list(config_manager.GEMINI_API_KEYS.keys())
    return pd.DataFrame(new_keys, columns=["Geminiキー名"]), gr.update(choices=new_keys, value=new_keys[0] if new_keys else None)

def handle_save_pushover_config(user_key, app_token):
    config_manager.update_pushover_config(user_key, app_token)
    gr.Info("Pushover設定を保存しました。")

def handle_save_tavily_key(api_key):
    config_manager.update_tavily_key(api_key)
    gr.Info("Tavily APIキーを保存しました。")

def handle_notification_service_change(service_choice: str):
    """通知サービスの設定を保存するハンドラ"""
    if service_choice in ["Discord", "Pushover"]:
        config_manager.save_config("notification_service", service_choice.lower())
        gr.Info(f"通知サービスを「{service_choice}」に設定しました。")
    return service_choice.lower()

def handle_save_discord_webhook(webhook_url: str):
    """Discord Webhook URLを保存するハンドラ"""
    config_manager.save_config("notification_webhook_url", webhook_url)
    gr.Info("Discord Webhook URLを保存しました。")

def load_system_prompt_content(character_name: str) -> str:
    """SystemPrompt.txtの内容を読み込む"""
    if not character_name: return ""
    _, system_prompt_path, _, _, _ = get_character_files_paths(character_name)
    if system_prompt_path and os.path.exists(system_prompt_path):
        with open(system_prompt_path, "r", encoding="utf-8") as f:
            return f.read()
    return ""

def handle_save_system_prompt(character_name: str, content: str) -> None:
    """SystemPrompt.txtの内容を保存する"""
    if not character_name:
        gr.Warning("キャラクターが選択されていません。")
        return
    _, system_prompt_path, _, _, _ = get_character_files_paths(character_name)
    if not system_prompt_path:
        gr.Error(f"「{character_name}」のプロンプトパス取得失敗。")
        return
    try:
        with open(system_prompt_path, "w", encoding="utf-8") as f:
            f.write(content)
        gr.Info(f"「{character_name}」の人格プロンプトを保存しました。")
    except Exception as e:
        gr.Error(f"人格プロンプトの保存エラー: {e}")

def handle_reload_system_prompt(character_name: str) -> str:
    """SystemPrompt.txtを再読み込みしてエディタに表示する"""
    if not character_name:
        gr.Warning("キャラクターが選択されていません。")
        return ""
    content = load_system_prompt_content(character_name)
    gr.Info(f"「{character_name}」の人格プロンプトを再読み込みしました。")
    return content

# ▼▼▼ この関数を新しく追加 ▼▼▼
def handle_rerun_button_click(
    selected_message: Optional[Dict[str, str]],
    character_name: str,
    api_key_name: str,
    file_list: Optional[List],
    api_history_limit: str,
    debug_mode: bool
):
    """
    「再生成」ボタンが押された際の処理。
    選択されたAIの応答とその直前のユーザー入力を削除し、再度AIに応答を生成させる。
    """
    if not selected_message or not character_name:
        gr.Warning("再生成するメッセージが選択されていません。")
        # 何もせずに現在のチャット状態を返す
        history, mapping_list = reload_chat_log(character_name, api_history_limit)
        # 戻り値の数を揃える
        return (history, mapping_list, gr.update(), gr.update(), gr.update(),
                gr.update(), gr.update(), gr.update(), gr.update(), gr.update(),
                gr.update(visible=False))

    log_f, _, _, _, _ = get_character_files_paths(character_name)

    # ユーザーの入力内容を復元し、関連するログを削除
    restored_input_text = utils.delete_and_get_previous_user_input(log_f, selected_message, character_name)

    if restored_input_text is None:
        gr.Error("再生成の元となるユーザー入力の特定に失敗しました。")
        history, mapping_list = reload_chat_log(character_name, api_history_limit)
        return (history, mapping_list, gr.update(), gr.update(), gr.update(),
                gr.update(), gr.update(), gr.update(), gr.update(), gr.update(),
                gr.update(visible=False))

    gr.Info("応答を再生成します...")

    # handle_message_submission の非同期処理を模倣
    # まず、UIを「思考中」の状態に更新
    chatbot_history, _ = reload_chat_log(character_name, api_history_limit)
    chatbot_history.append((restored_input_text, "思考中... ▌"))

    # handle_message_submission に処理を委譲
    # yield from を使って、handle_message_submission の yield を中継する
    yield from handle_message_submission(
        restored_input_text, # 復元したテキスト
        character_name,
        api_key_name,
        None, # 再実行時はファイル添付をサポートしない
        api_history_limit,
        debug_mode
    )
