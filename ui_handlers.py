# ui_handlers.py

from world_builder import get_world_data, generate_details_markdown, convert_data_to_yaml_str
import yaml
from typing import Dict, Any, Optional, Tuple, List
import character_manager
import gradio as gr
import json
from yaml.constructor import ConstructorError

# Keep all other existing imports and functions from the original ui_handlers.py
# For brevity, I'm only showing the new/changed functions.
# The `overwrite_file_with_block` will replace the whole file,
# so I need to reconstruct it with the old and new parts.

# [ ... all existing functions from the top of ui_handlers.py until the old world builder functions ... ]
# I will reconstruct the file from the last `read_file` output.
# ui_handlers.py (完全最終版)

import pandas as pd
import json
import traceback
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
from yaml.constructor import ConstructorError
import yaml


import gemini_api, config_manager, alarm_manager, character_manager, utils, constants
from agent.graph import generate_scenery_context
from timers import UnifiedTimer
from character_manager import get_character_files_paths, get_world_settings_path
from memory_manager import load_memory_data_safe, save_memory_data
from world_builder import get_world_data, save_world_data, generate_details_markdown, convert_data_to_yaml_str

DAY_MAP_EN_TO_JA = {"mon": "月", "tue": "火", "wed": "水", "thu": "木", "fri": "金", "sat": "土", "sun": "日"}
DAY_MAP_JA_TO_EN = {v: k for k, v in DAY_MAP_EN_TO_JA.items()}


