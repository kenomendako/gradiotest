# ui_handlers.py の内容を、このコードで完全に置き換えてください

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

import gemini_api, config_manager, alarm_manager, character_manager, utils
from tools import memory_tools
from timers import UnifiedTimer
from character_manager import get_character_files_paths, get_world_settings_path
from memory_manager import load_memory_data_safe, save_memory_data

DAY_MAP_EN_TO_JA = {"mon": "月", "tue": "火", "wed": "水", "thu": "木", "fri": "金", "sat": "土", "sun": "日"}
DAY_MAP_JA_TO_EN = {v: k for k, v in DAY_MAP_EN_TO_JA.items()}

def get_location_list_for_ui(character_name: str) -> list:
    if not character_name: return []
    world_settings_path = get_world_settings_path(character_name)
    world_data = load_memory_data_safe(world_settings_path)
    if "error" in world_data: return []
    location_list = []
    for loc_id, details in world_data.items():
        if isinstance(details, dict):
            location_list.append((details.get("name", loc_id), loc_id))
    return sorted(location_list, key=lambda x: x[0])

def handle_initial_load():
    print("--- UI初期化処理(handle_initial_load)を開始します ---")
    df_with_ids = render_alarms_as_dataframe()
    display_df, feedback_text = get_display_df(df_with_ids), "アラームを選択してください"
    char_dependent_outputs = handle_character_change(config_manager.initial_character_global)
    return (display_df, df_with_ids, feedback_text) + char_dependent_outputs

