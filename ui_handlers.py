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

import gemini_api, config_manager, alarm_manager, character_manager, utils
from tools import memory_tools
from timers import UnifiedTimer
from character_manager import get_character_files_paths
from memory_manager import load_memory_data_safe, save_memory_data

DAY_MAP_EN_TO_JA = {"mon": "月", "tue": "火", "wed": "水", "thu": "木", "fri": "金", "sat": "土", "sun": "日"}
DAY_MAP_JA_TO_EN = {v: k for k, v in DAY_MAP_EN_TO_JA.items()}

def handle_initial_load():
    """アプリ起動時に一度だけ呼ばれるハンドラ"""
    print("--- UI初期化処理(handle_initial_load)を開始します ---")

    df_with_ids = render_alarms_as_dataframe()
    display_df = get_display_df(df_with_ids)
    feedback_text = "アラームを選択してください"

    char_dependent_outputs = handle_character_change(config_manager.initial_character_global)

    return (display_df, df_with_ids, feedback_text) + char_dependent_outputs

def handle_character_change(character_name: str):
    """キャラクター選択時に呼ばれる単一司令塔ハンドラ"""
    if not character_name:
        character_name = character_manager.get_character_list()[0]

    print(f"--- UI更新司令塔(handle_character_change)実行: {character_name} ---")
    config_manager.save_config("last_character", character_name)

    log_f, _, img_p, mem_p, notepad_p = get_character_files_paths(character_name)
    chat_history, _ = utils.format_history_for_gradio(utils.load_chat_log(log_f, character_name)[-(config_manager.UI_HISTORY_MAX_LIMIT * 2):], character_name)
    memory_str = json.dumps(load_memory_data_safe(mem_p), indent=2, ensure_ascii=False)
    profile_image = img_p if img_p and os.path.exists(img_p) else None
    notepad_content = load_notepad_content(character_name)

    locations = get_location_list_for_ui(character_name)
    current_location_id = utils.get_current_location(character_name)
    memory_data = load_memory_data_safe(mem_p)
    current_location_name = memory_data.get("living_space", {}).get(current_location_id, {}).get("name", current_location_id)
    valid_location_ids = [loc[1] for loc in locations]
    location_dd_val = current_location_id if current_location_id in valid_location_ids else None
    scenery_text = "（AIとの対話開始時に生成されます）"

    effective_settings = config_manager.get_effective_settings(character_name)
    all_models = ["デフォルト"] + config_manager.AVAILABLE_MODELS_GLOBAL
    model_val = effective_settings["model_name"] if effective_settings["model_name"] != config_manager.initial_model_global else "デフォルト"
    voice_display_name = config_manager.SUPPORTED_VOICES.get(effective_settings["voice_id"], list(config_manager.SUPPORTED_VOICES.values())[0])
    voice_tone_prompt = effective_settings.get("voice_tone_prompt", "（デフォルトのトーン）")

    return (
        character_name, chat_history, "", profile_image, memory_str, character_name,
        character_name, notepad_content, gr.update(choices=locations, value=location_dd_val),
        current_location_name, scenery_text,
        gr.update(choices=all_models, value=model_val),
        voice_display_name,
        effective_settings["send_thoughts"],
        effective_settings["send_notepad"],
        effective_settings["use_common_prompt"],
        effective_settings["send_core_memory"],
        effective_settings["send_scenery"],
        f"ℹ️ *現在選択中のキャラクター「{character_name}」にのみ適用される設定です。*",
        voice_tone_prompt
    )

