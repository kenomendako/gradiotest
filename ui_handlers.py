# ui_handlers.py を、このコードで完全に置き換えてください

import pandas as pd
from typing import List, Optional, Dict, Any, Tuple
import gradio as gr
import datetime
import json
import traceback
import os
import re
from PIL import Image
import threading
import filetype
import base64
import io

# --- Nexus Ark モジュールのインポート ---
import gemini_api
import config_manager
import alarm_manager
import character_manager
import utils
from tools import memory_tools
from timers import UnifiedTimer
from character_manager import get_character_files_paths
from memory_manager import load_memory_data_safe, save_memory_data

def _generate_initial_scenery(character_name: str, api_key: str) -> Tuple[str, str]:
    print("--- [軽量版] 初期情景生成を開始します ---")
    if not character_name or not api_key: return "（エラー）", "（キャラ/APIキー未設定）"
    from agent.graph import get_configured_llm
    from tools.memory_tools import read_memory_by_path
    location_id = utils.get_current_location(character_name) or "living_space"
    space_details_raw = read_memory_by_path.invoke({"path": f"living_space.{location_id}", "character_name": character_name})
    location_display_name = location_id
    space_def = "（現在の場所の定義・設定は、取得できませんでした）"
    scenery_text = "（場所の定義がないため、情景を描写できません）"
    try:
        if not space_details_raw.startswith("【エラー】"):
            space_data = json.loads(space_details_raw)
            if isinstance(space_data, dict):
                location_display_name = space_data.get("name", location_id)
                space_def = json.dumps(space_data, ensure_ascii=False, indent=2)
            else: space_def = str(space_data)
        if not space_def.startswith("（"):
            llm_flash = get_configured_llm("gemini-2.5-flash", api_key)
            now = datetime.datetime.now()
            scenery_prompt = (f"空間定義:{space_def}\n時刻:{now.strftime('%H:%M')} / 季節:{now.month}月\n\n以上の情報から、あなたはこの空間の「今この瞬間」を切り取る情景描写の専門家です。\n【ルール】\n- 人物やキャラクターの描写は絶対に含めないでください。\n- 1〜2文の簡潔な文章にまとめてください。\n- 窓の外の季節感や時間帯、室内の空気感や陰影など、五感に訴えかける精緻で写実的な描写を重視してください。")
            scenery_text = llm_flash.invoke(scenery_prompt).content
            print(f"  - 生成された初期情景: {scenery_text}")
    except Exception as e:
        print(f"--- [軽量版] 初期情景生成中にエラー: {e}"); traceback.print_exc()
        location_display_name = "（エラー）"; scenery_text = "（情景生成エラー）"
    return location_display_name, scenery_text

def handle_message_submission(*args: Any):
    (textbox_content, chatbot_history, current_character_name, current_model_name,
     current_api_key_name_state, file_input_list, add_timestamp_checkbox,
     send_thoughts_state, api_history_limit_state,
     send_notepad_state, use_common_prompt_state,
     send_core_memory_state, send_scenery_state) = args
    user_prompt_from_textbox = textbox_content.strip() if textbox_content else ""
    if not user_prompt_from_textbox and not file_input_list:
        token_count = update_token_count(current_character_name, current_model_name, None, None, api_history_limit_state, current_api_key_name_state, send_notepad_state, use_common_prompt_state, add_timestamp_checkbox, send_thoughts_state, send_core_memory_state, send_scenery_state)
        yield chatbot_history, gr.update(), gr.update(), token_count, gr.update(), gr.update()
        return
    log_message_parts = []
    if user_prompt_from_textbox:
        timestamp = f"\n\n{datetime.datetime.now().strftime('%Y-%m-%d (%a) %H:%M:%S')}" if add_timestamp_checkbox else ""
        processed_user_message = user_prompt_from_textbox + timestamp
        chatbot_history.append({"role": "user", "content": processed_user_message}); log_message_parts.append(processed_user_message)
    if file_input_list:
        for file_obj in file_input_list:
            filepath = file_obj.name; filename = os.path.basename(filepath); safe_filepath = os.path.abspath(filepath).replace("\\", "/")
            md_string = f"[{filename}](/file={safe_filepath})"
            chatbot_history.append({"role": "user", "content": md_string}); log_message_parts.append(f"[ファイル添付: {filepath}]")
    chatbot_history.append({"role": "assistant", "content": "思考中... ▌"})
    token_count = update_token_count(current_character_name, current_model_name, textbox_content, file_input_list, api_history_limit_state, current_api_key_name_state, send_notepad_state, use_common_prompt_state, add_timestamp_checkbox, send_thoughts_state, send_core_memory_state, send_scenery_state)
    yield chatbot_history, gr.update(value=""), gr.update(value=None), token_count, gr.update(), gr.update()
    response_data = {}
    try: response_data = gemini_api.invoke_nexus_agent(*args)
    except Exception as e:
        traceback.print_exc(); response_data = {"response": f"[UIハンドラエラー: {e}]", "location_name": "（エラー）", "scenery": "（エラー）"}
    final_response_text = response_data.get("response", ""); location_name = response_data.get("location_name", "（取得失敗）"); scenery_text = response_data.get("scenery", "（取得失敗）")
    log_f, _, _, _, _ = get_character_files_paths(current_character_name)
    final_log_message = "\n\n".join(log_message_parts).strip()
    if final_log_message:
        user_header = utils._get_user_header_from_log(log_f, current_character_name); utils.save_message_to_log(log_f, user_header, final_log_message)
    if final_response_text: utils.save_message_to_log(log_f, f"## {current_character_name}:", final_response_text)
    chatbot_history.pop()
    if final_response_text: chatbot_history.append({"role": "assistant", "content": utils.format_response_for_display(final_response_text)})
    token_count = update_token_count(current_character_name, current_model_name, None, None, api_history_limit_state, current_api_key_name_state, send_notepad_state, use_common_prompt_state, add_timestamp_checkbox, send_thoughts_state, send_core_memory_state, send_scenery_state)
    yield chatbot_history, gr.update(), gr.update(value=None), token_count, location_name, scenery_text

