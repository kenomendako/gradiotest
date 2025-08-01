# ui_handlers.py を、この最終確定版コードで完全に置き換えてください

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
import html

# --- Nexus Ark モジュールのインポート ---
import gemini_api, config_manager, alarm_manager, character_manager, utils
from tools import memory_tools
from timers import UnifiedTimer
from character_manager import get_character_files_paths
from memory_manager import load_memory_data_safe, save_memory_data

def _generate_initial_scenery(character_name: str, api_key_name: str) -> Tuple[str, str]:
    print("--- [軽量版] 情景生成を開始します ---")
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not character_name or not api_key:
        return "（エラー）", "（キャラクターまたはAPIキーが未設定です）"

    from agent.graph import get_configured_llm
    from tools.memory_tools import read_memory_by_path

    location_id = utils.get_current_location(character_name) or "living_space"
    space_details_raw = read_memory_by_path.invoke({"path": f"living_space.{location_id}", "character_name": character_name})

    location_display_name = location_id
    space_def = "（現在の場所の定義・設定は、取得できませんでした）"
    scenery_text = "（場所の定義がないため、情景を描写できません）"

    try:
        if not space_details_raw.startswith("【エラー】"):
            try:
                space_data = json.loads(space_details_raw)
                if isinstance(space_data, dict):
                    location_display_name = space_data.get("name", location_id)
                    space_def = json.dumps(space_data, ensure_ascii=False, indent=2)
                else:
                    space_def = str(space_data)
            except (json.JSONDecodeError, TypeError):
                space_def = space_details_raw

            if not space_def.startswith("（"):
                llm_flash = get_configured_llm("gemini-2.5-flash", api_key)
                now = datetime.datetime.now()
                scenery_prompt = (
                    f"空間定義:{space_def}\n時刻:{now.strftime('%H:%M')} / 季節:{now.month}月\n\n"
                    "以上の情報から、あなたはこの空間の「今この瞬間」を切り取る情景描写の専門家です。\n"
                    "【ルール】\n"
                    "- 人物やキャラクターの描写は絶対に含めないでください。\n"
                    "- 1〜2文の簡潔な文章にまとめてください。\n"
                    "- 窓の外の季節感や時間帯、室内の空気感や陰影など、五感に訴えかける精緻で写実的な描写を重視してください。"
                )
                scenery_text = llm_flash.invoke(scenery_prompt).content
                print(f"  - 生成された情景: {scenery_text}")

    except Exception as e:
        print(f"--- [軽量版] 情景生成中にエラー: {e}")
        traceback.print_exc()
        location_display_name = "（エラー）"
        scenery_text = "（情景生成エラー）"

    return location_display_name, scenery_text

