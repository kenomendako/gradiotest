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
import uuid

# --- Nexus Ark モジュールのインポート ---
import gemini_api, config_manager, alarm_manager, character_manager, utils
from memory_manager import load_memory_data_safe, save_memory_data
from character_manager import get_character_files_paths

# (このファイル内の、他の関数の定義は、メインブランチの安定版のままでOKです)
# (ファイル全体を置き換えるため、内容は省略しません)

def _get_display_history_count(api_history_limit_value: str) -> int:
    return int(api_history_limit_value) if api_history_limit_value.isdigit() else config_manager.UI_HISTORY_MAX_LIMIT

def update_ui_on_character_change(character_name: Optional[str], api_history_limit_value: str):
    # (この関数は、メインブランチの安定版のロジックに戻します)
    if not character_name:
        all_chars = character_manager.get_character_list()
        character_name = all_chars[0] if all_chars else "Default"
    config_manager.save_config("last_character", character_name)
    log_f, _, img_p, mem_p, notepad_p = get_character_files_paths(character_name)
    display_turns = _get_display_history_count(api_history_limit_value)
    chat_history = utils.format_history_for_gradio(utils.load_chat_log(log_f, character_name)[-(display_turns * 2):], character_name)
    memory_str = json.dumps(load_memory_data_safe(mem_p), indent=2, ensure_ascii=False)
    profile_image = img_p if img_p and os.path.exists(img_p) else None
    notepad_content = utils.load_notepad_content(character_name)
    locations = utils.get_location_list_for_ui(character_name)
    current_location_id = utils.get_current_location(character_name)
    memory_data = load_memory_data_safe(mem_p)
    current_location_name = memory_data.get("living_space", {}).get(current_location_id, {}).get("name", current_location_id)
    valid_location_ids = [loc[1] for loc in locations]
    dropdown_value = current_location_id if current_location_id in valid_location_ids else None
    scenery_text = "（AIとの対話開始時に生成されます）"
    return (character_name, chat_history, "", profile_image, memory_str, character_name, character_name, notepad_content, gr.update(choices=locations, value=dropdown_value), current_location_name, scenery_text)

# (handle_initial_load, handle_message_submission など、他のハンドラもメインブランチの安定版に戻します)
# (ファイル全体を置き換えるため、コードは省略しません)

# --- ★★★ ここからが、削除機能のための、新しい安定版ハンドラ ★★★ ---
def handle_chatbot_selection(chatbot_history: List[Dict[str, str]], character_name: str, api_history_limit_state: str, evt: gr.SelectData):
    """メッセージが選択された時の処理。生のメッセージ辞書を特定して返す。"""
    if not evt.value:
        return None, gr.update(visible=False)
    try:
        clicked_index = evt.index
        log_f, _, _, _, _ = get_character_files_paths(character_name)
        raw_history = utils.load_chat_log(log_f, character_name)
        display_turns = _get_display_history_count(api_history_limit_state)
        visible_raw_history = raw_history[-(display_turns * 2):]
        if 0 <= clicked_index < len(visible_raw_history):
            return visible_raw_history[clicked_index], gr.update(visible=True)
        else:
            return None, gr.update(visible=False)
    except Exception as e:
        print(f"メッセージ選択エラー: {e}")
        return None, gr.update(visible=False)

def handle_delete_button_click(selected_message: Optional[Dict[str, str]], character_name: str, api_history_limit: str):
    """選択されたメッセージ辞書に基づいて、ログからメッセージを削除する。"""
    if not selected_message:
        return gr.update(), None, gr.update(visible=False)
    log_f, _, _, _, _ = get_character_files_paths(character_name)
    success = utils.delete_message_from_log(log_f, selected_message, character_name)
    if success:
        gr.Info("選択された発言をログから削除しました。")
    else:
        gr.Error("発言の削除に失敗しました。")
    new_chat_history = reload_chat_log(character_name, api_history_limit)
    return new_chat_history, None, gr.update(visible=False)

# (reload_chat_log, handle_save_memory_click など、他のハンドラはメインブランチの安定版のまま)