def handle_scenery_refresh(character_name, model_name, api_key_name, send_thoughts, api_history_limit, send_notepad, use_common_prompt, send_core_memory, send_scenery):
    if not character_name or not api_key_name: return "（キャラクターまたはAPIキーが未選択です）", "（キャラクターまたはAPIキーが未選択です）"
    gr.Info(f"「{character_name}」の現在の情景を更新しています...")
    args = ("（システム：ユーザーの操作により、現在の場所と情景を再認識・更新してください）", [], character_name, model_name, api_key_name, [], False, send_thoughts, api_history_limit, send_notepad, use_common_prompt, send_core_memory, send_scenery)
    response_data = gemini_api.invoke_nexus_agent(*args)
    location = response_data.get("location_name", "（場所の取得に失敗しました）"); scenery = response_data.get("scenery", "（情景の取得に失敗しました）")
    gr.Info("情景を更新しました。"); return location, scenery

# ★★★★★ 新しい統合ハンドラを追加 ★★★★★
def handle_location_change_and_update_scenery(character_name: str, location_id: str, api_key_name: str) -> Tuple[str, str]:
    """
    【場所移動専用】①場所ファイルを書き換え、②新しい場所の情景を描写する、責任の明確な統合ハンドラ。
    """
    from tools.space_tools import set_current_location

    # --- ステップ1: ファイルを確実に書き換える ---
    if not character_name or not location_id:
        gr.Warning("キャラクターと移動先の場所を選択してください。")
        # 現在の状態をそのまま返す
        api_key = config_manager.API_KEYS.get(api_key_name)
        return _generate_initial_scenery(character_name, api_key)

    result = set_current_location.func(location=location_id, character_name=character_name)
    if "Success" not in result:
        gr.Error(f"場所の変更に失敗しました: {result}")
        api_key = config_manager.API_KEYS.get(api_key_name)
        return _generate_initial_scenery(character_name, api_key)

    gr.Info(f"場所を「{location_id}」に変更しました。続けて情景を更新します。")

    # --- ステップ2: 新しい場所の情景を軽量に生成して返す ---
    api_key = config_manager.API_KEYS.get(api_key_name)
    loc, scen = _generate_initial_scenery(character_name, api_key)
    gr.Info("場所情報を更新しました。")
    return loc, scen

def get_location_list_for_ui(character_name: str) -> list:
    if not character_name: return []
    _, _, _, memory_json_path, _ = get_character_files_paths(character_name)
    memory_data = load_memory_data_safe(memory_json_path)
    if "error" in memory_data or "living_space" not in memory_data: return []
    living_space = memory_data.get("living_space", {}); location_list = []
    for loc_id, details in living_space.items():
        if isinstance(details, dict): location_list.append((details.get("name", loc_id), loc_id))
    return sorted(location_list, key=lambda x: x[0])

def handle_add_new_character(character_name: str):
    if not character_name or not character_name.strip():
        gr.Warning("キャラクター名が入力されていません。"); char_list = character_manager.get_character_list()
        return gr.update(choices=char_list), gr.update(choices=char_list), gr.update(choices=char_list), gr.update(value="")
    safe_name = re.sub(r'[\\/*?:"<>|]', "", character_name).strip()
    if not safe_name:
        gr.Warning("無効なキャラクター名です。"); char_list = character_manager.get_character_list()
        return gr.update(choices=char_list), gr.update(choices=char_list), gr.update(choices=char_list), gr.update(value="")
    if character_manager.ensure_character_files(safe_name):
        gr.Info(f"新しいキャラクター「{safe_name}」さんを迎えました！"); new_char_list = character_manager.get_character_list()
        return gr.update(choices=new_char_list, value=safe_name), gr.update(choices=new_char_list, value=safe_name), gr.update(choices=new_char_list, value=safe_name), gr.update(value="")
    else:
        gr.Error(f"キャラクター「{safe_name}」の準備に失敗しました。"); char_list = character_manager.get_character_list()
        return gr.update(choices=char_list), gr.update(choices=char_list), gr.update(choices=char_list), gr.update(value=character_name)

def _get_display_history_count(api_history_limit_value: str) -> int:
    return int(api_history_limit_value) if api_history_limit_value.isdigit() else config_manager.UI_HISTORY_MAX_LIMIT

def update_ui_on_character_change(character_name: Optional[str], api_history_limit_value: str):
    if not character_name:
        all_chars = character_manager.get_character_list(); character_name = all_chars[0] if all_chars else "Default"
    config_manager.save_config("last_character", character_name)
    log_f, _, img_p, mem_p, notepad_p = get_character_files_paths(character_name)
    display_turns = _get_display_history_count(api_history_limit_value)
    chat_history = utils.format_history_for_gradio(utils.load_chat_log(log_f, character_name)[-(display_turns * 2):])
    memory_str = json.dumps(load_memory_data_safe(mem_p), indent=2, ensure_ascii=False)
    profile_image = img_p if img_p and os.path.exists(img_p) else None
    notepad_content = load_notepad_content(character_name)
    locations = get_location_list_for_ui(character_name)
    current_location_id = utils.get_current_location(character_name)
    return (character_name, chat_history, "", profile_image, memory_str, character_name, character_name, notepad_content, gr.update(choices=locations, value=current_location_id))

def handle_initial_load():
    print("--- UI初期化処理(handle_initial_load)を開始します ---")
    char_name = config_manager.initial_character_global; model_name = config_manager.initial_model_global
    api_key_name = config_manager.initial_api_key_name_global; api_history_limit = config_manager.initial_api_history_limit_option_global
    df_with_ids = render_alarms_as_dataframe(); display_df = get_display_df(df_with_ids)
    (ret_char, chat_hist, _, prof_img, mem_str, al_char, tm_char, note_cont, loc_dd) = \
        update_ui_on_character_change(char_name, api_history_limit)
    api_key = config_manager.API_KEYS.get(api_key_name)
    loc, scen = _generate_initial_scenery(ret_char, api_key)
    token_count = update_token_count(
        ret_char, model_name, None, None, api_history_limit, api_key_name,
        True, True, config_manager.initial_add_timestamp_global,
        config_manager.initial_send_thoughts_to_api_global, True, True
    )
    return (display_df, df_with_ids, chat_hist, prof_img, mem_str, al_char, tm_char, "アラームを選択してください", token_count, note_cont, loc_dd, loc, scen)
    