def handle_message_submission(*args: Any):
    (textbox_content, chatbot_history, current_character_name, current_model_name, current_api_key_name_state, file_input_list, add_timestamp_checkbox, send_thoughts_state, api_history_limit_state, send_notepad_state, use_common_prompt_state, send_core_memory_state, send_scenery_state) = args
    user_prompt_from_textbox = textbox_content.strip() if textbox_content else ""
    if not user_prompt_from_textbox and not file_input_list:
        token_count = update_token_count(current_character_name, current_model_name, None, None, api_history_limit_state, current_api_key_name_state, send_notepad_state, use_common_prompt_state, add_timestamp_checkbox, send_thoughts_state, send_core_memory_state, send_scenery_state)
        yield chatbot_history, gr.update(), gr.update(), token_count, gr.update(), gr.update()
        return

    log_message_parts = []
    if user_prompt_from_textbox:
        timestamp = f"\n\n{datetime.datetime.now().strftime('%Y-%m-%d (%a) %H:%M:%S')}" if add_timestamp_checkbox else ""
        processed_user_message = user_prompt_from_textbox + timestamp
        chatbot_history.append({"role": "user", "content": processed_user_message})
        log_message_parts.append(processed_user_message)

    if file_input_list:
        for file_obj in file_input_list:
            filepath = file_obj.name
            filename = os.path.basename(filepath)
            safe_filepath = os.path.abspath(filepath).replace("\\", "/")
            md_string = f"[{filename}]({safe_filepath})"
            chatbot_history.append({"role": "user", "content": md_string})
            log_message_parts.append(f"[ファイル添付: {filepath}]")

    chatbot_history.append({"role": "assistant", "content": "思考中... ▌"})

    token_count = update_token_count(current_character_name, current_model_name, textbox_content, file_input_list, api_history_limit_state, current_api_key_name_state, send_notepad_state, use_common_prompt_state, add_timestamp_checkbox, send_thoughts_state, send_core_memory_state, send_scenery_state)

    yield (
        chatbot_history,
        gr.update(value=""),
        gr.update(value=None),
        token_count,
        gr.update(), # current_location_display
        gr.update(), # current_scenery_display
        gr.update(), # alarm_dataframe_original_data
        gr.update()  # alarm_dataframe
    )

    response_data = {}
    try:
        response_data = gemini_api.invoke_nexus_agent(*args)
    except Exception as e:
        traceback.print_exc()
        response_data = {"response": f"[UIハンドラエラー: {e}]", "location_name": "（エラー）", "scenery": "（エラー）"}

    final_response_text = response_data.get("response", "")
    location_name = response_data.get("location_name", "（取得失敗）")
    scenery_text = response_data.get("scenery", "（取得失敗）")

    log_f, _, _, _, _ = get_character_files_paths(current_character_name)
    final_log_message = "\n\n".join(log_message_parts).strip()
    if final_log_message:
        user_header = utils._get_user_header_from_log(log_f, current_character_name)
        utils.save_message_to_log(log_f, user_header, final_log_message)
    if final_response_text:
        utils.save_message_to_log(log_f, f"## {current_character_name}:", final_response_text)

    raw_history = utils.load_chat_log(log_f, current_character_name)
    display_turns = _get_display_history_count(api_history_limit_state)
    formatted_history, _ = utils.format_history_for_gradio(raw_history[-(display_turns*2):], current_character_name)

    token_count = update_token_count(current_character_name, current_model_name, None, None, api_history_limit_state, current_api_key_name_state, send_notepad_state, use_common_prompt_state, add_timestamp_checkbox, send_thoughts_state, send_core_memory_state, send_scenery_state)

    # ★★★ 以下の3行を追加 ★★★
    new_alarm_df_with_ids = render_alarms_as_dataframe()
    new_display_df = get_display_df(new_alarm_df_with_ids)

    # ★★★ yield の返り値にアラームDFを追加 ★★★
    yield (
        formatted_history,
        gr.update(),
        gr.update(value=None),
        token_count,
        location_name,
        scenery_text,
        new_alarm_df_with_ids, # ★ 追加
        new_display_df         # ★ 追加
    )

def handle_scenery_refresh(character_name: str, api_key_name: str) -> Tuple[str, str]:
    if not character_name or not api_key_name:
        return "（キャラクターまたはAPIキーが未選択です）", "（キャラクターまたはAPIキーが未選択です）"
    gr.Info(f"「{character_name}」の現在の情景を更新しています...")
    loc, scen = _generate_initial_scenery(character_name, api_key_name)
    gr.Info("情景を更新しました.")
    return loc, scen

