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

    yield chatbot_history, gr.update(value=""), gr.update(value=None), token_count, gr.update(), gr.update()

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
    formatted_history = utils.format_history_for_gradio(raw_history[-(display_turns*2):])

    token_count = update_token_count(current_character_name, current_model_name, None, None, api_history_limit_state, current_api_key_name_state, send_notepad_state, use_common_prompt_state, add_timestamp_checkbox, send_thoughts_state, send_core_memory_state, send_scenery_state)

    yield formatted_history, gr.update(), gr.update(value=None), token_count, location_name, scenery_text

def handle_scenery_refresh(character_name: str, api_key_name: str) -> Tuple[str, str]:
    if not character_name or not api_key_name:
        return "（キャラクターまたはAPIキーが未選択です）", "（キャラクターまたはAPIキーが未選択です）"
    gr.Info(f"「{character_name}」の現在の情景を更新しています...")
    loc, scen = _generate_initial_scenery(character_name, api_key_name)
    gr.Info("情景を更新しました.")
    return loc, scen

def handle_location_change_and_update_scenery(character_name: str, location_id: str, api_key_name: str) -> Tuple[str, str]:
    from tools.space_tools import set_current_location
    print(f"--- UIからの場所変更処理開始: キャラクター='{character_name}', 移動先ID='{location_id}' ---")
    if not character_name or not location_id:
        gr.Warning("キャラクターと移動先の場所を選択してください。")
        return _generate_initial_scenery(character_name, api_key_name)

    result = set_current_location.func(location=location_id, character_name=character_name)
    if "Success" not in result:
        gr.Error(f"場所の変更に失敗しました: {result}")
        return _generate_initial_scenery(character_name, api_key_name)

    gr.Info(f"場所を「{location_id}」に変更しました。続けて情景を更新します。")
    loc, scen = _generate_initial_scenery(character_name, api_key_name)
    gr.Info("場所情報を更新しました。")
    return loc, scen

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
    chat_history = utils.format_history_for_gradio(utils.load_chat_log(log_f, character_name)[-(display_turns * 2):])
    memory_str = json.dumps(load_memory_data_safe(mem_p), indent=2, ensure_ascii=False)
    profile_image = img_p if img_p and os.path.exists(img_p) else None
    notepad_content = load_notepad_content(character_name)
    locations = get_location_list_for_ui(character_name)
    current_location_id = utils.get_current_location(character_name)
    return (character_name, chat_history, "", profile_image, memory_str, character_name, character_name, notepad_content, gr.update(choices=locations, value=current_location_id))

def handle_initial_load():
    print("--- UI初期化処理(handle_initial_load)を開始します ---")
    char_name = config_manager.initial_character_global
    model_name = config_manager.initial_model_global
    api_key_name = config_manager.initial_api_key_name_global
    api_history_limit = config_manager.initial_api_history_limit_option_global
    df_with_ids = render_alarms_as_dataframe()
    display_df = get_display_df(df_with_ids)
    (ret_char, chat_hist, _, prof_img, mem_str, al_char, tm_char, note_cont, loc_dd) = update_ui_on_character_change(char_name, api_history_limit)
    loc, scen = _generate_initial_scenery(ret_char, api_key_name)
    token_count = update_token_count(ret_char, model_name, None, None, api_history_limit, api_key_name, True, True, config_manager.initial_add_timestamp_global, config_manager.initial_send_thoughts_to_api_global, True, True)
    return (display_df, df_with_ids, chat_hist, prof_img, mem_str, al_char, tm_char, "アラームを選択してください", token_count, note_cont, loc_dd, loc, scen)

def handle_chatbot_selection(chatbot_history: List[Dict[str, str]], evt: gr.SelectData):
    """メッセージが選択された時の処理。削除ボタンを表示し、対象をStateに保存する。"""
    if not evt.value:
        return None, gr.update(visible=False)
    try:
        # <a>タグ（スクロール）のクリックではイベントを発火させない
        if evt.value.strip().startswith('<a href='):
            return None, gr.update(visible=False)

        clicked_index = evt.index if isinstance(evt.index, int) else evt.index[0]

        # ログから読み込んだ生のメッセージを取得
        # chatbot_history はHTMLフォーマット済みなので、インデックスを元に生ログから探す
        log_f, _, _, _, _ = get_character_files_paths(character_manager.get_character_list()[0]) # HACK: needs current char
        raw_history = utils.load_chat_log(log_f, character_manager.get_character_list()[0])
        # This part is still tricky. For now, let's store the formatted message.
        # It's better to store the raw message if we can reliably map index.
        selected_message_obj = chatbot_history[clicked_index]

        return selected_message_obj, gr.update(visible=True)
    except Exception as e:
        print(f"メッセージ選択処理でエラー: {e}")
        return None, gr.update(visible=False)

def handle_delete_button_click(
    selected_message: Optional[Dict[str, str]],
    character_name: str,
    api_history_limit: str
):
    """「選択した発言を削除」ボタンが押された時の処理。"""
    if not selected_message:
        gr.Warning("削除する発言が選択されていません。")
        return gr.update(), None, gr.update(visible=False)

    log_f, _, _, _, _ = get_character_files_paths(character_name)

    # GradioのChatbotはHTMLとしてcontentを扱うため、生のテキストに戻す必要がある
    raw_content = utils.extract_raw_text_from_html(selected_message['content'])

    role_from_ui = 'user' if selected_message['role'] == 'user' else 'model'

    message_to_delete_from_log = {
        'role': role_from_ui,
        'content': raw_content
    }

    success = utils.delete_message_from_log(log_f, message_to_delete_from_log)
    if success:
        gr.Info("選択された発言をログから削除しました。")
    else:
        gr.Error("発言の削除に失敗しました。詳細はターミナルログを確認してください。")

    new_chat_history = reload_chat_log(character_name, api_history_limit)

    return new_chat_history, None, gr.update(visible=False)

def reload_chat_log(character_name: Optional[str], api_history_limit_value: str):
    if not character_name: return []
    log_f,_,_,_,_ = get_character_files_paths(character_name)
    if not log_f or not os.path.exists(log_f): return []
    display_turns = _get_display_history_count(api_history_limit_value)
    history = utils.format_history_for_gradio(utils.load_chat_log(log_f, character_name)[-(display_turns*2):])
    return history

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
def update_send_notepad_state(checked: bool): return checked
def update_use_common_prompt_state(checked: bool): return checked
def update_send_core_memory_state(checked: bool): return bool(checked)
def update_send_scenery_state(checked: bool): return bool(checked)
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