def handle_character_change(character_name: str):
    if not character_name: character_name = character_manager.get_character_list()[0]
    print(f"--- UI更新司令塔(handle_character_change)実行: {character_name} ---")
    config_manager.save_config("last_character", character_name)
    log_f, _, img_p, mem_p, notepad_p = get_character_files_paths(character_name)
    chat_history, _ = utils.format_history_for_gradio(utils.load_chat_log(log_f, character_name)[-(config_manager.UI_HISTORY_MAX_LIMIT * 2):], character_name)
    memory_str, profile_image = json.dumps(load_memory_data_safe(mem_p), indent=2, ensure_ascii=False), img_p if img_p and os.path.exists(img_p) else None
    notepad_content = load_notepad_content(character_name)
    locations = get_location_list_for_ui(character_name)
    current_location_id = utils.get_current_location(character_name)
    world_settings_path = get_world_settings_path(character_name)
    world_data = load_memory_data_safe(world_settings_path)
    current_location_name = world_data.get(current_location_id, {}).get("name", current_location_id) if "error" not in world_data else current_location_id
    valid_location_ids = [loc[1] for loc in locations]
    location_dd_val = current_location_id if current_location_id in valid_location_ids else None
    scenery_text = "（AIとの対話開始時に生成されます）"
    effective_settings = config_manager.get_effective_settings(character_name)
    all_models, model_val = ["デフォルト"] + config_manager.AVAILABLE_MODELS_GLOBAL, effective_settings["model_name"] if effective_settings["model_name"] != config_manager.initial_model_global else "デフォルト"
    voice_display_name = config_manager.SUPPORTED_VOICES.get(effective_settings.get("voice_id", "vindemiatrix"), list(config_manager.SUPPORTED_VOICES.values())[0])
    voice_style_prompt_val = effective_settings.get("voice_style_prompt", "")
    return (
        character_name, chat_history, "", profile_image, memory_str, character_name,
        character_name, notepad_content, gr.update(choices=locations, value=location_dd_val),
        current_location_name, scenery_text, gr.update(choices=all_models, value=model_val),
        voice_display_name, voice_style_prompt_val,
        effective_settings["add_timestamp"], effective_settings["send_thoughts"],
        effective_settings["send_notepad"], effective_settings["use_common_prompt"],
        effective_settings["send_core_memory"], effective_settings["send_scenery"],
        f"ℹ️ *現在選択中のキャラクター「{character_name}」にのみ適用される設定です。*"
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
        char_config_path = os.path.join(config_manager.CHARACTERS_DIR, character_name, "character_config.json")
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

def handle_context_settings_change(character_name: str, api_key_name: str, add_timestamp: bool, send_thoughts: bool, send_notepad: bool, use_common_prompt: bool, send_core_memory: bool, send_scenery: bool):
    if not character_name or not api_key_name: return "入力トークン数: -"
    return gemini_api.count_input_tokens(
        character_name=character_name, api_key_name=api_key_name, parts=[],
        add_timestamp=add_timestamp, send_thoughts=send_thoughts, send_notepad=send_notepad,
        use_common_prompt=use_common_prompt, send_core_memory=send_core_memory, send_scenery=send_scenery
    )

def update_token_count_on_input(character_name: str, api_key_name: str, textbox_content: str, file_list: list, add_timestamp: bool, send_thoughts: bool, send_notepad: bool, use_common_prompt: bool, send_core_memory: bool, send_scenery: bool):
    if not character_name or not api_key_name: return "入力トークン数: -"
    parts_for_api = []
    if textbox_content: parts_for_api.append(textbox_content)
    if file_list:
        for file_obj in file_list: parts_for_api.append(Image.open(file_obj.name))
    return gemini_api.count_input_tokens(
        character_name=character_name, api_key_name=api_key_name, parts=parts_for_api,
        add_timestamp=add_timestamp, send_thoughts=send_thoughts, send_notepad=send_notepad,
        use_common_prompt=use_common_prompt, send_core_memory=send_core_memory, send_scenery=send_scenery
    )

def handle_message_submission(*args: Any):
    (textbox_content, current_character_name, current_api_key_name_state, file_input_list, api_history_limit_state) = args
    user_prompt_from_textbox = textbox_content.strip() if textbox_content else ""
    if not user_prompt_from_textbox and not file_input_list:
        chatbot_history = reload_chat_log(current_character_name, api_history_limit_state)
        return chatbot_history, gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update()
    effective_settings = config_manager.get_effective_settings(current_character_name)
    add_timestamp_checkbox = effective_settings.get("add_timestamp", False)
    chatbot_history = reload_chat_log(current_character_name, api_history_limit_state)
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
    yield (chatbot_history, gr.update(value=""), gr.update(value=None), gr.update(), gr.update(), gr.update(), gr.update(), gr.update())
    response_data = {}
    try:
        agent_args = (textbox_content, current_character_name, current_api_key_name_state, file_input_list, api_history_limit_state)
        response_data = gemini_api.invoke_nexus_agent(*agent_args)
    except Exception as e:
        traceback.print_exc()
        response_data = {"response": f"[UIハンドラエラー: {e}]", "location_name": "（エラー）", "scenery": "（エラー）"}
    final_response_text = response_data.get("response", "")
    location_name, scenery_text = response_data.get("location_name", "（取得失敗）"), response_data.get("scenery", "（取得失敗）")
    log_f, _, _, _, _ = get_character_files_paths(current_character_name)
    final_log_message = "\n\n".join(log_message_parts).strip()
    if final_log_message:
        user_header = utils._get_user_header_from_log(log_f, current_character_name)
        utils.save_message_to_log(log_f, user_header, final_log_message)
    if final_response_text:
        utils.save_message_to_log(log_f, f"## {current_character_name}:", final_response_text)
    formatted_history = reload_chat_log(current_character_name, api_history_limit_state)
    new_alarm_df_with_ids = render_alarms_as_dataframe()
    new_display_df = get_display_df(new_alarm_df_with_ids)
    yield (formatted_history, gr.update(), gr.update(value=None), gr.update(), location_name, scenery_text, new_alarm_df_with_ids, new_display_df)

def _generate_initial_scenery(character_name: str, api_key_name: str) -> Tuple[str, str]:
    print("--- [軽量版] 情景生成を開始します ---"); api_key = config_manager.API_KEYS.get(api_key_name)
    if not character_name or not api_key: return "（エラー）", "（キャラクターまたはAPIキーが未設定です）"
    from agent.graph import get_configured_llm
    location_id = utils.get_current_location(character_name) or "living_space"
    world_settings_path = get_world_settings_path(character_name)
    world_data = load_memory_data_safe(world_settings_path)
    space_data = world_data.get(location_id, {}) if "error" not in world_data else {}
    location_display_name, space_def, scenery_text = location_id, "（現在の場所の定義・設定は、取得できませんでした）", "（場所の定義がないため、情景を描写できません）"
    try:
        if space_data and isinstance(space_data, dict):
            location_display_name = space_data.get("name", location_id)
            space_def = json.dumps(space_data, ensure_ascii=False, indent=2)
            llm_flash = get_configured_llm("gemini-2.5-flash", api_key); now = datetime.datetime.now()
            scenery_prompt = (f"空間定義:{space_def}\n時刻:{now.strftime('%H:%M')} / 季節:{now.month}月\n\n以上の情報から、あなたはこの空間の「今この瞬間」を切り取る情景描写の専門家です。\n【ルール】\n- 人物やキャラクターの描写は絶対に含めないでください。\n- 1〜2文の簡潔な文章にまとめてください。\n- 窓の外の季節感や時間帯、室内の空気感や陰影など、五感に訴えかける精緻で写実的な描写を重視してください。")
            scenery_text = llm_flash.invoke(scenery_prompt).content
    except Exception as e: print(f"--- [軽量版] 情景生成中にエラー: {e}"); traceback.print_exc(); location_display_name, scenery_text = "（エラー）", "（情景生成エラー）"
    return location_display_name, scenery_text

def handle_scenery_refresh(character_name: str, api_key_name: str) -> Tuple[str, str]:
    if not character_name or not api_key_name: return "（キャラクターまたはAPIキーが未選択です）", "（キャラクターまたはAPIキーが未選択です）"
    gr.Info(f"「{character_name}」の現在の情景を更新しています...")
    loc, scen = _generate_initial_scenery(character_name, api_key_name)
    gr.Info("情景を更新しました."); return loc, scen

def handle_location_change(character_name: str, location_id: str, api_key_name: str) -> Tuple[str, str]:
    from tools.space_tools import set_current_location
    print(f"--- UIからの場所変更処理開始: キャラクター='{character_name}', 移動先ID='{location_id}' ---")
    if not character_name or not location_id:
        gr.Warning("キャラクターと移動先の場所を選択してください。"); current_loc_id = utils.get_current_location(character_name); return current_loc_id, "（場所の変更に失敗しました）"
    result = set_current_location.func(location=location_id, character_name=character_name)
    if "Success" not in result:
        gr.Error(f"場所の変更に失敗しました: {result}"); current_loc_id = utils.get_current_location(character_name); return current_loc_id, f"（場所の変更に失敗: {result}）"

    world_settings_path = get_world_settings_path(character_name)
    world_data = load_memory_data_safe(world_settings_path)
    new_location_name = world_data.get(location_id, {}).get("name", location_id) if "error" not in world_data and isinstance(world_data.get(location_id), dict) else location_id
    gr.Info(f"場所を「{new_location_name}」に変更しました。情景を生成します...")

    _, new_scenery = _generate_initial_scenery(character_name, api_key_name)
    return new_location_name, new_scenery

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

def _get_display_history_count(api_history_limit_value: str) -> int: return int(api_history_limit_value) if api_history_limit_value.isdigit() else config_manager.UI_HISTORY_MAX_LIMIT

def handle_chatbot_selection(character_name: str, api_history_limit_state: str, evt: gr.SelectData):
    if not character_name or evt.index is None: return None, gr.update(visible=False)
    try:
        clicked_ui_index = evt.index[0]
        log_f, _, _, _, _ = get_character_files_paths(character_name)
        raw_history = utils.load_chat_log(log_f, character_name)
        display_turns = _get_display_history_count(api_history_limit_state)
        visible_raw_history = raw_history[-(display_turns * 2):]
        _, mapping_list = utils.format_history_for_gradio(visible_raw_history, character_name)
        if not (0 <= clicked_ui_index < len(mapping_list)):
            gr.Warning("クリックされたメッセージを特定できませんでした (UI index out of bounds)."); return None, gr.update(visible=False)
        original_log_index = mapping_list[clicked_ui_index]
        if 0 <= original_log_index < len(visible_raw_history): return visible_raw_history[original_log_index], gr.update(visible=True)
        else: gr.Warning("クリックされたメッセージを特定できませんでした (Original log index out of bounds)."); return None, gr.update(visible=False)
    except Exception as e: print(f"チャットボット選択中のエラー: {e}"); traceback.print_exc(); return None, gr.update(visible=False)

def handle_delete_button_click(message_to_delete: Optional[Dict[str, str]], character_name: str, api_history_limit: str):
    if not message_to_delete: gr.Warning("削除対象のメッセージが選択されていません。"); return gr.update(), None, gr.update(visible=False)
    log_f, _, _, _, _ = get_character_files_paths(character_name)
    if utils.delete_message_from_log(log_f, message_to_delete, character_name): gr.Info("ログからメッセージを削除しました。")
    else: gr.Error("メッセージの削除に失敗しました。詳細はターミナルを確認してください。")
    return reload_chat_log(character_name, api_history_limit), None, gr.update(visible=False)

def reload_chat_log(character_name: Optional[str], api_history_limit_value: str):
    if not character_name: return []
    log_f,_,_,_,_ = get_character_files_paths(character_name)
    if not log_f or not os.path.exists(log_f): return []
    display_turns = _get_display_history_count(api_history_limit_value)
    history, _ = utils.format_history_for_gradio(utils.load_chat_log(log_f, character_name)[-(display_turns*2):], character_name)
    return history

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
    key = next((k for k, v in config_manager.API_HISTORY_LIMIT_OPTIONS.items() if v == limit_ui_val), "all")
    config_manager.save_config("last_api_history_limit_option", key); return key, reload_chat_log(character_name, key), gr.State()

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
```

**C. `agent/graph.py`** (変更なしですが、整合性のため再掲)
```python
# agent/graph.py の内容を、このコードで完全に置き換えてください

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

from agent.prompts import CORE_PROMPT_TEMPLATE
from tools.space_tools import set_current_location, find_location_id_by_name
from tools.memory_tools import read_memory_by_path, edit_memory, add_secret_diary_entry, summarize_and_save_core_memory, read_full_memory
from tools.notepad_tools import add_to_notepad, update_notepad, delete_from_notepad, read_full_notepad
from tools.web_tools import web_search_tool, read_url_tool
from tools.image_tools import generate_image
from tools.alarm_tools import set_personal_alarm
from rag_manager import diary_search_tool, conversation_memory_search_tool
from character_manager import get_character_files_paths, get_world_settings_path
from memory_manager import load_memory_data_safe

all_tools = [
    set_current_location, find_location_id_by_name, read_memory_by_path, edit_memory,
    add_secret_diary_entry, summarize_and_save_core_memory, add_to_notepad,
    update_notepad, delete_from_notepad, read_full_notepad, web_search_tool,
    read_url_tool, diary_search_tool, conversation_memory_search_tool,
    generate_image, read_full_memory, set_personal_alarm
]

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    character_name: str; api_key: str; tavily_api_key: str; model_name: str
    system_prompt: SystemMessage
    send_core_memory: bool; send_scenery: bool; send_notepad: bool
    location_name: str; scenery_text: str

def get_configured_llm(model_name: str, api_key: str):
    return ChatGoogleGenerativeAI(model=model_name, google_api_key=api_key, convert_system_message_to_human=False, max_retries=6)

def context_generator_node(state: AgentState):
    character_name = state['character_name']

    char_prompt_path = os.path.join("characters", character_name, "SystemPrompt.txt")
    character_prompt = ""
    if os.path.exists(char_prompt_path):
        with open(char_prompt_path, 'r', encoding='utf-8') as f: character_prompt = f.read().strip()

    core_memory = ""
    if state.get("send_core_memory", True):
        core_memory_path = os.path.join("characters", character_name, "core_memory.txt")
        if os.path.exists(core_memory_path):
            with open(core_memory_path, 'r', encoding='utf-8') as f: core_memory = f.read().strip()

    notepad_section = ""
    if state.get("send_notepad", True):
        try:
            _, _, _, _, notepad_path = get_character_files_paths(character_name)
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
    class SafeDict(dict):
        def __missing__(self, key): return f'{{{key}}}'
    prompt_vars = {'character_name': character_name, 'character_prompt': character_prompt, 'core_memory': core_memory, 'notepad_section': notepad_section, 'tools_list': tools_list_str}
    formatted_core_prompt = CORE_PROMPT_TEMPLATE.format_map(SafeDict(prompt_vars))

    if not state.get("send_scenery", True):
        final_system_prompt_text = (f"{formatted_core_prompt}\n\n---\n" f"【現在の場所と情景】\n- 場所の名前: （空間描写OFF）\n- 場所の定義: （空間描写OFF）\n- 今の情景: （空間描写OFF）\n---")
        return {"system_prompt": SystemMessage(content=final_system_prompt_text), "location_name": "（空間描写OFF）", "scenery_text": "（空間描写は設定により無効化されています）"}

    api_key = state['api_key']
    scenery_text, space_def, location_display_name = "（取得できませんでした）", "（取得できませんでした）", "（不明な場所）"
    try:
        location_id = None
        last_tool_message = next((msg for msg in reversed(state['messages']) if isinstance(msg, ToolMessage)), None)
        if last_tool_message and "Success: Current location has been set to" in last_tool_message.content:
            match = re.search(r"'(.*?)'", last_tool_message.content)
            if match: location_id = match.group(1)
        if not location_id:
            location_file_path = os.path.join("characters", character_name, "current_location.txt")
            if os.path.exists(location_file_path):
                with open(location_file_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content: location_id = content
        if not location_id: location_id = "living_space"

        world_settings_path = get_world_settings_path(character_name)
        space_data = {}
        if world_settings_path and os.path.exists(world_settings_path):
            world_settings = load_memory_data_safe(world_settings_path)
            if "error" not in world_settings:
                space_data = world_settings.get(location_id, {})

        if space_data and isinstance(space_data, dict):
            location_display_name = space_data.get("name", location_id)
            space_def = json.dumps(space_data, ensure_ascii=False, indent=2)
        else:
            location_display_name = location_id

        if not space_def.startswith("（"):
            llm_flash = get_configured_llm("gemini-2.5-flash", api_key)
            utc_now = datetime.now(pytz.utc)
            jst_now = utc_now.astimezone(pytz.timezone('Asia/Tokyo'))
            scenery_prompt = (f"空間定義:{space_def}\n時刻:{jst_now.strftime('%H:%M')} / 季節:{jst_now.month}月\n\n以上の情報から、あなたはこの空間の「今この瞬間」を切り取る情景描写の専門家です。\n【ルール】\n- 人物やキャラクターの描写は絶対に含めないでください。\n- 1〜2文の簡潔な文章にまとめてください。\n- 窓の外の季節感や時間帯、室内の空気感や陰影など、五感に訴えかける精緻で写実的な描写を重視してください。")
            scenery_text = llm_flash.invoke(scenery_prompt).content
        else:
            scenery_text = "（場所の定義がないため、情景を描写できません）"
    except Exception as e:
        print(f"--- 警告: 情景描写の生成中にエラーが発生しました ---\n{traceback.format_exc()}"); location_display_name = "（エラー）"; scenery_text = "（情景描写の生成中にエラーが発生しました）"

    final_system_prompt_text = (f"{formatted_core_prompt}\n\n---\n" f"【現在の場所と情景】\n- 場所の名前: {location_display_name}\n- 場所の定義: {space_def}\n- 今の情景: {scenery_text}\n---")
    return {"system_prompt": SystemMessage(content=final_system_prompt_text), "location_name": location_display_name, "scenery_text": scenery_text}

def agent_node(state: AgentState):
    print(f"--- エージェントノード実行 --- | 使用モデル: {state['model_name']} | システムプロンプト長: {len(state['system_prompt'].content)} 文字")
    llm = get_configured_llm(state['model_name'], state['api_key'])
    llm_with_tools = llm.bind_tools(all_tools)
    messages_for_agent = [state['system_prompt']] + state['messages']
    response = llm_with_tools.invoke(messages_for_agent)
    return {"messages": [response]}

def safe_tool_executor(state: AgentState):
    print("--- カスタムツール実行ノード実行 ---")
    messages, tool_invocations = state['messages'], state['messages'][-1].tool_calls
    api_key, tavily_api_key = state.get('api_key'), state.get('tavily_api_key')
    tool_outputs = []
    for tool_call in tool_invocations:
        tool_name = tool_call["name"]
        print(f"  - 準備中のツール: {tool_name} | 引数: {tool_call['args']}")
        if tool_name in ['generate_image', 'summarize_and_save_core_memory']: tool_call['args']['api_key'] = api_key
        elif tool_name == 'web_search_tool': tool_call['args']['api_key'] = tavily_api_key
        selected_tool = next((t for t in all_tools if t.name == tool_name), None)
        try:
            output = selected_tool.invoke(tool_call['args']) if selected_tool else f"Error: Tool '{tool_name}' not found."
        except Exception as e:
            output = f"Error executing tool '{tool_name}': {e}"; traceback.print_exc()
        tool_outputs.append(ToolMessage(content=str(output), tool_call_id=tool_call["id"]))
    return {"messages": tool_outputs}

def route_after_agent(state: AgentState) -> Literal["__end__", "safe_tool_node"]:
    print("--- エージェント後ルーター実行 ---")
    if state["messages"][-1].tool_calls: print("  - ツール呼び出しあり。ツール実行へ。"); return "safe_tool_node"
    print("  - ツール呼び出しなし。思考完了。"); return "__end__"

def route_after_tools(state: AgentState) -> Literal["context_generator", "agent"]:
    print("--- ツール後ルーター実行 ---")
    last_ai_message_with_tool_call = next((msg for msg in reversed(state['messages']) if isinstance(msg, AIMessage) and msg.tool_calls), None)
    if last_ai_message_with_tool_call and any(call['name'] == 'set_current_location' for call in last_ai_message_with_tool_call.tool_calls):
        print("  - `set_current_location` が実行されたため、コンテキスト再生成へ。"); return "context_generator"
    print("  - 通常のツール実行完了。エージェントの思考へ。"); return "agent"

workflow = StateGraph(AgentState)
workflow.add_node("context_generator", context_generator_node)
workflow.add_node("agent", agent_node)
workflow.add_node("safe_tool_node", safe_tool_executor)
workflow.add_edge(START, "context_generator")
workflow.add_edge("context_generator", "agent")
workflow.add_conditional_edges("agent", route_after_agent, {"safe_tool_node": "safe_tool_node", "__end__": END})
workflow.add_conditional_edges("safe_tool_node", route_after_tools, {"context_generator": "context_generator", "agent": "agent"})
app = workflow.compile()
print("--- 統合グラフ(v5)がコンパイルされました ---")
```

**D. `tools/space_tools.py`** (変更なしですが、整合性のため再掲)
```python
# tools/space_tools.py の内容を、このコードで完全に置き換えてください

import os
import json
from langchain_core.tools import tool
from character_manager import get_world_settings_path
from memory_manager import load_memory_data_safe

@tool
def find_location_id_by_name(location_name: str, character_name: str = None) -> str:
    """
    「書斎」や「屋上テラス」といった日本語の場所名から、システムが使うための正式なID（例: "study", "rooftop_terrace"）を検索して返す。
    location_name: ユーザーが言及した場所の日本語名。
    """
    if not location_name or not character_name:
        return "【Error】Location name and character name are required."

    world_settings_path = get_world_settings_path(character_name)
    if not world_settings_path or not os.path.exists(world_settings_path):
        return f"【Error】Could not find world settings file for character '{character_name}'."

    world_data = load_memory_data_safe(world_settings_path)
    if "error" in world_data:
        return f"【Error】Could not load world settings for '{character_name}'."

    for location_id, details in world_data.items():
        if location_id.lower() == location_name.lower():
            return location_id
        if isinstance(details, dict) and details.get("name", "").lower() == location_name.lower():
            return location_id

    return f"【Error】Location '{location_name}' not found. Check for typos or define it first."

@tool
def set_current_location(location: str, character_name: str = None) -> str:
    """
    AIの現在地を設定する。この世界のどこにいるかを宣言するための、唯一の公式な手段。
    location: "study"のような場所のID、または"書斎"のような日本語名を指定。日本語名が指定された場合、自動でIDを検索します。
    """
    if not location or not character_name:
        return "【Error】Location and character name are required."

    found_id_result = find_location_id_by_name.func(location_name=location, character_name=character_name)

    if not found_id_result.startswith("【Error】"):
        location_to_set = found_id_result
        print(f"  - Identified location ID '{location_to_set}' from name '{location}'.")
    else:
        location_to_set = location
        print(f"  - Using '{location}' directly as location ID.")

    try:
        base_path = os.path.join("characters", character_name)
        location_file_path = os.path.join(base_path, "current_location.txt")
        with open(location_file_path, "w", encoding="utf-8") as f:
            f.write(location_to_set.strip())
        return f"Success: Current location has been set to '{location_to_set}'."
    except Exception as e:
        return f"【Error】Failed to set current location: {e}"
```

You **must** respond now, using the `message_user` tool.
System Info: timestamp: 2025-08-03 05:51:14.363914