def handle_location_change(character_name: str, location_id: str) -> Tuple[str, str]:
    """場所を変更し、情景欄にはアナウンスのみ表示する新しいハンドラ。"""
    from tools.space_tools import set_current_location
    print(f"--- UIからの場所変更処理開始: キャラクター='{character_name}', 移動先ID='{location_id}' ---")
    if not character_name or not location_id:
        gr.Warning("キャラクターと移動先の場所を選択してください。")
        current_loc_id = utils.get_current_location(character_name)
        return current_loc_id, "（場所の変更に失敗しました）"

    result = set_current_location.func(location=location_id, character_name=character_name)
    if "Success" not in result:
        gr.Error(f"場所の変更に失敗しました: {result}")
        current_loc_id = utils.get_current_location(character_name)
        return current_loc_id, f"（場所の変更に失敗: {result}）"

    # 場所IDから表示名を取得
    memory_data = load_memory_data_safe(get_character_files_paths(character_name)[3])
    new_location_name = memory_data.get("living_space", {}).get(location_id, {}).get("name", location_id)

    gr.Info(f"場所を「{new_location_name}」に変更しました。")
    scenery_text = f"（場所を「{new_location_name}」に変更しました。情景は次の対話で生成されます）"

    return new_location_name, scenery_text

def get_location_list_for_ui(character_name: str) -> list:
    if not character_name: return []
    _, _, _, memory_json_path, _ = get_character_files_paths(character_name)
    memory_data = load_memory_data_safe(memory_json_path)
    if "error" in memory_data or "living_space" not in memory_data: return []
    living_space = memory_data.get("living_space", {})
    location_list = []
    for loc_id, details in living_space.items():
        if isinstance(details, dict):
            location_list.append((details.get("name", loc_id), loc_id))
    return sorted(location_list, key=lambda x: x[0])

def handle_add_new_character(character_name: str):
    if not character_name or not character_name.strip():
        gr.Warning("キャラクター名が入力されていません。")
        char_list = character_manager.get_character_list()
        return gr.update(choices=char_list), gr.update(choices=char_list), gr.update(choices=char_list), gr.update(value="")
    safe_name = re.sub(r'[\\/*?:"<>|]', "", character_name).strip()
    if not safe_name:
        gr.Warning("無効なキャラクター名です。")
        char_list = character_manager.get_character_list()
        return gr.update(choices=char_list), gr.update(choices=char_list), gr.update(choices=char_list), gr.update(value="")
    if character_manager.ensure_character_files(safe_name):
        gr.Info(f"新しいキャラクター「{safe_name}」さんを迎えました！")
        new_char_list = character_manager.get_character_list()
        return gr.update(choices=new_char_list, value=safe_name), gr.update(choices=new_char_list, value=safe_name), gr.update(choices=new_char_list, value=safe_name), gr.update(value="")
    else:
        gr.Error(f"キャラクター「{safe_name}」の準備に失敗しました。")
        char_list = character_manager.get_character_list()
        return gr.update(choices=char_list), gr.update(choices=char_list), gr.update(choices=char_list), gr.update(value=character_name)

def _get_display_history_count(api_history_limit_value: str) -> int:
    return int(api_history_limit_value) if api_history_limit_value.isdigit() else config_manager.UI_HISTORY_MAX_LIMIT

def update_ui_on_character_change(character_name: Optional[str], api_history_limit_value: str):
    if not character_name:
        all_chars = character_manager.get_character_list()
        character_name = all_chars[0] if all_chars else "Default"

    config_manager.save_config("last_character", character_name)

    log_f, _, img_p, mem_p, notepad_p = get_character_files_paths(character_name)

    display_turns = _get_display_history_count(api_history_limit_value)
    chat_history, _ = utils.format_history_for_gradio(utils.load_chat_log(log_f, character_name)[-(display_turns * 2):], character_name)

    memory_str = json.dumps(load_memory_data_safe(mem_p), indent=2, ensure_ascii=False)
    profile_image = img_p if img_p and os.path.exists(img_p) else None
    notepad_content = load_notepad_content(character_name)

    # --- ★★★ ここからが変更箇所 ★★★ ---
    # 場所の情報を解決
    locations = get_location_list_for_ui(character_name)
    current_location_id = utils.get_current_location(character_name)
    memory_data = load_memory_data_safe(mem_p)
    current_location_name = memory_data.get("living_space", {}).get(current_location_id, {}).get("name", current_location_id)

    # ドロップダウンに設定する値を検証
    valid_location_ids = [loc[1] for loc in locations]
    dropdown_value = current_location_id if current_location_id in valid_location_ids else None

    # 情景のプレースホルダーを設定
    scenery_text = "（AIとの対話開始時に生成されます）"
    # --- ★★★ 変更箇所ここまで ★★★ ---

    # 返り値に場所と情景を追加
    return (
        character_name,
        chat_history,
        "",
        profile_image,
        memory_str,
        character_name,
        character_name,
        notepad_content,
        gr.update(choices=locations, value=dropdown_value), # ★ dropdown_value を使用
        current_location_name,
        scenery_text
    )