def get_location_list_for_ui(character_name: str) -> list:
    """
    UIの移動先ドロップダウン用のリストを生成する。
    エリアと部屋の両方をリストに含める。
    """
    if not character_name: return []

    world_settings_path = get_world_settings_path(character_name)
    from utils import parse_world_markdown
    world_data = parse_world_markdown(world_settings_path)

    if not world_data: return []

    location_list = []
    # 2階層のループで、エリアと部屋をすべて探索する
    for area_id, area_data in world_data.items():
        if not isinstance(area_data, dict): continue

        # まず、エリア自体に 'name' があれば、それをリストに追加
        if 'name' in area_data:
            location_list.append((area_data['name'], area_id))

        # 次に、エリア内の各要素をチェック
        for room_id, room_data in area_data.items():
            # 値が辞書で、かつ 'name' キーを持つなら、それは部屋だと判断
            if isinstance(room_data, dict) and 'name' in room_data:
                location_list.append((room_data['name'], room_id))

    # 重複を除外し、名前でソートして返す
    unique_locations = sorted(list(set(location_list)), key=lambda x: x[0])
    return unique_locations

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

    locations = get_location_list_for_ui(character_name)
    current_location_id = utils.get_current_location(character_name)

    scenery_cache = utils.load_scenery_cache(character_name)
    current_location_name = scenery_cache.get("location_name", "（不明な場所）")
    scenery_text = scenery_cache.get("scenery_text", "（AIとの対話開始時に生成されます）")

    scenery_image_path = utils.find_scenery_image(character_name, utils.get_current_location(character_name))

    valid_location_ids = [loc[1] for loc in locations]
    location_dd_val = current_location_id if current_location_id in valid_location_ids else None

    effective_settings = config_manager.get_effective_settings(character_name)
    all_models = ["デフォルト"] + config_manager.AVAILABLE_MODELS_GLOBAL
    model_val = effective_settings["model_name"] if effective_settings["model_name"] != config_manager.initial_model_global else "デフォルト"
    voice_display_name = config_manager.SUPPORTED_VOICES.get(effective_settings.get("voice_id", "vindemiatrix"), list(config_manager.SUPPORTED_VOICES.values())[0])
    voice_style_prompt_val = effective_settings.get("voice_style_prompt", "")

    return (
        character_name, chat_history, mapping_list, "", profile_image, memory_str,
        character_name, character_name, notepad_content,
        gr.update(choices=locations, value=location_dd_val),
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
        return chatbot_history, mapping_list, gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update()

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

    final_response_text = response_data.get("response", "")
    location_name, scenery_text = response_data.get("location_name", "（取得失敗）"), response_data.get("scenery", "（取得失敗）")

    if not final_response_text or not final_response_text.strip():
        print("--- 警告: AIからの応答が空のため、後続処理をスキップしました ---")
        formatted_history, new_mapping_list = reload_chat_log(current_character_name, api_history_limit_state)
        new_alarm_df_with_ids = render_alarms_as_dataframe()
        new_display_df = get_display_df(new_alarm_df_with_ids)

        current_location_id = utils.get_current_location(current_character_name)
        scenery_image_path = utils.find_scenery_image(current_character_name, current_location_id)

        yield (formatted_history, new_mapping_list, gr.update(), gr.update(value=None),
               gr.update(), location_name, scenery_text, new_alarm_df_with_ids,
               new_display_df, scenery_image_path)
        return

    scenery_image_path = None
    if not location_name.startswith("（"):
        utils.save_scenery_cache(current_character_name, location_name, scenery_text)
        current_location_id = utils.get_current_location(current_character_name)
        scenery_image_path = utils.find_scenery_image(current_character_name, current_location_id)

    log_f, _, _, _, _ = get_character_files_paths(current_character_name)
    final_log_message = "\n\n".join(log_message_parts).strip()
    if final_log_message:
        user_header = utils._get_user_header_from_log(log_f, current_character_name)
        utils.save_message_to_log(log_f, user_header, final_log_message)

    utils.save_message_to_log(log_f, f"## {current_character_name}:", final_response_text)

    formatted_history, new_mapping_list = reload_chat_log(current_character_name, api_history_limit_state)
    new_alarm_df_with_ids = render_alarms_as_dataframe()
    new_display_df = get_display_df(new_alarm_df_with_ids)

    yield (formatted_history, new_mapping_list, gr.update(), gr.update(value=None),
           gr.update(), location_name, scenery_text, new_alarm_df_with_ids,
           new_display_df, scenery_image_path)

def handle_scenery_refresh(character_name: str, api_key_name: str) -> Tuple[str, str, Optional[str]]:
    if not character_name or not api_key_name:
        return "（キャラクターまたはAPIキーが未選択です）", "（キャラクターまたはAPIキーが未選択です）", None

    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key:
        gr.Warning(f"APIキー '{api_key_name}' が見つかりません。")
        return "（APIキーエラー）", "（APIキーエラー）", None

    gr.Info(f"「{character_name}」の現在の情景を更新しています...")
    location_name, _, scenery_text = generate_scenery_context(character_name, api_key)

    if not location_name.startswith("（"):
        utils.save_scenery_cache(character_name, location_name, scenery_text)
        gr.Info("情景を更新しました。")
        current_location_id = utils.get_current_location(character_name)
        scenery_image_path = utils.find_scenery_image(character_name, current_location_id)
    else:
        gr.Error("情景の更新に失敗しました。")
        scenery_image_path = None

    return location_name, scenery_text, scenery_image_path

def handle_location_change(character_name: str, location_id: str) -> Tuple[str, str, Optional[str]]:
    from tools.space_tools import set_current_location
    print(f"--- UIからの場所変更処理開始: キャラクター='{character_name}', 移動先ID='{location_id}' ---")

    current_loc_name = "（場所不明）"
    scenery_text = "（場所の変更に失敗しました）"
    current_image_path = None
    scenery_cache = utils.load_scenery_cache(character_name)
    if scenery_cache:
        current_loc_name = scenery_cache.get("location_name", current_loc_name)
        scenery_text = scenery_cache.get("scenery_text", scenery_text)

    current_location_id_before_move = utils.get_current_location(character_name)
    current_image_path = utils.find_scenery_image(character_name, current_location_id_before_move)

    if not character_name or not location_id:
        gr.Warning("キャラクターと移動先の場所を選択してください。")
        return current_loc_name, scenery_text, current_image_path

    result = set_current_location.func(location=location_id, character_name=character_name)

    if "Success" not in result:
        gr.Error(f"場所の変更に失敗しました: {result}")
        return current_loc_name, scenery_text, current_image_path

    gr.Info(f"場所を「{location_id}」に移動しました。")

    world_settings_path = get_world_settings_path(character_name)
    from utils import parse_world_markdown
    world_data = parse_world_markdown(world_settings_path)
    new_location_name = location_id
    if world_data:
        from character_manager import find_space_data_by_id_recursive
        space_data = find_space_data_by_id_recursive(world_data, location_id)
        if space_data and isinstance(space_data, dict):
            new_location_name = space_data.get("name", location_id)

    new_scenery_text = f"（場所を「{new_location_name}」に移動しました。「情景を更新」ボタン、またはAIとの対話で新しい景色を確認できます）"
    new_image_path = utils.find_scenery_image(character_name, location_id)

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
    if not hasattr(evt, 'index') or evt.index is None or df_with_id is None or df_with_id.empty: return []
    indices = evt.index if isinstance(evt.index, list) else [evt.index]
    return [str(df_with_id.iloc[r[0] if isinstance(r, tuple) else r]['ID']) for r in indices if isinstance(r, (int, tuple)) and 0 <= (r[0] if isinstance(r, tuple) else r) < len(df_with_id)]

def handle_alarm_selection_for_all_updates(evt: gr.SelectData, df_with_id: pd.DataFrame):
    selected_ids = handle_alarm_selection(evt, df_with_id)
    feedback_text = "アラームを選択してください" if not selected_ids else f"{len(selected_ids)} 件のアラームを選択中"
    all_chars, default_char = character_manager.get_character_list(), "Default"
    if all_chars: default_char = all_chars[0]
    if len(selected_ids) == 1:
        alarm = next((a for a in alarm_manager.load_alarms() if a.get("id") == selected_ids[0]), None)
        if alarm:
            h, m = alarm.get("time", "08:00").split(":")
            days_ja = [DAY_MAP_EN_TO_JA.get(d.lower(), d.upper()) for d in alarm.get("days", [])]
            form_updates = ("アラーム更新", alarm.get("context_memo", ""), "", alarm.get("character", default_char), days_ja, alarm.get("is_emergency", False), h, m, selected_ids[0])
        else: form_updates = ("アラーム追加", "", "", default_char, [], False, "08", "00", None)
    else: form_updates = ("アラーム追加", "", "", default_char, [], False, "08", "00", None)
    return (selected_ids, feedback_text) + form_updates

def toggle_selected_alarms_status(selected_ids: list, target_status: bool):
    if not selected_ids: gr.Warning("状態を変更するアラームが選択されていません。")
    else:
        current_alarms = alarm_manager.load_alarms()
        modified = any(a.get("id") in selected_ids and a.update({"enabled": target_status}) is None for a in current_alarms)
        if modified:
            alarm_manager.alarms_data_global = current_alarms; alarm_manager.save_alarms()
            gr.Info(f"{len(selected_ids)}件のアラームの状態を「{'有効' if target_status else '無効'}」に変更しました。")
    new_df_with_ids = render_alarms_as_dataframe(); return new_df_with_ids, get_display_df(new_df_with_ids)

def handle_delete_selected_alarms(selected_ids: list):
    if not selected_ids: gr.Warning("削除するアラームが選択されていません。")
    else:
        for sid in selected_ids: alarm_manager.delete_alarm(str(sid))
    new_df_with_ids = render_alarms_as_dataframe(); return new_df_with_ids, get_display_df(new_df_with_ids)

def handle_add_or_update_alarm(editing_id, h, m, char, theme, prompt, days_ja, is_emergency):
    from tools.alarm_tools import set_personal_alarm
    context = theme or prompt or "時間になりました"; days_en = [DAY_MAP_JA_TO_EN.get(d) for d in days_ja if d in DAY_MAP_JA_TO_EN]
    if editing_id: alarm_manager.delete_alarm(editing_id); gr.Info(f"アラームID:{editing_id}を更新します。")
    set_personal_alarm.func(time=f"{h}:{m}", context_memo=context, character_name=char, days=days_en, date=None, is_emergency=is_emergency)
    new_df_with_ids, all_chars = render_alarms_as_dataframe(), character_manager.get_character_list()
    default_char = all_chars[0] if all_chars else "Default"
    return new_df_with_ids, get_display_df(new_df_with_ids), "アラーム追加", "", "", gr.update(choices=all_chars, value=default_char), [], False, "08", "00", None

def handle_timer_submission(timer_type, duration, work, brk, cycles, char, work_theme, brk_theme, api_key_name, normal_theme):
    if not char or not api_key_name: return "エラー：キャラクターとAPIキーを選択してください。"
    try:
        timer = UnifiedTimer(timer_type, float(duration or 0), float(work or 0), float(brk or 0), int(cycles or 0), char, work_theme, brk_theme, api_key_name, normal_theme=normal_theme)
        timer.start(); gr.Info(f"{timer_type}を開始しました。"); return f"{timer_type}を開始しました。"
    except Exception as e: return f"タイマー開始エラー: {e}"

def handle_rag_update_button_click(character_name: str, api_key_name: str):
    if not character_name or not api_key_name: gr.Warning("キャラクターとAPIキーを選択してください。"); return
    api_key = config_manager.API_KEYS.get(api_key_name)
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
    api_key = config_manager.API_KEYS.get(api_key_name)
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
    if not selected_message: gr.Warning("再生するメッセージが選択されていません。"); return None
    raw_text = utils.extract_raw_text_from_html(selected_message.get("content"))
    text_to_speak = utils.remove_thoughts_from_text(raw_text)
    if not text_to_speak: gr.Info("このメッセージには音声で再生できるテキストがありません。"); return None
    effective_settings = config_manager.get_effective_settings(character_name)
    voice_id, voice_style_prompt = effective_settings.get("voice_id", "vindemiatrix"), effective_settings.get("voice_style_prompt", "")
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key: gr.Warning(f"APIキー '{api_key_name}' が見つかりません。"); return None
    from audio_manager import generate_audio_from_text
    gr.Info(f"「{character_name}」の声で音声を生成しています...")
    audio_filepath = generate_audio_from_text(text_to_speak, api_key, voice_id, voice_style_prompt)
    if audio_filepath: gr.Info("再生します。"); return audio_filepath
    else: gr.Error("音声の生成に失敗しました。"); return None

def handle_voice_preview(selected_voice_name: str, voice_style_prompt: str, text_to_speak: str, api_key_name: str):
    if not selected_voice_name or not text_to_speak or not api_key_name: gr.Warning("声、テキスト、APIキーがすべて選択されている必要があります。"); return None
    voice_id = next((key for key, value in config_manager.SUPPORTED_VOICES.items() if value == selected_voice_name), None)
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not voice_id or not api_key: gr.Warning("声またはAPIキーが無効です。"); return None
    from audio_manager import generate_audio_from_text
    gr.Info(f"声「{selected_voice_name}」で音声を生成しています...")
    audio_filepath = generate_audio_from_text(text_to_speak, api_key, voice_id, voice_style_prompt)
    if audio_filepath: gr.Info("プレビューを再生します。"); return audio_filepath
    else: gr.Error("音声の生成に失敗しました。"); return None

def handle_generate_or_regenerate_scenery_image(character_name: str, api_key_name: str) -> Optional[str]:
    if not character_name or not api_key_name:
        gr.Warning("キャラクターとAPIキーを選択してください。")
        return None

    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key:
        gr.Warning(f"APIキー '{api_key_name}' が見つかりません。")
        return None

    location_id = utils.get_current_location(character_name)
    scenery_cache = utils.load_scenery_cache(character_name)
    scenery_text = scenery_cache.get("scenery_text")

    if not location_id or not scenery_text:
        gr.Warning("生成の元となる場所の情報または情景描写が見つかりません。")
        return None

    gr.Info(f"「{location_id}」の情景画像を生成/更新しています...")
    prompt = f"A photorealistic, atmospheric, wide-angle landscape painting of the following scene. Do not include any people, characters, text, or watermarks. Style: cinematic, detailed, epic. Scene: {scenery_text}"

    now = datetime.datetime.now()
    filename = f"{location_id}_{utils.get_season(now.month)}_{utils.get_time_of_day(now.hour)}.png"
    save_dir = os.path.join(constants.CHARACTERS_DIR, character_name, "spaces", "images")
    final_save_path = os.path.join(save_dir, filename)

    result = generate_image_tool_func.func(prompt=prompt, character_name=character_name, api_key=api_key)

    if "Generated Image:" in result:
        generated_path = result.replace("[Generated Image: ", "").replace("]", "").strip()
        if os.path.exists(generated_path):
            if os.path.exists(final_save_path):
                os.remove(final_save_path)
            os.rename(generated_path, final_save_path)
            print(f"--- 情景画像を再生成し、保存しました: {final_save_path} ---")
            gr.Info("画像を生成/更新しました。")
            return final_save_path
        else:
            gr.Error("画像の生成には成功しましたが、一時ファイルの特定に失敗しました。")
            return None
    else:
        gr.Error(f"画像の生成/更新に失敗しました。AIの応答: {result}")
        return None

#
# ui_handlers.py の一番下に追加したワールド・ビルダー新規作成用の関数群を、このブロックで置き換えてください
#

def handle_add_item_button_click(item_type: str, selected_area_id: Optional[str]):
    """「エリアを追加」「部屋を追加」ボタンが押された時の処理"""
    if item_type == "room" and not selected_area_id:
        gr.Warning("部屋を追加するには、まず「エリア」を選択してください。")
        # 戻り値の数をoutputsの6つに合わせる
        return gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update()

    # 戻り値の数をoutputsの6つに合わせる
    return (
        gr.update(visible=False),  # area_selector
        gr.update(visible=False),  # room_selector
        gr.update(visible=False),  # edit_button_wb
        gr.update(visible=True),   # new_item_form_wb
        item_type,                 # new_item_type_wb (hidden state)
        f"#### 新しい{ 'エリア' if item_type == 'area' else '部屋' }の作成" # new_item_form_title_wb
    )

def handle_cancel_add_button_click():
    """新規作成フォームの「キャンセル」ボタンが押された時の処理。戻り値の数をoutputsの6つに合わせる。"""
    return (
        gr.update(visible=True),   # area_selector
        gr.update(visible=True),   # room_selector
        gr.update(visible=False),  # edit_button_wb (選択状態ではないので非表示)
        gr.update(visible=False),  # new_item_form_wb
        "",                        # clear new_item_id
        ""                         # clear new_item_name
    )

def handle_confirm_add_button_click(character_name: str, world_data: Dict, selected_area_id: Optional[str], item_type: str, new_id: str, new_name: str):
    """新規作成フォームの「決定」ボタンが押された時の処理。戻り値の数をoutputsの7つに合わせる。"""
    # --- 入力検証 ---
    if not new_id or not new_name:
        gr.Warning("IDと表示名の両方を入力してください。")
        return world_data, gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update()
    if not re.match(r"^[a-zA-Z0-9_]+$", new_id):
        gr.Warning("IDには半角英数字とアンダースコア(_)のみ使用できます。")
        return world_data, gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update()

    # --- IDの重複チェック ---
    if item_type == "area" and new_id in world_data:
        gr.Warning(f"ID '{new_id}' は既に使用されています。別のIDを指定してください。")
        return world_data, gr.update(), gr.update(), gr.update(), gr.update(), new_id, new_name
    if item_type == "room" and selected_area_id and new_id in world_data.get(selected_area_id, {}):
        gr.Warning(f"エリア '{selected_area_id}' 内でID '{new_id}' は既に使用されています。")
        return world_data, gr.update(), gr.update(), gr.update(), gr.update(), new_id, new_name

    # --- データ更新 ---
    if item_type == "area":
        world_data[new_id] = {"name": new_name, "description": "新しいエリアです。"}
    elif item_type == "room" and selected_area_id:
        if selected_area_id not in world_data: world_data[selected_area_id] = {}
        world_data[selected_area_id][new_id] = {"name": new_name, "description": "新しい部屋です。"}

    from world_builder import save_world_data
    save_world_data(character_name, world_data)

    area_choices, _ = get_choices_from_world_data(world_data)
    gr.Info(f"新しい{ 'エリア' if item_type == 'area' else '部屋' }「{new_name}」を追加しました。")

    # 戻り値の数をoutputsの7つに合わせる
    return (
        world_data,
        gr.update(choices=area_choices, value=new_id if item_type == 'area' else selected_area_id),
        gr.update(choices=get_choices_from_world_data(world_data)[1].get(new_id if item_type == 'area' else selected_area_id, []), value=new_id if item_type == 'room' else None),
        gr.update(visible=True),   # edit_button_wb - 項目が選択された状態になるので表示
        gr.update(visible=False),  # new_item_form_wb
        "",                        # clear new_item_id
        ""                         # clear new_item_name
    )