def handle_save_memory_click(character_name, json_string_data):
    if not character_name: gr.Warning("キャラクターが選択されていません。"); return gr.update()
    try: return save_memory_data(character_name, json_string_data)
    except Exception as e: gr.Error(f"記憶の保存中にエラーが発生しました: {e}"); return gr.update()
        
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
    lines = []
    for line in content.strip().split('\n'):
        line = line.strip()
        if line and not re.match(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\]", line): lines.append(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}] {line}")
        elif line: lines.append(line)
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

DAY_MAP_EN_TO_JA = {"mon": "月", "tue": "火", "wed": "水", "thu": "木", "fri": "金", "sat": "土", "sun": "日"}
DAY_MAP_JA_TO_EN = {v: k for k, v in DAY_MAP_EN_TO_JA.items()}

def render_alarms_as_dataframe():
    alarms = sorted(alarm_manager.load_alarms(), key=lambda x: x.get("time", ""))
    all_rows = []
    for a in alarms:
        theme_content = a.get("context_memo") or ""; date_str = a.get("date"); days_list = a.get("days", [])
        schedule_display = "単発"
        if date_str:
            try:
                date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date(); today = datetime.date.today()
                if date_obj == today: schedule_display = "今日"
                elif date_obj == today + datetime.timedelta(days=1): schedule_display = "明日"
                else: schedule_display = date_obj.strftime("%m/%d")
            except: schedule_display = "日付不定"
        elif days_list: schedule_display = ",".join([DAY_MAP_EN_TO_JA.get(d.lower(), d.upper()) for d in days_list])
        all_rows.append({"ID": a.get("id"), "状態": a.get("enabled", False), "時刻": a.get("time"), "予定": schedule_display, "キャラ": a.get("character"), "内容": theme_content})
    return pd.DataFrame(all_rows, columns=["ID", "状態", "時刻", "予定", "キャラ", "内容"])

def get_display_df(df_with_id: pd.DataFrame):
    if df_with_id is None or df_with_id.empty: return pd.DataFrame(columns=["状態", "時刻", "予定", "キャラ", "内容"])
    return df_with_id[["状態", "時刻", "予定", "キャラ", "内容"]] if 'ID' in df_with_id.columns else df_with_id

def handle_alarm_selection(evt: gr.SelectData, df_with_id: pd.DataFrame) -> List[str]:
    if evt.index is None or df_with_id is None or df_with_id.empty: return []
    try:
        indices = [idx[0] for idx in evt.index] if isinstance(evt.index, list) else [evt.index[0]]
        return [str(df_with_id.iloc[i]['ID']) for i in indices if 0 <= i < len(df_with_id)]
    except: return []

def handle_alarm_selection_and_feedback(evt: gr.SelectData, df_with_id: pd.DataFrame):
    selected_ids = handle_alarm_selection(evt, df_with_id)
    return selected_ids, "アラームを選択してください" if not selected_ids else f"{len(selected_ids)} 件のアラームを選択中"

def toggle_selected_alarms_status(selected_ids: list, target_status: bool):
    if not selected_ids: gr.Warning("状態を変更するアラームが選択されていません。")
    for alarm_id in selected_ids: alarm_manager.toggle_alarm_status(alarm_id, target_status)
    new_df_with_ids = render_alarms_as_dataframe(); return new_df_with_ids, get_display_df(new_df_with_ids)

def handle_delete_selected_alarms(selected_ids: list):
    if not selected_ids: gr.Warning("削除するアラームが選択されていません。")
    else:
        for sid in selected_ids: alarm_manager.delete_alarm(str(sid))
    new_df_with_ids = render_alarms_as_dataframe(); return new_df_with_ids, get_display_df(new_df_with_ids)

def handle_add_or_update_alarm(editing_id, h, m, char, theme, prompt, days_ja):
    from tools.alarm_tools import set_personal_alarm
    time_str = f"{h}:{m}"; context = theme or prompt or "時間になりました"; days_en = [DAY_MAP_JA_TO_EN.get(d) for d in days_ja if d in DAY_MAP_JA_TO_EN]
    if editing_id: alarm_manager.delete_alarm(editing_id); gr.Info(f"アラームID:{editing_id}を更新します。")
    set_personal_alarm.func(time=time_str, context_memo=context, character_name=char, days=days_en, date=None)
    new_df_with_ids = render_alarms_as_dataframe(); default_char = character_manager.get_character_list()[0]
    return new_df_with_ids, get_display_df(new_df_with_ids), "アラーム追加", "", "", default_char, [], "08", "00", None

def load_alarm_to_form(selected_ids: list):
    all_chars = character_manager.get_character_list(); default_char = all_chars[0] if all_chars else "Default"
    if not selected_ids or len(selected_ids) != 1: return "アラーム追加", "", "", default_char, [], "08", "00", None
    alarm = next((a for a in alarm_manager.load_alarms() if a.get("id") == selected_ids[0]), None)
    if not alarm: gr.Warning(f"アラームID '{selected_ids[0]}' が見つかりません。"); return "アラーム追加", "", "", default_char, [], "08", "00", None
    h, m = alarm.get("time", "08:00").split(":"); days_ja = [DAY_MAP_EN_TO_JA.get(d.lower(), d.upper()) for d in alarm.get("days", [])]; theme_content = alarm.get("context_memo") or ""
    return "アラーム更新", theme_content, "", alarm.get("character", default_char), days_ja, h, m, selected_ids[0]