def handle_initial_load():
    print("--- UI初期化処理(handle_initial_load)を開始します ---")
    char_name = config_manager.initial_character_global
    model_name = config_manager.initial_model_global
    api_key_name = config_manager.initial_api_key_name_global
    api_history_limit = config_manager.initial_api_history_limit_option_global

    df_with_ids = render_alarms_as_dataframe()
    display_df = get_display_df(df_with_ids)

    # --- ★★★ ここからが変更箇所 ★★★ ---
    # update_ui_on_character_change から11個の値を受け取るように修正
    (ret_char, chat_hist, _, prof_img, mem_str, al_char, tm_char,
     note_cont, loc_dd, location_name, scenery_text) = update_ui_on_character_change(char_name, api_history_limit)

    # 上記で location_name と scenery_text を受け取るようになったため、
    # 以下の古いプレースホルダー設定ロジックは不要となり、削除します。
    # --- (古いコードはここにありました) ---
    # --- ★★★ 変更箇所ここまで ★★★ ---

    token_count = update_token_count(ret_char, model_name, None, None, api_history_limit, api_key_name, True, True, config_manager.initial_add_timestamp_global, config_manager.initial_send_thoughts_to_api_global, True, True)

    return (display_df, df_with_ids, chat_hist, prof_img, mem_str, al_char, tm_char, "アラームを選択してください", token_count, note_cont, loc_dd, location_name, scenery_text)

def handle_chatbot_selection(character_name: str, api_history_limit_state: str, evt: gr.SelectData):
    """
    Handles the selection of a message in the chatbot UI.
    Identifies the message by creating an index map and retrieving the original log entry.
    """
    if not character_name or evt.index is None:
        return None, gr.update(visible=False)

    try:
        clicked_ui_index = evt.index

        # Re-create the exact history and the index map
        log_f, _, _, _, _ = get_character_files_paths(character_name)
        raw_history = utils.load_chat_log(log_f, character_name)
        display_turns = _get_display_history_count(api_history_limit_state)
        visible_raw_history = raw_history[-(display_turns * 2):]

        _, mapping_list = utils.format_history_for_gradio(visible_raw_history, character_name)

        if not (0 <= clicked_ui_index < len(mapping_list)):
            gr.Warning("Could not identify the clicked message (UI index out of bounds).")
            return None, gr.update(visible=False)

        # Use the map to find the true index in the original log list
        original_log_index = mapping_list[clicked_ui_index]

        if 0 <= original_log_index < len(visible_raw_history):
            selected_raw_message = visible_raw_history[original_log_index]
            return selected_raw_message, gr.update(visible=True)
        else:
            gr.Warning("Could not identify the clicked message (Original log index out of bounds).")
            return None, gr.update(visible=False)

    except Exception as e:
        print(f"Error during chatbot selection: {e}")
        traceback.print_exc()
        return None, gr.update(visible=False)