def handle_save_char_settings(
    character_name: str, model_name: str, voice_name: str,
    voice_tone_prompt: str,
    send_thoughts: bool, send_notepad: bool, use_common_prompt: bool,
    send_core_memory: bool, send_scenery: bool
):
    """キャラクター個別設定を一度に保存する司令塔ハンドラ"""
    if not character_name:
        gr.Warning("設定を保存するキャラクターが選択されていません。")
        return

    new_settings = {
        "model_name": model_name if model_name != "デフォルト" else None,
        "voice_id": next((k for k, v in config_manager.SUPPORTED_VOICES.items() if v == voice_name), None),
        "voice_tone_prompt": voice_tone_prompt,
        "send_thoughts": bool(send_thoughts),
        "send_notepad": bool(send_notepad),
        "use_common_prompt": bool(use_common_prompt),
        "send_core_memory": bool(send_core_memory),
        "send_scenery": bool(send_scenery),
    }

    try:
        char_config_path = os.path.join(config_manager.CHARACTERS_DIR, character_name, "character_config.json")
        config = {}
        if os.path.exists(char_config_path) and os.path.getsize(char_config_path) > 0:
            with open(char_config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

        if "override_settings" not in config:
            config["override_settings"] = {}

        config["override_settings"].update(new_settings)
        config["last_updated"] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        with open(char_config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        gr.Info(f"「{character_name}」の個別設定を保存しました。")

    except Exception as e:
        gr.Error(f"個別設定の保存中にエラーが発生しました: {e}")
        traceback.print_exc()

def update_token_count_from_state(character_name: str, api_key_name: str):
    """設定変更時に呼ばれる。テキスト入力は考慮せず、履歴とプロンプトのみで計算"""
    if not character_name or not api_key_name: return "入力トークン数: -"
    token_count_str = gemini_api.count_input_tokens(
        character_name=character_name,
        api_key_name=api_key_name,
        parts=[]
    )
    return token_count_str

def update_token_count_on_input(character_name: str, api_key_name: str, textbox_content: str, file_list: list):
    """テキスト入力やファイル添付時に呼ばれる。現在の入力内容を含めて計算"""
    if not character_name or not api_key_name: return "入力トークン数: -"

    parts_for_api = []
    if textbox_content:
        parts_for_api.append(textbox_content)
    if file_list:
        for file_obj in file_list:
            filepath = file_obj.name
            try:
                kind = filetype.guess(filepath)
                if kind and kind.mime.startswith("image/"):
                    parts_for_api.append(Image.open(filepath))
                else:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        parts_for_api.append(f.read())
            except Exception as e:
                print(f"Token count on input error (file handling): {e}")
                parts_for_api.append(f"[ファイル: {os.path.basename(filepath)}]")

    token_count_str = gemini_api.count_input_tokens(
        character_name=character_name,
        api_key_name=api_key_name,
        parts=parts_for_api
    )
    return token_count_str

def handle_message_submission(*args: Any):
    (textbox_content, chatbot_history, current_character_name, current_api_key_name_state, file_input_list, add_timestamp_checkbox, api_history_limit_state) = args

    user_prompt_from_textbox = textbox_content.strip() if textbox_content else ""
    if not user_prompt_from_textbox and not file_input_list:
        token_count = update_token_count_from_state(current_character_name, current_api_key_name_state)
        yield chatbot_history, gr.update(), gr.update(), token_count, gr.update(), gr.update(), gr.update(), gr.update()
        return

    log_message_parts = []
    if user_prompt_from_textbox:
        timestamp = f"\n\n{datetime.datetime.now().strftime('%Y-%m-%d (%a) %H:%M:%S')}" if add_timestamp_checkbox else ""
        processed_user_message = user_prompt_from_textbox + timestamp
        chatbot_history.append((processed_user_message, None))
        log_message_parts.append(processed_user_message)

    if file_input_list:
        for file_obj in file_input_list:
            filepath = file_obj.name
            filename = os.path.basename(filepath)
            chatbot_history.append(((filepath, filename), None))
            log_message_parts.append(f"[ファイル添付: {filepath}]")

    chatbot_history.append((None, "思考中... ▌"))

    token_count = update_token_count_on_input(current_character_name, current_api_key_name_state, textbox_content, file_input_list)

    yield (
        chatbot_history,
        gr.update(value=""),
        gr.update(value=None),
        token_count,
        gr.update(),
        gr.update(),
        gr.update(),
        gr.update()
    )

    response_data = {}
    try:
        agent_args = (
            textbox_content, chatbot_history, current_character_name,
            current_api_key_name_state, file_input_list, add_timestamp_checkbox,
            api_history_limit_state
        )
        response_data = gemini_api.invoke_nexus_agent(*agent_args)
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
    formatted_history, _ = utils.format_history_for_gradio(raw_history, current_character_name)

    token_count = update_token_count_from_state(current_character_name, current_api_key_name_state)

    new_alarm_df_with_ids = render_alarms_as_dataframe()
    new_display_df = get_display_df(new_alarm_df_with_ids)

    yield (
        formatted_history,
        gr.update(),
        gr.update(value=None),
        token_count,
        location_name,
        scenery_text,
        new_alarm_df_with_ids,
        new_display_df
    )
def handle_voice_preview(selected_voice_name: str, text_to_speak: str,
                         tone_prompt: str,
                         api_key_name: str):
    if not selected_voice_name or not text_to_speak or not api_key_name:
        gr.Warning("声、テキスト、APIキーがすべて選択されている必要があります。")
        return None

    voice_id = next((key for key, value in config_manager.SUPPORTED_VOICES.items() if value == selected_voice_name), None)
    api_key = config_manager.API_KEYS.get(api_key_name)

    if not voice_id or not api_key:
        gr.Warning("声またはAPIキーが無効です。")
        return None

    from audio_manager import generate_audio_from_text
    gr.Info(f"声「{selected_voice_name}」で音声を生成しています...")
    audio_filepath = generate_audio_from_text(text_to_speak, api_key, voice_id, tone_prompt)

    if audio_filepath:
        gr.Info("プレビューを再生します。")
        return audio_filepath
    else:
        gr.Error("音声の生成に失敗しました。")
        return None

def handle_play_audio_button_click(selected_message: Optional[Dict[str, str]], character_name: str, api_key_name: str):
    if not selected_message:
        gr.Warning("再生するメッセージが選択されていません。")
        return None

    raw_text = utils.extract_raw_text_from_html(selected_message.get("content"))
    text_to_speak = utils.remove_thoughts_from_text(raw_text)

    if not text_to_speak:
        gr.Info("このメッセージには音声で再生できるテキストがありません。")
        return None

    effective_settings = config_manager.get_effective_settings(character_name)
    voice_id = effective_settings.get("voice_id", "vindemiatrix")
    voice_tone_prompt = effective_settings.get("voice_tone_prompt")
    api_key = config_manager.API_KEYS.get(api_key_name)

    if not api_key:
        gr.Warning(f"APIキー '{api_key_name}' が見つかりません。")
        return None

    from audio_manager import generate_audio_from_text
    gr.Info(f"「{character_name}」の声で音声を生成しています...")
    audio_filepath = generate_audio_from_text(text_to_speak, api_key, voice_id, voice_tone_prompt)

    if audio_filepath:
        gr.Info("再生します。")
        return audio_filepath
    else:
        gr.Error("音声の生成に失敗しました。")
        return None

# ... (the rest of the handler functions are assumed to be here, unchanged) ...
def _get_display_history_count(api_history_limit_value: str) -> int:
    return int(api_history_limit_value) if api_history_limit_value.isdigit() else config_manager.UI_HISTORY_MAX_LIMIT

def reload_chat_log(character_name: Optional[str], api_history_limit_value: str):
    """チャットログを再読み込みしてUI用の形式で返す"""
    if not character_name:
        return [], []
    log_f, _, _, _, _ = get_character_files_paths(character_name)
    if not log_f or not os.path.exists(log_f):
        return [], []

    display_turns = _get_display_history_count(api_history_limit_value)
    raw_history = utils.load_chat_log(log_f, character_name)
    visible_history = raw_history[-(display_turns * 2):]

    # utils.pyの返り値は2つ (history, mapping_list)
    formatted_history, _ = utils.format_history_for_gradio(visible_history, character_name)

    return formatted_history

def update_model_state(model):
    """共通設定のモデル名を保存する"""
    config_manager.save_config("last_model", model)
    # Gradioはgr.Stateを更新するために値を返す必要がある
    return model

def update_api_key_state(api_key_name):
    """共通設定のAPIキー名を保存する"""
    config_manager.save_config("last_api_key_name", api_key_name)
    gr.Info(f"共通APIキーを '{api_key_name}' に設定しました。")
    return api_key_name

def update_timestamp_state(checked):
    """共通設定のタイムスタンプ追加設定を保存する"""
    config_manager.save_config("add_timestamp", bool(checked))

def update_api_history_limit_state_and_reload_chat(limit_ui_val: str, character_name: Optional[str]):
    """共通設定の履歴長を保存し、チャットをリロードする"""
    key = next((k for k, v in config_manager.API_HISTORY_LIMIT_OPTIONS.items() if v == limit_ui_val), "all")
    config_manager.save_config("last_api_history_limit_option", key)

    # チャットのリロード処理
    reloaded_history = reload_chat_log(character_name, key)

    return key, reloaded_history, gr.State()