def handle_timer_submission(timer_type, duration, work, brk, cycles, char, work_theme, brk_theme, api_key_name, normal_theme):
    if not char or not api_key_name: return "エラー：キャラクターとAPIキーを選択してください。"
    try:
        timer = UnifiedTimer(timer_type, float(duration or 0), float(work or 0), float(brk or 0), int(cycles or 0), char, work_theme, brk_theme, api_key_name, normal_theme=normal_theme)
        timer.start(); gr.Info(f"{timer_type}を開始しました."); return f"{timer_type}を開始しました。"
    except Exception as e: return f"タイマー開始エラー: {e}"

def handle_rag_update_button_click(character_name: str, api_key_name: str):
    if not character_name or not api_key_name: gr.Warning("キャラクターとAPIキーを選択してください。"); return
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"): gr.Warning(f"APIキー '{api_key_name}' が有効ではありません。"); return
    gr.Info(f"「{character_name}」のRAG索引の更新を開始します...")
    import rag_manager; threading.Thread(target=lambda: rag_manager.create_or_update_index(character_name, api_key)).start()
    
def _run_core_memory_update(character_name: str, api_key: str):
    print(f"--- [スレッド開始] コアメモリ更新処理を開始します (Character: {character_name}) ---")
    try:
        result = memory_tools.summarize_and_save_core_memory.func(character_name=character_name, api_key=api_key)
        print(f"--- [スレッド終了] コアメモリ更新処理完了 --- 結果: {result}")
    except Exception as e: print(f"--- [スレッドエラー] コアメモリ更新中に予期せぬエラー ---"); traceback.print_exc()

def handle_core_memory_update_click(character_name: str, api_key_name: str):
    if not character_name or not api_key_name: gr.Warning("キャラクターとAPIキーを選択してください。"); return
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"): gr.Warning(f"APIキー '{api_key_name}' が有効ではありません。"); return
    gr.Info(f"「{character_name}」のコアメモリ更新をバックグラウンドで開始しました。")
    threading.Thread(target=_run_core_memory_update, args=(character_name, api_key)).start()

def update_model_state(model): config_manager.save_config("last_model", model); return model
def update_api_key_state(api_key_name): config_manager.save_config("last_api_key_name", api_key_name); gr.Info(f"APIキーを '{api_key_name}' に設定しました。"); return api_key_name
def update_timestamp_state(checked): config_manager.save_config("add_timestamp", bool(checked))
def update_send_thoughts_state(checked): config_manager.save_config("last_send_thoughts_to_api", bool(checked)); return bool(checked)
def update_send_notepad_state(checked: bool): return checked
def update_use_common_prompt_state(checked: bool): return checked
def update_send_core_memory_state(checked: bool): return bool(checked)
def update_send_scenery_state(checked: bool): return bool(checked)

def update_api_history_limit_state_and_reload_chat(limit_ui_val: str, character_name: Optional[str]):
    key = next((k for k, v in config_manager.API_HISTORY_LIMIT_OPTIONS.items() if v == limit_ui_val), "all")
    config_manager.save_config("last_api_history_limit_option", key)
    return key, reload_chat_log(character_name, key), gr.State()

def reload_chat_log(character_name: Optional[str], api_history_limit_value: str):
    if not character_name: return []
    log_f,_,_,_,_ = get_character_files_paths(character_name)
    if not log_f or not os.path.exists(log_f): return []
    display_turns = _get_display_history_count(api_history_limit_value)
    history = utils.format_history_for_gradio(utils.load_chat_log(log_f, character_name)[-(display_turns*2):])
    return history

def handle_chatbot_selection(evt: gr.SelectData, chatbot_history: List[Dict[str, str]]):
    default_button_text = "🗑️ 選択した発言を削除"
    if evt.value:
        try:
            message_index = evt.index if isinstance(evt.index, int) else evt.index[0]
            if 0 <= message_index < len(chatbot_history):
                selected_message_obj = chatbot_history[message_index]; content = str(selected_message_obj.get('content', ''))
                display_text = content[:20] + '...' if len(content) > 20 else content; new_button_text = f"🗑️ 「{display_text}」を削除"
                print(f"--- 発言選択: Index={message_index}, Content='{content[:50]}...' ---")
                return selected_message_obj, gr.update(value=new_button_text)
        except: pass
    return None, gr.update(value=default_button_text)

def handle_delete_selected_messages(character_name: str, selected_message: Dict[str, str], api_history_limit: str):
    default_button_text = "🗑️ 選択した発言を削除"
    if not character_name or not selected_message:
        gr.Warning("キャラクターが選択されていないか、削除する発言が選択されていません。"); return reload_chat_log(character_name, api_history_limit), None, gr.update(value=default_button_text)
    log_f, _, _, _, _ = get_character_files_paths(character_name)
    success = utils.delete_message_from_log(log_f, selected_message)
    if success: gr.Info("選択された発言をログから削除しました。")
    else: gr.Error("発言の削除に失敗しました。詳細はターミナルログを確認してください。")
    return reload_chat_log(character_name, api_history_limit), None, gr.update(value=default_button_text)

def update_token_count(*args):
    (current_character_name, current_model_name, textbox_content, file_input_list, api_history_limit_state, current_api_key_name_state, send_notepad_state, use_common_prompt_state, add_timestamp_state, send_thoughts_state, send_core_memory_state, send_scenery_state) = args
    parts_for_api = []
    if textbox_content: parts_for_api.append(textbox_content.strip())
    if file_input_list:
        for file_obj in file_input_list:
            filepath = file_obj.name
            try:
                kind = filetype.guess(filepath); mime_type = kind.mime if kind else None
                if mime_type and mime_type.startswith("image/"): parts_for_api.append(Image.open(filepath))
                elif mime_type and (mime_type.startswith("audio/") or mime_type.startswith("video/") or mime_type == "application/pdf"):
                    with open(filepath, "rb") as f: file_data = base64.b64encode(f.read()).decode("utf-8"); parts_for_api.append({"type": "media", "mime_type": mime_type, "data": file_data})
                else:
                    with open(filepath, 'r', encoding='utf-8') as f: text_content = f.read(); parts_for_api.append(f"--- 添付ファイル「{os.path.basename(filepath)}」の内容 ---\n{text_content}\n--- ファイル内容ここまで ---")
            except Exception as e: print(f"警告: トークン計算ファイル処理エラー: {e}")
    try:
        token_count = gemini_api.count_input_tokens(current_character_name, current_model_name, parts_for_api, api_history_limit_state, current_api_key_name_state, send_notepad_state, use_common_prompt_state, add_timestamp_state, send_thoughts_state, send_core_memory_state, send_scenery_state)
        if token_count == -1: return "入力トークン数: (APIキー/モデルエラー)"
        api_key = config_manager.API_KEYS.get(current_api_key_name_state)
        limit_info = gemini_api.get_model_token_limits(current_model_name, api_key)
        if limit_info and 'input' in limit_info: return f"入力トークン数: {token_count} / {limit_info['input']}"
        else: return f"入力トークン数: {token_count}"
    except Exception as e: print(f"トークン数計算UIハンドラエラー: {e}"); traceback.print_exc(); return "入力トークン数: (例外発生)"