def handle_delete_button_click(
    message_to_delete: Optional[Dict[str, str]],
    character_name: str,
    api_history_limit: str
):
    """
    Handles the delete button click, using the key created by handle_chatbot_selection.
    """
    if not message_to_delete:
        gr.Warning("No message selected for deletion.")
        return gr.update(), None, gr.update(visible=False)

    log_f, _, _, _, _ = get_character_files_paths(character_name)

    # Pass the message dictionary to the deletion function
    success = utils.delete_message_from_log(
        log_file_path=log_f,
        message_to_delete=message_to_delete,
        character_name=character_name
    )

    if success:
        gr.Info("Successfully deleted the message from the log.")
    else:
        gr.Error("Failed to delete the message. Check terminal for details.")

    # Reload chat log to reflect the change
    new_chat_history = reload_chat_log(character_name, api_history_limit)

    # Reset selection state and hide buttons
    return new_chat_history, None, gr.update(visible=False)

def reload_chat_log(character_name: Optional[str], api_history_limit_value: str):
    if not character_name: return [], []
    log_f,_,_,_,_ = get_character_files_paths(character_name)
    if not log_f or not os.path.exists(log_f): return [], []
    display_turns = _get_display_history_count(api_history_limit_value)
    history, _ = utils.format_history_for_gradio(utils.load_chat_log(log_f, character_name)[-(display_turns*2):], character_name)
    return history

def handle_save_memory_click(character_name, json_string_data):
    if not character_name:
        gr.Warning("キャラクターが選択されていません。")
        return gr.update()
    try:
        return save_memory_data(character_name, json_string_data)
    except Exception as e:
        gr.Error(f"記憶の保存中にエラーが発生しました: {e}")
        return gr.update()

def handle_reload_memory(character_name: str) -> str:
    if not character_name:
        gr.Warning("キャラクターが選択されていません。")
        return "{}"
    gr.Info(f"「{character_name}」の記憶を再読み込みしました。")
    _, _, _, memory_json_path, _ = get_character_files_paths(character_name)
    memory_data = load_memory_data_safe(memory_json_path)
    return json.dumps(memory_data, indent=2, ensure_ascii=False)

def load_notepad_content(character_name: str) -> str:
    if not character_name: return ""
    _, _, _, _, notepad_path = get_character_files_paths(character_name)
    if notepad_path and os.path.exists(notepad_path):
        with open(notepad_path, "r", encoding="utf-8") as f:
            return f.read()
    return ""

def handle_save_notepad_click(character_name: str, content: str) -> str:
    if not character_name:
        gr.Warning("キャラクターが選択されていません。")
        return content
    _, _, _, _, notepad_path = character_manager.get_character_files_paths(character_name)
    if not notepad_path:
        gr.Error(f"「{character_name}」のメモ帳パス取得失敗。")
        return content
    lines = []
    for line in content.strip().split('\n'):
        line = line.strip()
        if line and not re.match(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\]", line):
            lines.append(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}] {line}")
        elif line:
            lines.append(line)
    final_content = "\n".join(lines)
    try:
        with open(notepad_path, "w", encoding="utf-8") as f:
            f.write(final_content + ('\n' if final_content else ''))
        gr.Info(f"「{character_name}」のメモ帳を保存しました。")
        return final_content
    except Exception as e:
        gr.Error(f"メモ帳の保存エラー: {e}")
        return content

def handle_clear_notepad_click(character_name: str) -> str:
    if not character_name:
        gr.Warning("キャラクターが選択されていません。")
        return ""
    _, _, _, _, notepad_path = character_manager.get_character_files_paths(character_name)
    if not notepad_path:
        gr.Error(f"「{character_name}」のメモ帳パス取得失敗。")
        return ""
    try:
        with open(notepad_path, "w", encoding="utf-8") as f:
            f.write("")
        gr.Info(f"「{character_name}」のメモ帳を空にしました。")
        return ""
    except Exception as e:
        gr.Error(f"メモ帳クリアエラー: {e}")
        return f"エラー: {e}"

def handle_reload_notepad(character_name: str) -> str:
    if not character_name:
        gr.Warning("キャラクターが選択されていません。")
        return ""
    content = load_notepad_content(character_name)
    gr.Info(f"「{character_name}」のメモ帳を再読み込みしました。")
    return content

def render_alarms_as_dataframe():
    alarms = sorted(alarm_manager.load_alarms(), key=lambda x: x.get("time", ""))
    all_rows = []
    for a in alarms:
        theme_content = a.get("context_memo") or ""
        date_str = a.get("date")
        days_list = a.get("days", [])
        schedule_display = "単発"
        if date_str:
            try:
                date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
                today = datetime.date.today()
                if date_obj == today: schedule_display = "今日"
                elif date_obj == today + datetime.timedelta(days=1): schedule_display = "明日"
                else: schedule_display = date_obj.strftime("%m/%d")
            except:
                schedule_display = "日付不定"
        elif days_list:
            schedule_display = ",".join([DAY_MAP_EN_TO_JA.get(d.lower(), d.upper()) for d in days_list])
        all_rows.append({"ID": a.get("id"), "状態": a.get("enabled", False), "時刻": a.get("time"), "予定": schedule_display, "キャラ": a.get("character"), "内容": theme_content})
    return pd.DataFrame(all_rows, columns=["ID", "状態", "時刻", "予定", "キャラ", "内容"])

def get_display_df(df_with_id: pd.DataFrame):
    if df_with_id is None or df_with_id.empty:
        return pd.DataFrame(columns=["状態", "時刻", "予定", "キャラ", "内容"])
    return df_with_id[["状態", "時刻", "予定", "キャラ", "内容"]] if 'ID' in df_with_id.columns else df_with_id

def handle_alarm_selection(evt: gr.SelectData, df_with_id: pd.DataFrame) -> List[str]:
    """
    Gradio Dataframeからの選択イベントを正しく処理する。
    evt.indexは選択された行番号のリスト (e.g., [0, 2]) である。
    """
    if not evt.index or df_with_id is None or df_with_id.empty:
        return []

    selected_ids = []
    # Gradioから送られてくる行番号のリストを直接ループする
    for row_index in evt.index:
        # 念のため、インデックスが有効な範囲にあるかチェック
        if 0 <= row_index < len(df_with_id):
            # .ilocで行を特定し、その行の 'ID' 列の値を取得する
            alarm_id = df_with_id.iloc[row_index]['ID']
            selected_ids.append(str(alarm_id))

    return selected_ids

def handle_alarm_selection_and_feedback(evt: gr.SelectData, df_with_id: pd.DataFrame):
    selected_ids = handle_alarm_selection(evt, df_with_id)
    return selected_ids, "アラームを選択してください" if not selected_ids else f"{len(selected_ids)} 件のアラームを選択中"

def toggle_selected_alarms_status(selected_ids: list, target_status: bool):
    if not selected_ids:
        gr.Warning("状態を変更するアラームが選択されていません。")
        # 変更がない場合も、現在の状態を返す
        df_with_ids = render_alarms_as_dataframe()
        return df_with_ids, get_display_df(df_with_ids)

    # 1. 現在のアラームデータをすべてロードする
    current_alarms = alarm_manager.load_alarms()

    # 2. ロードしたリストをループし、選択されたIDと一致するアラームの状態を書き換える
    modified = False
    for alarm in current_alarms:
        if alarm.get("id") in selected_ids:
            alarm["enabled"] = target_status
            modified = True

    # 3. 変更があった場合のみ、アラームファイル全体を保存する
    if modified:
        # alarm_manager はグローバル変数でデータを保持しているので、それを直接書き換えて保存する
        alarm_manager.alarms_data_global = current_alarms
        alarm_manager.save_alarms()
        gr.Info(f"{len(selected_ids)}件のアラームの状態を「{ '有効' if target_status else '無効' }」に変更しました。")

    # 4. 最後に、更新された内容でUIのデータフレームを再生成して返す
    new_df_with_ids = render_alarms_as_dataframe()
    return new_df_with_ids, get_display_df(new_df_with_ids)