```

### 2. `nexus_ark.py` の最終修正版

```python
# nexus_ark.py を、この最終確定版コードで完全に置き換えてください

import os
import sys
import utils

if not utils.acquire_lock():
    print("ロックが取得できなかったため、アプリケーションを終了します。")
    if os.name == "nt": os.system("pause")
    else: input("続行するにはEnterキーを押してください...")
    sys.exit(1)

os.environ["MEM0_TELEMETRY_ENABLED"] = "false"

try:
    import gradio as gr
    import traceback
    import pandas as pd
    import config_manager, character_manager, alarm_manager, ui_handlers

    config_manager.load_config()
    alarm_manager.load_alarms()

    custom_css = """
#chat_output_area pre { overflow-wrap: break-word !important; white-space: pre-wrap !important; word-break: break-word !important; }
#chat_output_area .thoughts { background-color: #2f2f32; color: #E6E6E6; padding: 5px; border-radius: 5px; font-family: "Menlo", "Monaco", "Consolas", "Courier New", monospace; font-size: 0.8em; white-space: pre-wrap; word-break: break-word; overflow-wrap: break-word !important; }
#memory_json_editor_code .cm-editor { max-height: 300px !important; overflow-y: auto !important; overflow-x: hidden !important; white-space: pre-wrap !important; word-break: break-word !important; overflow-wrap: break-word !important; }
#notepad_editor_code textarea { max-height: 300px !important; overflow-y: auto !important; white-space: pre-wrap !important; word-break: break-word !important; overflow-wrap: break-word !important; box-sizing: border-box; }
#memory_json_editor_code, #notepad_editor_code { max-height: 310px; border: 1px solid #ccc; border-radius: 5px; padding: 0; }
#alarm_dataframe_display { border-radius: 8px !important; } #alarm_dataframe_display table { width: 100% !important; }
#alarm_dataframe_display th, #alarm_dataframe_display td { text-align: left !important; padding: 4px 8px !important; white-space: normal !important; font-size: 0.95em; }
#alarm_dataframe_display th:nth-child(1), #alarm_dataframe_display td:nth-child(1) { width: 50px !important; text-align: center !important; }
#selection_feedback { font-size: 0.9em; color: #555; margin-top: 0px; margin-bottom: 5px; padding-left: 5px; }
#token_count_display { text-align: right; font-size: 0.85em; color: #555; padding-right: 10px; margin-bottom: 5px; }
#tpm_note_display { text-align: right; font-size: 0.75em; color: #777; padding-right: 10px; margin-bottom: -5px; margin-top: 0px; }
"""
    with gr.Blocks(theme=gr.themes.Soft(primary_hue="blue", secondary_hue="sky"), css=custom_css) as demo:
        character_list_on_startup = character_manager.get_character_list()
        if not character_list_on_startup:
            character_manager.ensure_character_files("Default"); character_list_on_startup = ["Default"]
        effective_initial_character = config_manager.initial_character_global
        if not effective_initial_character or effective_initial_character not in character_list_on_startup:
            new_char = character_list_on_startup[0] if character_list_on_startup else "Default"; print(f"警告: 最後に使用したキャラクター '{effective_initial_character}' が見つからないか無効です。'{new_char}' で起動します。"); effective_initial_character = new_char; config_manager.save_config("last_character", new_char)
            if new_char == "Default" and "Default" not in character_list_on_startup: character_manager.ensure_character_files("Default"); character_list_on_startup = ["Default"]

        current_character_name = gr.State(effective_initial_character)
        current_model_name = gr.State(config_manager.initial_model_global)
        current_api_key_name_state = gr.State(config_manager.initial_api_key_name_global)
        send_thoughts_state = gr.State(config_manager.initial_send_thoughts_to_api_global)
        api_history_limit_state = gr.State(config_manager.initial_api_history_limit_option_global)
        alarm_dataframe_original_data = gr.State(pd.DataFrame())
        selected_alarm_ids_state = gr.State([])
        editing_alarm_id_state = gr.State(None)
        send_notepad_state = gr.State(True)
        use_common_prompt_state = gr.State(True)
        send_core_memory_state = gr.State(True)
        send_scenery_state = gr.State(True)
        selected_message_state = gr.State(None)

        with gr.Row():
            with gr.Column(scale=1, min_width=300):
                profile_image_display = gr.Image(height=150, width=150, interactive=False, show_label=False, container=False)
                gr.Markdown("### キャラクター"); character_dropdown = gr.Dropdown(choices=character_list_on_startup, value=effective_initial_character, label="キャラクターを選択", interactive=True)
                with gr.Accordion("空間認識・移動", open=True):
                    current_location_display = gr.Textbox(label="現在地", interactive=False); current_scenery_display = gr.Textbox(label="現在の情景", interactive=False, lines=4, autoscroll=False)
                    with gr.Row(): location_dropdown = gr.Dropdown(label="移動先を選択", interactive=True, scale=3); change_location_button = gr.Button("移動", scale=1)
                    refresh_scenery_button = gr.Button("情景を更新", variant="secondary")
                with gr.Accordion("新しいキャラクターを迎える", open=False):
                    with gr.Row(): new_character_name_textbox = gr.Textbox(placeholder="新しいキャラクター名", show_label=False, scale=3); add_character_button = gr.Button("迎える", variant="secondary", scale=1)
                with gr.Accordion("⚙️ 基本設定", open=False):
                    model_dropdown = gr.Dropdown(choices=config_manager.AVAILABLE_MODELS_GLOBAL, value=config_manager.initial_model_global, label="使用するAIモデル", interactive=True); api_key_dropdown = gr.Dropdown(choices=list(config_manager.API_KEYS.keys()), value=config_manager.initial_api_key_name_global, label="使用するAPIキー", interactive=True); api_history_limit_dropdown = gr.Dropdown(choices=list(config_manager.API_HISTORY_LIMIT_OPTIONS.values()), value=config_manager.API_HISTORY_LIMIT_OPTIONS.get(config_manager.initial_api_history_limit_option_global, "全ログ"), label="APIへの履歴送信", interactive=True); add_timestamp_checkbox = gr.Checkbox(value=config_manager.initial_add_timestamp_global, label="メッセージにタイムスタンプを追加", interactive=True); send_thoughts_checkbox = gr.Checkbox(value=config_manager.initial_send_thoughts_to_api_global, label="思考過程をAPIに送信", interactive=True); send_notepad_checkbox = gr.Checkbox(value=True, label="メモ帳の内容をAPIに送信", interactive=True); use_common_prompt_checkbox = gr.Checkbox(value=True, label="共通ツールプロンプトを注入", interactive=True); send_core_memory_checkbox = gr.Checkbox(value=True, label="コアメモリをAPIに送信", interactive=True); send_scenery_checkbox = gr.Checkbox(value=True, label="空間描写・設定をAPIに送信", interactive=True)
                with gr.Accordion("📗 記憶とログの編集", open=False):
                    with gr.Tabs():
                        with gr.TabItem("記憶 (memory.json)"):
                            memory_json_editor = gr.Code(label="記憶データ", language="json", interactive=True, elem_id="memory_json_editor_code");
                            with gr.Row(): save_memory_button = gr.Button(value="想いを綴る", variant="secondary"); core_memory_update_button = gr.Button(value="コアメモリを更新", variant="primary"); rag_update_button = gr.Button(value="手帳の索引を更新", variant="secondary")
                        with gr.TabItem("メモ帳 (notepad.md)"):
                            notepad_editor = gr.Textbox(label="メモ帳の内容", interactive=True, elem_id="notepad_editor_code", lines=15, autoscroll=True);
                            with gr.Row(): save_notepad_button = gr.Button(value="メモ帳を保存", variant="secondary"); reload_notepad_button = gr.Button(value="再読込", variant="secondary"); clear_notepad_button = gr.Button(value="メモ帳を全削除", variant="stop")
                with gr.Accordion("⏰ 時間管理", open=False):
                    with gr.Tabs():
                        with gr.TabItem("アラーム"):
                            gr.Markdown("ℹ️ **操作方法**: リストから操作したいアラームの行を選択し、下のボタンで操作します。"); alarm_dataframe = gr.Dataframe(headers=["状態", "時刻", "予定", "キャラ", "内容"], datatype=["bool", "str", "str", "str", "str"], interactive=True, row_count=(5, "dynamic"), col_count=5, wrap=True, elem_id="alarm_dataframe_display"); selection_feedback_markdown = gr.Markdown("アラームを選択してください", elem_id="selection_feedback")
                            with gr.Row(): enable_button = gr.Button("✔️ 選択を有効化"); disable_button = gr.Button("❌ 選択を無効化"); delete_alarm_button = gr.Button("🗑️ 選択したアラームを削除", variant="stop")
                            gr.Markdown("---"); gr.Markdown("#### 新規 / 更新"); alarm_hour_dropdown = gr.Dropdown(choices=[str(i).zfill(2) for i in range(24)], label="時", value="08"); alarm_minute_dropdown = gr.Dropdown(choices=[str(i).zfill(2) for i in range(60)], label="分", value="00"); alarm_char_dropdown = gr.Dropdown(choices=character_list_on_startup, value=effective_initial_character, label="キャラ"); alarm_theme_input = gr.Textbox(label="テーマ", placeholder="例：朝の目覚まし"); alarm_prompt_input = gr.Textbox(label="プロンプト（オプション）", placeholder="例：今日も一日頑張ろう！"); alarm_days_checkboxgroup = gr.CheckboxGroup(choices=["月", "火", "水", "木", "金", "土", "日"], label="曜日", value=[]); alarm_add_button = gr.Button("アラーム追加")
                        with gr.TabItem("タイマー"):
                            timer_type_radio = gr.Radio(["通常タイマー", "ポモドーロタイマー"], label="タイマー種別", value="通常タイマー")
                            with gr.Column(visible=True) as normal_timer_ui: timer_duration_number = gr.Number(label="タイマー時間 (分)", value=10, minimum=1, step=1); normal_timer_theme_input = gr.Textbox(label="通常タイマーのテーマ", placeholder="例: タイマー終了！")
                            with gr.Column(visible=False) as pomo_timer_ui: pomo_work_number = gr.Number(label="作業時間 (分)", value=25, minimum=1, step=1); pomo_break_number = gr.Number(label="休憩時間 (分)", value=5, minimum=1, step=1); pomo_cycles_number = gr.Number(label="サイクル数", value=4, minimum=1, step=1); timer_work_theme_input = gr.Textbox(label="作業終了時テーマ", placeholder="作業終了！"); timer_break_theme_input = gr.Textbox(label="休憩終了時テーマ", placeholder="休憩終了！")
                            timer_char_dropdown = gr.Dropdown(choices=character_list_on_startup, value=effective_initial_character, label="通知キャラ", interactive=True); timer_status_output = gr.Textbox(label="タイマー設定状況", interactive=False, placeholder="ここに設定内容が表示されます。"); timer_submit_button = gr.Button("タイマー開始", variant="primary")
            with gr.Column(scale=3):
                chatbot_display = gr.Chatbot(type="messages", height=600, elem_id="chat_output_area", show_copy_button=True);
                with gr.Row(): delete_selected_button = gr.Button("🗑️ 選択した発言を削除", variant="stop", scale=4); chat_reload_button = gr.Button("🔄 更新", scale=1)
                token_count_display = gr.Markdown("入力トークン数", elem_id="token_count_display"); tpm_note_display = gr.Markdown("(参考: Gemini 2.5 シリーズ無料枠TPM: 250,000)", elem_id="tpm_note_display"); chat_input_textbox = gr.Textbox(show_label=False, placeholder="メッセージを入力...", lines=3); submit_button = gr.Button("送信", variant="primary")
                allowed_file_types = ['.png', '.jpg', '.jpeg', '.webp', '.heic', '.heif', '.mp3', '.wav', '.flac', '.aac', '.mp4', '.mov', '.avi', '.webm', '.txt', '.md', '.py', '.js', '.html', '.css', '.pdf', '.xml', '.json']
                file_upload_button = gr.Files(label="ファイル添付", type="filepath", file_count="multiple", file_types=allowed_file_types); gr.Markdown(f"ℹ️ *複数のファイルを添付できます。対応形式: {', '.join(allowed_file_types)}*")

        token_calc_inputs = [current_character_name, current_model_name, chat_input_textbox, file_upload_button, api_history_limit_state, current_api_key_name_state, send_notepad_state, use_common_prompt_state, add_timestamp_checkbox, send_thoughts_state, send_core_memory_state, send_scenery_state]
        chat_inputs = [chat_input_textbox, chatbot_display, current_character_name, current_model_name, current_api_key_name_state, file_upload_button, add_timestamp_checkbox, send_thoughts_state, api_history_limit_state, send_notepad_state, use_common_prompt_state, send_core_memory_state, send_scenery_state]
        chat_submit_outputs = [chatbot_display, chat_input_textbox, file_upload_button, token_count_display, current_location_display, current_scenery_display]
        scenery_refresh_inputs = [current_character_name, current_model_name, current_api_key_name_state, send_thoughts_state, api_history_limit_state, send_notepad_state, use_common_prompt_state, send_core_memory_state, send_scenery_state]
        scenery_refresh_outputs = [current_location_display, current_scenery_display]

        # ★★★★★ ここからが最重要修正箇所 ★★★★★
        add_character_button.click(fn=ui_handlers.handle_add_new_character, inputs=[new_character_name_textbox], outputs=[character_dropdown, alarm_char_dropdown, timer_char_dropdown, new_character_name_textbox])

        character_dropdown.change(
            fn=ui_handlers.update_ui_on_character_change,
            inputs=[character_dropdown, api_history_limit_state],
            outputs=[current_character_name, chatbot_display, chat_input_textbox, profile_image_display, memory_json_editor, alarm_char_dropdown, timer_char_dropdown, notepad_editor, location_dropdown]
        ).then(
            fn=ui_handlers._generate_initial_scenery, # 軽量な直接呼び出しに変更
            inputs=[current_character_name, current_api_key_name_state],
            outputs=scenery_refresh_outputs
        ).then(
            fn=ui_handlers.update_token_count,
            inputs=token_calc_inputs,
            outputs=[token_count_display]
        )

        change_location_button.click(
            fn=ui_handlers.handle_location_change_and_update_scenery,
            inputs=[current_character_name, location_dropdown, current_api_key_name_state],
            outputs=scenery_refresh_outputs
        )

        refresh_scenery_button.click(
            fn=ui_handlers.handle_scenery_refresh,
            inputs=scenery_refresh_inputs,
            outputs=scenery_refresh_outputs
        )
        # ★★★★★ 修正箇所ここまで ★★★★★

        chat_input_textbox.submit(fn=ui_handlers.handle_message_submission, inputs=chat_inputs, outputs=chat_submit_outputs); submit_button.click(fn=ui_handlers.handle_message_submission, inputs=chat_inputs, outputs=chat_submit_outputs)
        for component in [chat_input_textbox, file_upload_button, notepad_editor, model_dropdown, api_key_dropdown, add_timestamp_checkbox, send_thoughts_checkbox, send_notepad_checkbox, use_common_prompt_checkbox, send_core_memory_checkbox, send_scenery_checkbox, api_history_limit_dropdown]:
            if isinstance(component, (gr.Textbox, gr.Checkbox, gr.Dropdown, gr.Radio)): component.change(fn=ui_handlers.update_token_count, inputs=token_calc_inputs, outputs=[token_count_display], show_progress=False)
            elif isinstance(component, gr.Files): component.upload(fn=ui_handlers.update_token_count, inputs=token_calc_inputs, outputs=[token_count_display]); component.clear(fn=ui_handlers.update_token_count, inputs=token_calc_inputs, outputs=[token_count_display])
        model_dropdown.change(fn=ui_handlers.update_model_state, inputs=[model_dropdown], outputs=[current_model_name]); api_key_dropdown.change(fn=ui_handlers.update_api_key_state, inputs=[api_key_dropdown], outputs=[current_api_key_name_state]); add_timestamp_checkbox.change(fn=ui_handlers.update_timestamp_state, inputs=[add_timestamp_checkbox], outputs=[]); send_thoughts_checkbox.change(fn=ui_handlers.update_send_thoughts_state, inputs=[send_thoughts_checkbox], outputs=[send_thoughts_state]); send_notepad_checkbox.change(fn=ui_handlers.update_send_notepad_state, inputs=[send_notepad_checkbox], outputs=[send_notepad_state]); use_common_prompt_checkbox.change(fn=ui_handlers.update_use_common_prompt_state, inputs=[use_common_prompt_checkbox], outputs=[use_common_prompt_state]); send_core_memory_checkbox.change(fn=ui_handlers.update_send_core_memory_state, inputs=[send_core_memory_checkbox], outputs=[send_core_memory_state]); send_scenery_checkbox.change(fn=ui_handlers.update_send_scenery_state, inputs=[send_scenery_checkbox], outputs=[send_scenery_state]); api_history_limit_dropdown.change(fn=ui_handlers.update_api_history_limit_state_and_reload_chat, inputs=[api_history_limit_dropdown, current_character_name], outputs=[api_history_limit_state, chatbot_display, gr.State()])
        chat_reload_button.click(fn=ui_handlers.reload_chat_log, inputs=[current_character_name, api_history_limit_state], outputs=[chatbot_display])
        chatbot_display.select(fn=ui_handlers.handle_chatbot_selection, inputs=[chatbot_display], outputs=[selected_message_state, delete_selected_button], show_progress=False); delete_selected_button.click(fn=ui_handlers.handle_delete_selected_messages, inputs=[current_character_name, selected_message_state, api_history_limit_state], outputs=[chatbot_display, selected_message_state, delete_selected_button])
        save_memory_button.click(fn=ui_handlers.handle_save_memory_click, inputs=[current_character_name, memory_json_editor], outputs=[memory_json_editor]).then(fn=lambda: gr.update(variant="secondary"), inputs=None, outputs=[save_memory_button]); save_notepad_button.click(fn=ui_handlers.handle_save_notepad_click, inputs=[current_character_name, notepad_editor], outputs=[notepad_editor]); reload_notepad_button.click(fn=ui_handlers.handle_reload_notepad, inputs=[current_character_name], outputs=[notepad_editor]); clear_notepad_button.click(fn=ui_handlers.handle_clear_notepad_click, inputs=[current_character_name], outputs=[notepad_editor])
        alarm_dataframe.select(fn=ui_handlers.handle_alarm_selection_and_feedback, inputs=[alarm_dataframe, alarm_dataframe_original_data], outputs=[selected_alarm_ids_state, selection_feedback_markdown], show_progress=False).then(fn=ui_handlers.load_alarm_to_form, inputs=[selected_alarm_ids_state], outputs=[alarm_add_button, alarm_theme_input, alarm_prompt_input, alarm_char_dropdown, alarm_days_checkboxgroup, alarm_hour_dropdown, alarm_minute_dropdown, editing_alarm_id_state])
        enable_button.click(fn=lambda ids: ui_handlers.toggle_selected_alarms_status(ids, True), inputs=[selected_alarm_ids_state], outputs=[alarm_dataframe_original_data, alarm_dataframe]); disable_button.click(fn=lambda ids: ui_handlers.toggle_selected_alarms_status(ids, False), inputs=[selected_alarm_ids_state], outputs=[alarm_dataframe_original_data, alarm_dataframe]); delete_alarm_button.click(fn=ui_handlers.handle_delete_selected_alarms, inputs=[selected_alarm_ids_state], outputs=[alarm_dataframe_original_data, alarm_dataframe]).then(fn=lambda: ([], "アラームを選択してください"), outputs=[selected_alarm_ids_state, selection_feedback_markdown])
        alarm_add_button.click(fn=ui_handlers.handle_add_or_update_alarm, inputs=[editing_alarm_id_state, alarm_hour_dropdown, alarm_minute_dropdown, alarm_char_dropdown, alarm_theme_input, alarm_prompt_input, alarm_days_checkboxgroup], outputs=[alarm_dataframe_original_data, alarm_dataframe, alarm_add_button, alarm_theme_input, alarm_prompt_input, alarm_char_dropdown, alarm_days_checkboxgroup, alarm_hour_dropdown, alarm_minute_dropdown, editing_alarm_id_state])
        timer_type_radio.change(fn=lambda t: (gr.update(visible=t=="通常タイマー"), gr.update(visible=t=="ポモドーロタイマー"), ""), inputs=[timer_type_radio], outputs=[normal_timer_ui, pomo_timer_ui, timer_status_output]); timer_submit_button.click(fn=ui_handlers.handle_timer_submission, inputs=[timer_type_radio, timer_duration_number, pomo_work_number, pomo_break_number, pomo_cycles_number, timer_char_dropdown, timer_work_theme_input, timer_break_theme_input, api_key_dropdown, normal_timer_theme_input], outputs=[timer_status_output])
        rag_update_button.click(fn=ui_handlers.handle_rag_update_button_click, inputs=[current_character_name, current_api_key_name_state], outputs=None); core_memory_update_button.click(fn=ui_handlers.handle_core_memory_update_click, inputs=[current_character_name, current_api_key_name_state], outputs=None)
        demo.load(fn=ui_handlers.handle_initial_load, inputs=None, outputs=[alarm_dataframe, alarm_dataframe_original_data, chatbot_display, profile_image_display, memory_json_editor, alarm_char_dropdown, timer_char_dropdown, selection_feedback_markdown, token_count_display, notepad_editor, location_dropdown, current_location_display, current_scenery_display])
        demo.load(fn=alarm_manager.start_alarm_scheduler_thread, inputs=None, outputs=None)

    if __name__ == "__main__":
        print("\n" + "="*60); print("アプリケーションを起動します..."); print(f"起動後、以下のURLでアクセスしてください。"); print(""); print(f"  【PCからアクセスする場合】"); print(f"  http://127.0.0.1:7860"); print(""); print("  【スマホからアクセスする場合（PCと同じWi-Fiに接続してください）】"); print(f"  http://<お使いのPCのIPアドレス>:7860"); print("  (IPアドレスが分からない場合は、PCのコマンドプロンプトやターミナルで"); print("   `ipconfig` (Windows) または `ifconfig` (Mac/Linux) と入力して確認できます)"); print("="*60 + "\n")
        demo.queue().launch(server_name="0.0.0.0", server_port=7860, share=False, allowed_paths=["."])

except Exception as e:
    print("\n" + "X"*60); print("!!! [致命的エラー] アプリケーションの起動中に、予期せぬ例外が発生しました。"); print("X"*60)
    traceback.print_exc()
finally:
    utils.release_lock()
    if os.name == "nt": os.system("pause")
    else: input("続行するにはEnterキーを押してください...")
```

You **must** respond now, using the `message_user` tool.
System Info: timestamp: 2025-07-27 07:08:08.560613