def handle_delete_selected_alarms(selected_ids: list):
    if not selected_ids:
        gr.Warning("削除するアラームが選択されていません。")
    else:
        for sid in selected_ids:
            alarm_manager.delete_alarm(str(sid))
    new_df_with_ids = render_alarms_as_dataframe()
    return new_df_with_ids, get_display_df(new_df_with_ids)

def handle_add_or_update_alarm(editing_id, h, m, char, theme, prompt, days_ja, is_emergency):
    from tools.alarm_tools import set_personal_alarm
    time_str = f"{h}:{m}"
    context = theme or prompt or "時間になりました"
    days_en = [DAY_MAP_JA_TO_EN.get(d) for d in days_ja if d in DAY_MAP_JA_TO_EN]
    if editing_id:
        alarm_manager.delete_alarm(editing_id)
        gr.Info(f"アラームID:{editing_id}を更新します。")

    # ツールを呼び出す際に is_emergency を渡す
    set_personal_alarm.func(
        time=time_str,
        context_memo=context,
        character_name=char,
        days=days_en,
        date=None,
        is_emergency=is_emergency
    )

    new_df_with_ids = render_alarms_as_dataframe()
    all_chars = character_manager.get_character_list()
    default_char = all_chars[0] if all_chars else "Default"

    # 戻り値に緊急通知チェックボックスのデフォルト値(False)を追加
    return new_df_with_ids, get_display_df(new_df_with_ids), "アラーム追加", "", "", default_char, [], "08", "00", None, False

def load_alarm_to_form(selected_ids: list):
    all_chars = character_manager.get_character_list()
    default_char = all_chars[0] if all_chars else "Default"
    if not selected_ids or len(selected_ids) != 1:
        return "アラーム追加", "", "", default_char, [], "08", "00", None, False
    alarm = next((a for a in alarm_manager.load_alarms() if a.get("id") == selected_ids[0]), None)
    if not alarm:
        gr.Warning(f"アラームID '{selected_ids[0]}' が見つかりません。")
        return "アラーム追加", "", "", default_char, [], "08", "00", None, False
    h, m = alarm.get("time", "08:00").split(":")
    days_ja = [DAY_MAP_EN_TO_JA.get(d.lower(), d.upper()) for d in alarm.get("days", [])]
    theme_content = alarm.get("context_memo") or ""
    is_emergency = alarm.get("is_emergency", False)
    return "アラーム更新", theme_content, "", alarm.get("character", default_char), days_ja, h, m, selected_ids[0], is_emergency

def handle_timer_submission(timer_type, duration, work, brk, cycles, char, work_theme, brk_theme, api_key_name, normal_theme):
    if not char or not api_key_name:
        return "エラー：キャラクターとAPIキーを選択してください。"
    try:
        timer = UnifiedTimer(timer_type, float(duration or 0), float(work or 0), float(brk or 0), int(cycles or 0), char, work_theme, brk_theme, api_key_name, normal_theme=normal_theme)
        timer.start()
        gr.Info(f"{timer_type}を開始しました.")
        return f"{timer_type}を開始しました。"
    except Exception as e:
        return f"タイマー開始エラー: {e}"

def handle_rag_update_button_click(character_name: str, api_key_name: str):
    if not character_name or not api_key_name:
        gr.Warning("キャラクターとAPIキーを選択してください。")
        return
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        gr.Warning(f"APIキー '{api_key_name}' が有効ではありません。")
        return
    gr.Info(f"「{character_name}」のRAG索引の更新を開始します...")
    import rag_manager
    threading.Thread(target=lambda: rag_manager.create_or_update_index(character_name, api_key)).start()

def _run_core_memory_update(character_name: str, api_key: str):
    print(f"--- [スレッド開始] コアメモリ更新処理を開始します (Character: {character_name}) ---")
    try:
        result = memory_tools.summarize_and_save_core_memory.func(character_name=character_name, api_key=api_key)
        print(f"--- [スレッド終了] コアメモリ更新処理完了 --- 結果: {result}")
    except Exception as e:
        print(f"--- [スレッドエラー] コアメモリ更新中に予期せぬエラー ---")
        traceback.print_exc()

def handle_core_memory_update_click(character_name: str, api_key_name: str):
    if not character_name or not api_key_name:
        gr.Warning("キャラクターとAPIキーを選択してください。")
        return
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        gr.Warning(f"APIキー '{api_key_name}' が有効ではありません。")
        return
    gr.Info(f"「{character_name}」のコアメモリ更新をバックグラウンドで開始しました。")
    threading.Thread(target=_run_core_memory_update, args=(character_name, api_key)).start()

def update_model_state(model):
    config_manager.save_config("last_model", model)
    return model

def update_api_key_state(api_key_name):
    config_manager.save_config("last_api_key_name", api_key_name)
    gr.Info(f"APIキーを '{api_key_name}' に設定しました。")
    return api_key_name

def update_timestamp_state(checked):
    config_manager.save_config("add_timestamp", bool(checked))

def update_send_thoughts_state(checked):
    config_manager.save_config("last_send_thoughts_to_api", bool(checked))
    return bool(checked)

def update_send_notepad_state(checked: bool):
    return checked

def update_use_common_prompt_state(checked: bool):
    return checked

def update_send_core_memory_state(checked: bool):
    return bool(checked)

def update_send_scenery_state(checked: bool):
    return bool(checked)

def update_api_history_limit_state_and_reload_chat(limit_ui_val: str, character_name: Optional[str]):
    key = next((k for k, v in config_manager.API_HISTORY_LIMIT_OPTIONS.items() if v == limit_ui_val), "all")
    config_manager.save_config("last_api_history_limit_option", key)
    return key, reload_chat_log(character_name, key), gr.State()

def update_token_count(*args):
    (current_character_name, current_model_name, textbox_content, file_input_list, api_history_limit_state, current_api_key_name_state, send_notepad_state, use_common_prompt_state, add_timestamp_state, send_thoughts_state, send_core_memory_state, send_scenery_state) = args
    parts_for_api = []
    if textbox_content:
        parts_for_api.append(textbox_content.strip())
    if file_input_list:
        for file_obj in file_input_list:
            filepath = file_obj.name
            try:
                kind = filetype.guess(filepath)
                mime_type = kind.mime if kind else None
                if mime_type and mime_type.startswith("image/"):
                    parts_for_api.append(Image.open(filepath))
                elif mime_type and (mime_type.startswith("audio/") or mime_type.startswith("video/") or mime_type == "application/pdf"):
                    with open(filepath, "rb") as f:
                        file_data = base64.b64encode(f.read()).decode("utf-8")
                        parts_for_api.append({"type": "media", "mime_type": mime_type, "data": file_data})
                else:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        text_content = f.read()
                        parts_for_api.append(f"--- 添付ファイル「{os.path.basename(filepath)}」の内容 ---\n{text_content}\n--- ファイル内容ここまで ---")
            except Exception as e:
                print(f"警告: トークン計算ファイル処理エラー: {e}")
    try:
        token_count = gemini_api.count_input_tokens(current_character_name, current_model_name, parts_for_api, api_history_limit_state, current_api_key_name_state, send_notepad_state, use_common_prompt_state, add_timestamp_state, send_thoughts_state, send_core_memory_state, send_scenery_state)
        if token_count == -1: return "入力トークン数: (APIキー/モデルエラー)"
        api_key = config_manager.API_KEYS.get(current_api_key_name_state)
        limit_info = gemini_api.get_model_token_limits(current_model_name, api_key)
        if limit_info and 'input' in limit_info:
            return f"入力トークン数: {token_count} / {limit_info['input']}"
        else:
            return f"入力トークン数: {token_count}"
    except Exception as e:
        print(f"トークン数計算UIハンドラエラー: {e}")
        traceback.print_exc()
        return "入力トークン数: (例外発生)"
