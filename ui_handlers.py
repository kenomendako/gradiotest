import shutil
import psutil
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


import gemini_api, config_manager, alarm_manager, room_manager, utils, constants, chatgpt_importer
from tools import timer_tools
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
    【修正】チャットタブと、それに付随する設定UIの更新のみを担当するヘルパー関数。
    戻り値の数は `initial_load_chat_outputs` の30個と一致する。
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
    memory_str = json.dumps(load_memory_data_safe(mem_p), indent=2, ensure_ascii=False)
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
    current_location_name, _, scenery_text = generate_scenery_context(room_name, api_key)
    scenery_image_path = utils.find_scenery_image(room_name, location_dd_val)
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

    # このタプルの要素数は30個
    chat_tab_updates = (
        room_name, chat_history, mapping_list,
        gr.update(value={'text': '', 'files': []}), # 2つの戻り値を、MultimodalTextbox用の1つの辞書に統合
        profile_image,
        memory_str, notepad_content, load_system_prompt_content(room_name),
        gr.update(choices=room_manager.get_room_list_for_ui(), value=room_name),
        gr.update(choices=room_manager.get_room_list_for_ui(), value=room_name),
        gr.update(choices=room_manager.get_room_list_for_ui(), value=room_name),
        gr.update(choices=locations_for_ui, value=location_dd_val),
        current_location_name, scenery_text,
        voice_display_name, voice_style_prompt_val,
        temp_val, top_p_val, harassment_val, hate_val, sexual_val, dangerous_val,
        effective_settings["add_timestamp"], effective_settings["send_thoughts"],
        effective_settings["send_notepad"], effective_settings["use_common_prompt"],
        effective_settings["send_core_memory"], effective_settings["send_scenery"],
        f"ℹ️ *現在選択中のルーム「{room_name}」にのみ適用される設定です。*",
        scenery_image_path
    )
    return chat_tab_updates

def _update_all_tabs_for_room_change(room_name: str, api_key_name: str):
    """
    【修正】ルーム切り替え時に、全ての関連タブのUIを更新する。
    戻り値の数は `all_room_change_outputs` の39個と一致する。
    """
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

    return chat_tab_updates + world_builder_updates + session_management_updates + (rules_df_for_ui,)


def handle_initial_load(initial_room_to_load: str, initial_api_key_name: str):
    """
    【修正】UIの初期化処理。戻り値の数は `initial_load_outputs` の35個と一致する。
    """
    print("--- UI初期化処理(handle_initial_load)を開始します ---")
    df_with_ids = render_alarms_as_dataframe()
    display_df, feedback_text = get_display_df(df_with_ids), "アラームを選択してください"

    # チャットタブ関連の31個の更新値を取得
    chat_tab_updates = _update_chat_tab_for_room_change(initial_room_to_load, initial_api_key_name)

    # 置換ルール関連の1個の更新値を取得
    rules = config_manager.load_redaction_rules()
    rules_df_for_ui = _create_redaction_df_from_rules(rules)

    # アラーム(3) + チャットタブ(31) + 置換ルール(1) = 35個の値を返す
    return (display_df, df_with_ids, feedback_text) + chat_tab_updates + (rules_df_for_ui,)

def handle_save_room_settings(
    room_name: str, voice_name: str, voice_style_prompt: str,
    temp: float, top_p: float, harassment: str, hate: str, sexual: str, dangerous: str,
    add_timestamp: bool, send_thoughts: bool, send_notepad: bool,
    use_common_prompt: bool, send_core_memory: bool, send_scenery: bool,
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
        "add_timestamp": bool(add_timestamp), "send_thoughts": bool(send_thoughts), "send_notepad": bool(send_notepad),
        "use_common_prompt": bool(use_common_prompt), "send_core_memory": bool(send_core_memory), "send_scenery": bool(send_scenery),
        "auto_memory_enabled": bool(auto_memory_enabled)
    }
    try:
        # 正しくは room_config.json を参照する
        room_config_path = os.path.join(constants.ROOMS_DIR, room_name, "room_config.json")
        config = {}
        # ファイルが存在しない場合も考慮（ensure_room_filesで作成されるはずだが念のため）
        if os.path.exists(room_config_path):
             if os.path.getsize(room_config_path) > 0:
                with open(room_config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
        else:
            # 万が一ファイルがない場合は、ここで基本的な構造を作成する
            gr.Warning(f"設定ファイルが見つからなかったため、新しく作成します: {room_config_path}")
            config = {
                "version": 1,
                "room_name": room_name,
                "user_display_name": "ユーザー",
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

def handle_context_settings_change(room_name: str, api_key_name: str, api_history_limit: str, add_timestamp: bool, send_thoughts: bool, send_notepad: bool, use_common_prompt: bool, send_core_memory: bool, send_scenery: bool):
    if not room_name or not api_key_name: return "入力トークン数: -"
    return gemini_api.count_input_tokens(
        room_name=room_name, api_key_name=api_key_name, parts=[],
        api_history_limit=api_history_limit,
        add_timestamp=add_timestamp, send_thoughts=send_thoughts, send_notepad=send_notepad,
        use_common_prompt=use_common_prompt, send_core_memory=send_core_memory, send_scenery=send_scenery
    )

def update_token_count_on_input(
    room_name: str,
    api_key_name: str,
    api_history_limit: str,
    multimodal_input: dict,
    add_timestamp: bool, send_thoughts: bool, send_notepad: bool,
    use_common_prompt: bool, send_core_memory: bool, send_scenery: bool
):
    if not room_name or not api_key_name: return "トークン数: -"
    textbox_content = multimodal_input.get("text", "") if multimodal_input else ""
    file_list = multimodal_input.get("files", []) if multimodal_input else []
    parts_for_api = []
    if textbox_content: parts_for_api.append(textbox_content)
    if file_list:
        for file_obj in file_list:
            try:
                if isinstance(file_obj, str):
                    parts_for_api.append(file_obj)
                else:
                    file_path = file_obj.name
                    file_basename = os.path.basename(file_path)
                    kind = filetype.guess(file_path)
                    if kind and kind.mime.startswith('image/'):
                        parts_for_api.append(Image.open(file_path))
                    else:
                        file_size = os.path.getsize(file_path)
                        parts_for_api.append(f"[ファイル添付: {file_basename}, サイズ: {file_size} bytes]")
            except Exception as e:
                print(f"トークン計算中のファイル処理エラー: {e}")
                error_source = "ペーストされたテキスト" if isinstance(file_obj, str) else f"ファイル「{os.path.basename(file_obj.name)}」"
                parts_for_api.append(f"[ファイル処理エラー: {error_source}]")
    effective_settings = config_manager.get_effective_settings(
        room_name,
        add_timestamp=add_timestamp, send_thoughts=send_thoughts,
        send_notepad=send_notepad, use_common_prompt=use_common_prompt,
        send_core_memory=send_core_memory, send_scenery=send_scenery
    )
    return gemini_api.count_input_tokens(
        room_name=room_name, api_key_name=api_key_name,
        api_history_limit=api_history_limit, parts=parts_for_api, **effective_settings
    )

def _stream_and_handle_response(
    room_to_respond: str,
    full_user_log_entry: str,
    user_prompt_parts_for_api: List[Dict],
    api_key_name: str,
    global_model: str,
    api_history_limit: str,
    debug_mode: bool,
    soul_vessel_room: str,
    active_participants: List[str],
    current_console_content: str
) -> Iterator[Tuple]:
    """
    【v2: 再生成対応】AIへのリクエスト送信とストリーミング応答処理を担う、中核となる内部ジェネレータ関数。
    """
    main_log_f, _, _, _, _ = get_room_files_paths(soul_vessel_room)
    effective_settings = config_manager.get_effective_settings(soul_vessel_room)
    add_timestamp = effective_settings.get("add_timestamp", False)
    chatbot_history, mapping_list = reload_chat_log(
        room_name=soul_vessel_room,
        api_history_limit_value=api_history_limit,
        add_timestamp=add_timestamp
    )

    try:
        # 1. UIをストリーミングモードに移行
        chatbot_history.append((None, "▌"))
        yield (chatbot_history, mapping_list, gr.update(value={'text': '', 'files': []}),
               gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(),
               current_console_content, current_console_content,
               # ▼▼▼【ここが修正点】ストップボタンは押せるようにする ▼▼▼
               gr.update(visible=True, interactive=True),
               # ▲▲▲【修正はここまで】▲▲▲
               gr.update(interactive=False)
        )

        # 2. グループ会話と情景のコンテキストを準備
        all_rooms_in_scene = [soul_vessel_room] + (active_participants or [])
        api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)
        shared_location_name, _, shared_scenery_text = generate_scenery_context(soul_vessel_room, api_key)

        # 3. AIごとの応答生成ループ
        for current_room in all_rooms_in_scene:
            chatbot_history[-1] = (None, f"思考中 ({current_room})... ▌")
            yield (chatbot_history, mapping_list, gr.update(), gr.update(), gr.update(),
                   gr.update(), gr.update(), gr.update(), gr.update(), gr.update(),
                   current_console_content, gr.update(), gr.update())

            # 4. APIに渡す引数を準備
            # グループ会話では、最初のAI（魂の器）のみがファイルを受け取り、他のAIはテキストのみを参照する
            final_user_prompt_parts = user_prompt_parts_for_api if current_room == soul_vessel_room else [{"type": "text", "text": full_user_log_entry}]

            agent_args_dict = {
                "room_to_respond": current_room, "api_key_name": api_key_name,
                "global_model_from_ui": global_model,
                "api_history_limit": api_history_limit, "debug_mode": debug_mode,
                "history_log_path": main_log_f, "user_prompt_parts": final_user_prompt_parts,
                "soul_vessel_room": soul_vessel_room, "active_participants": active_participants,
                "shared_location_name": shared_location_name, "shared_scenery_text": shared_scenery_text,
            }

            # 5. ストリーミング実行とUI更新
            streamed_text = ""
            final_state = None
            initial_message_count = 0
            with utils.capture_prints() as captured_output:
                for mode, chunk in gemini_api.invoke_nexus_agent_stream(agent_args_dict):
                    if mode == "initial_count": initial_message_count = chunk
                    elif mode == "messages":
                        message_chunk, _ = chunk
                        if isinstance(message_chunk, AIMessageChunk):
                            streamed_text += message_chunk.content
                            chatbot_history[-1] = (None, streamed_text + "▌")
                            yield (chatbot_history, mapping_list, gr.update(), gr.update(),
                                   gr.update(), gr.update(), gr.update(), gr.update(),
                                   gr.update(), gr.update(), current_console_content,
                                   gr.update(), gr.update())
                    elif mode == "values": final_state = chunk
            current_console_content += captured_output.getvalue()

            # 6. 最終応答の処理とログ保存
            final_response_text = ""
            all_turn_popups = []
            if final_state:
                new_messages = final_state["messages"][initial_message_count:]
                for msg in new_messages:
                    if isinstance(msg, ToolMessage):
                        popup_text = utils.format_tool_result_for_ui(msg.name, str(msg.content))
                        if popup_text: all_turn_popups.append(popup_text)
                last_ai_message = final_state["messages"][-1]
                if isinstance(last_ai_message, AIMessage): final_response_text = last_ai_message.content

            final_response_text = final_response_text or streamed_text
            chatbot_history[-1] = (None, final_response_text)

            if final_response_text.strip():
                utils.save_message_to_log(main_log_f, f"## AGENT:{current_room}", final_response_text)

        for popup_message in all_turn_popups: gr.Info(popup_message)

    finally:
        # 7. 処理完了後の最終的なUI更新
        final_chatbot_history, final_mapping_list = reload_chat_log(
            room_name=soul_vessel_room,
            api_history_limit_value=api_history_limit,
            add_timestamp=add_timestamp
        )
        api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)
        new_location_name, _, new_scenery_text = generate_scenery_context(soul_vessel_room, api_key)
        scenery_image = utils.find_scenery_image(soul_vessel_room, utils.get_current_location(soul_vessel_room))
        token_calc_kwargs = config_manager.get_effective_settings(soul_vessel_room, global_model_from_ui=global_model)
        token_count_text = gemini_api.count_input_tokens(
            room_name=soul_vessel_room, api_key_name=api_key_name,
            api_history_limit=api_history_limit, parts=[], **token_calc_kwargs
        )
        final_df_with_ids = render_alarms_as_dataframe()
        final_df = get_display_df(final_df_with_ids)

        yield (final_chatbot_history, final_mapping_list, gr.update(), token_count_text,
               new_location_name, new_scenery_text,
               final_df_with_ids, final_df, scenery_image,
               current_console_content, current_console_content,
               gr.update(visible=False, interactive=True), gr.update(interactive=True)) # Stopボタン非表示, ボタン有効化

def handle_message_submission(*args: Any):
    """
    【v4: ペースト挙動FIX】新規メッセージの送信を処理する司令塔。
    """
    (multimodal_input, soul_vessel_room, api_key_name,
     api_history_limit, debug_mode, auto_memory_enabled,
     console_content, active_participants, global_model) = args

    # 1. ユーザー入力を解析
    textbox_content = multimodal_input.get("text", "") if multimodal_input else ""
    file_input_list = multimodal_input.get("files", []) if multimodal_input else []
    user_prompt_from_textbox = textbox_content.strip() if textbox_content else ""

    log_message_parts = []
    # タイムスタンプはUI設定(add_timestamp)に関わらず、常にログに記録する。
    # UIでの表示/非表示は、表示用のフォーマッタ(format_history_for_gradio)が担当する。
    timestamp = f"\n\n{datetime.datetime.now().strftime('%Y-%m-%d (%a) %H:%M:%S')}"

    if user_prompt_from_textbox:
        log_message_parts.append(user_prompt_from_textbox + timestamp)

    if file_input_list:
        for file_obj in file_input_list:
            if isinstance(file_obj, str):
                log_message_parts.append(file_obj)
            else:
                log_message_parts.append(f"[ファイル添付: {os.path.basename(file_obj.name)}]")

    full_user_log_entry = "\n".join(log_message_parts).strip()

    if not full_user_log_entry:
        effective_settings = config_manager.get_effective_settings(soul_vessel_room)
        add_timestamp = effective_settings.get("add_timestamp", False)
        history, mapping = reload_chat_log(soul_vessel_room, api_history_limit, add_timestamp)
        yield (history, mapping, gr.update(), gr.update(), gr.update(), gr.update(),
               gr.update(), gr.update(), gr.update(), console_content, console_content,
               gr.update(visible=False), gr.update(interactive=True))
        return

    main_log_f, _, _, _, _ = get_room_files_paths(soul_vessel_room)
    utils.save_message_to_log(main_log_f, "## USER:user", full_user_log_entry)

    # 2. API用の入力パーツを準備
    user_prompt_parts_for_api = []
    if user_prompt_from_textbox:
        user_prompt_parts_for_api.append({"type": "text", "text": user_prompt_from_textbox})

    if file_input_list:
        for file_obj in file_input_list:
            try:
                if isinstance(file_obj, str):
                    content = file_obj
                    if not user_prompt_from_textbox and content:
                         user_prompt_parts_for_api.append({"type": "text", "text": content})
                    else:
                        user_prompt_parts_for_api.append({"type": "text", "text": f"添付されたテキストの内容:\n---\n{content}\n---"})
                else:
                    file_path = file_obj.name
                    file_basename = os.path.basename(file_path)
                    kind = filetype.guess(file_path)
                    if kind and kind.mime.startswith('image/'):
                        with open(file_path, "rb") as f:
                            encoded_string = base64.b64encode(f.read()).decode("utf-8")
                        user_prompt_parts_for_api.append({"type": "image_url", "image_url": {"url": f"data:{kind.mime};base64,{encoded_string}"}})
                    else:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                        user_prompt_parts_for_api.append({"type": "text", "text": f"添付ファイル「{file_basename}」の内容:\n---\n{content}\n---"})
            except Exception as e:
                print(f"--- ファイル処理中にエラー: {e} ---")
                traceback.print_exc()
                error_source = "ペーストされたテキスト" if isinstance(file_obj, str) else f"ファイル「{os.path.basename(file_obj.name)}」"
                user_prompt_parts_for_api.append({"type": "text", "text": f"（{error_source}の処理中にエラー）"})


    # 3. 中核となるストリーミング関数を呼び出す
    yield from _stream_and_handle_response(
        room_to_respond=soul_vessel_room,
        full_user_log_entry=full_user_log_entry,
        user_prompt_parts_for_api=user_prompt_parts_for_api,
        api_key_name=api_key_name,
        global_model=global_model,
        api_history_limit=api_history_limit,
        debug_mode=debug_mode,
        soul_vessel_room=soul_vessel_room,
        active_participants=active_participants or [],
        current_console_content=console_content
    )

def handle_rerun_button_click(*args: Any):
    """
    【v2: ストリーミング対応】発言の再生成を処理する司令塔。
    """
    (selected_message, room_name, api_key_name,
     api_history_limit, debug_mode,
     console_content, active_participants, global_model) = args

    if not selected_message or not room_name:
        gr.Warning("再生成の起点となるメッセージが選択されていません。")
        yield (gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(),
               gr.update(), gr.update(), gr.update(), console_content, console_content,
               gr.update(visible=True, interactive=True), gr.update(interactive=True))
        return

    # 1. ログを巻き戻し、再送信するユーザー発言を取得
    log_f, _, _, _, _ = get_room_files_paths(room_name)
    is_ai_message = selected_message.get("role") == "AGENT"

    restored_input_text = None
    if is_ai_message:
        restored_input_text = utils.delete_and_get_previous_user_input(log_f, selected_message)
    else: # ユーザー発言の場合
        restored_input_text = utils.delete_user_message_and_after(log_f, selected_message)

    if restored_input_text is None:
        gr.Error("ログの巻き戻しに失敗しました。再生成できません。")
        effective_settings = config_manager.get_effective_settings(room_name)
        add_timestamp = effective_settings.get("add_timestamp", False)
        history, mapping = reload_chat_log(room_name, api_history_limit, add_timestamp)
        yield (history, mapping, gr.update(), gr.update(), gr.update(), gr.update(),
               gr.update(), gr.update(), gr.update(), console_content, console_content,
               gr.update(visible=True, interactive=True), gr.update(interactive=True))
        return

    # 2. 巻き戻したユーザー発言を、タイムスタンプを更新してログに再保存
    full_user_log_entry = restored_input_text # タイムスタンプはここで更新しない（元の形式を維持）
    utils.save_message_to_log(log_f, "## USER:user", full_user_log_entry)

    gr.Info("応答を再生成します...")
    user_prompt_parts_for_api = [{"type": "text", "text": restored_input_text}]

    # 3. 中核となるストリーミング関数を呼び出す
    yield from _stream_and_handle_response(
        room_to_respond=room_name,
        full_user_log_entry=full_user_log_entry,
        user_prompt_parts_for_api=user_prompt_parts_for_api,
        api_key_name=api_key_name,
        global_model=global_model,
        api_history_limit=api_history_limit,
        debug_mode=debug_mode,
        soul_vessel_room=room_name,
        active_participants=active_participants or [],
        current_console_content=console_content
    )

def handle_scenery_refresh(room_name: str, api_key_name: str) -> Tuple[str, str, Optional[str]]:
    if not room_name or not api_key_name:
        return "（ルームまたはAPIキーが未選択です）", "（ルームまたはAPIキーが未選択です）", None

    api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)
    if not api_key:
        gr.Warning(f"APIキー '{api_key_name}' が見つかりません。")
        return "（APIキーエラー）", "（APIキーエラー）", None

    gr.Info(f"「{room_name}」の現在の情景を強制的に再生成しています...")

    location_name, _, scenery_text = generate_scenery_context(room_name, api_key, force_regenerate=True)

    if not location_name.startswith("（"):
        gr.Info("情景を再生成しました。")
        scenery_image_path = utils.find_scenery_image(room_name, utils.get_current_location(room_name))
    else:
        gr.Error("情景の再生成に失敗しました。")
        scenery_image_path = None

    return location_name, scenery_text, scenery_image_path

def handle_location_change(room_name: str, selected_value: str, api_key_name: str) -> Tuple[str, str, Optional[str]]:
    if not selected_value or selected_value.startswith("__AREA_HEADER_"):
        location_name, _, scenery_text = generate_scenery_context(room_name, config_manager.GEMINI_API_KEYS.get(api_key_name))
        scenery_image_path = utils.find_scenery_image(room_name, utils.get_current_location(room_name))
        return location_name, scenery_text, scenery_image_path

    location_id = selected_value

    from tools.space_tools import set_current_location
    print(f"--- UIからの場所変更処理開始: ルーム='{room_name}', 移動先ID='{location_id}' ---")

    scenery_cache = utils.load_scenery_cache(room_name)
    current_loc_name = scenery_cache.get("location_name", "（場所不明）")
    scenery_text = scenery_cache.get("scenery_text", "（情景不明）")
    current_image_path = utils.find_scenery_image(room_name, utils.get_current_location(room_name))

    if not room_name or not location_id:
        gr.Warning("ルームと移動先の場所を選択してください。")
        return current_loc_name, scenery_text, current_image_path

    result = set_current_location.func(location_id=location_id, room_name=room_name)
    if "Success" not in result:
        gr.Error(f"場所の変更に失敗しました: {result}")
        return current_loc_name, scenery_text, current_image_path

    gr.Info(f"場所を「{location_id}」に移動しました。情景を更新します...")

    api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)
    if not api_key:
        gr.Warning(f"APIキー '{api_key_name}' が見つかりません。")
        return "（APIキーエラー）", "（APIキーエラー）", None

    new_location_name, _, new_scenery_text = generate_scenery_context(room_name, api_key)
    new_image_path = utils.find_scenery_image(room_name, location_id)

    return new_location_name, new_scenery_text, new_image_path

#
# --- Room Management Handlers ---
#

def handle_create_room(new_room_name: str, new_user_display_name: str, initial_system_prompt: str):
    """
    「新規作成」タブのロジック。
    新しいチャットルームを作成し、関連ファイルと設定を初期化する。
    """
    # 1. 入力検証
    if not new_room_name or not new_room_name.strip():
        gr.Warning("ルーム名は必須です。")
        # nexus_ark.pyのoutputsは7つ
        return gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update()

    try:
        # 2. 安全なフォルダ名生成
        safe_folder_name = room_manager.generate_safe_folder_name(new_room_name)

        # 3. ルームファイル群の作成
        if not room_manager.ensure_room_files(safe_folder_name):
            gr.Error("ルームの基本ファイル作成に失敗しました。詳細はターミナルを確認してください。")
            return gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update()

        # 4. 設定の書き込み
        config_path = os.path.join(constants.ROOMS_DIR, safe_folder_name, "room_config.json")
        with open(config_path, "r+", encoding="utf-8") as f:
            config = json.load(f)
            config["room_name"] = new_room_name.strip()
            if new_user_display_name and new_user_display_name.strip():
                config["user_display_name"] = new_user_display_name.strip()
            f.seek(0)
            json.dump(config, f, indent=2, ensure_ascii=False)
            f.truncate()

        if initial_system_prompt and initial_system_prompt.strip():
            system_prompt_path = os.path.join(constants.ROOMS_DIR, safe_folder_name, "SystemPrompt.txt")
            with open(system_prompt_path, "w", encoding="utf-8") as f:
                f.write(initial_system_prompt)

        # 5. UI更新
        gr.Info(f"新しいルーム「{new_room_name}」を作成しました。")
        updated_room_list = room_manager.get_room_list_for_ui()

        # フォームのクリア
        clear_form = (gr.update(value=""), gr.update(value=""), gr.update(value=""))

        # 全てのドロップダウンを更新し、新しいルームを選択状態にする
        main_dd = gr.update(choices=updated_room_list, value=safe_folder_name)
        manage_dd = gr.update(choices=updated_room_list, value=safe_folder_name) # 管理タブも更新
        alarm_dd = gr.update(choices=updated_room_list, value=safe_folder_name)
        timer_dd = gr.update(choices=updated_room_list, value=safe_folder_name)

        return main_dd, manage_dd, alarm_dd, timer_dd, *clear_form

    except Exception as e:
        gr.Error(f"ルームの作成に失敗しました。詳細はターミナルを確認してください。: {e}")
        traceback.print_exc()
        return gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update()

def handle_manage_room_select(selected_folder_name: str):
    """
    「管理」タブのルームセレクタ変更時のロジック。
    選択されたルームの情報をフォームに表示する。
    """
    if not selected_folder_name:
        return gr.update(visible=False), "", "", "", "", ""

    try:
        config_path = os.path.join(constants.ROOMS_DIR, selected_folder_name, "room_config.json")
        if not os.path.exists(config_path):
            gr.Warning(f"設定ファイルが見つかりません: {config_path}")
            return gr.update(visible=False), "", "", "", "", ""

        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        return (
            gr.update(visible=True),
            config.get("room_name", ""),
            config.get("user_display_name", ""),
            config.get("agent_display_name", ""), # agent_display_nameを読み込む
            config.get("description", ""),
            selected_folder_name
        )
    except Exception as e:
        gr.Error(f"ルーム設定の読み込み中にエラーが発生しました: {e}")
        traceback.print_exc()
        return gr.update(visible=False), "", "", "", "", ""

def handle_save_room_config(folder_name: str, room_name: str, user_display_name: str, agent_display_name: str, description: str):
    """
    「管理」タブの保存ボタンのロジック。
    ルームの設定情報を更新する。
    """
    if not folder_name:
        gr.Error("対象のルームフォルダが見つかりません。")
        return gr.update(), gr.update()

    if not room_name or not room_name.strip():
        gr.Warning("ルーム名は空にできません。")
        return gr.update(), gr.update()

    try:
        config_path = os.path.join(constants.ROOMS_DIR, folder_name, "room_config.json")
        with open(config_path, "r+", encoding="utf-8") as f:
            config = json.load(f)
            config["room_name"] = room_name.strip()
            config["user_display_name"] = user_display_name.strip()
            config["agent_display_name"] = agent_display_name.strip() # agent_display_nameを保存
            config["description"] = description.strip()
            f.seek(0)
            json.dump(config, f, indent=2, ensure_ascii=False)
            f.truncate()

        gr.Info(f"ルーム「{room_name}」の設定を保存しました。")

        updated_room_list = room_manager.get_room_list_for_ui()

        # メインと管理タブのドロップダウンを更新
        main_dd_update = gr.update(choices=updated_room_list)
        manage_dd_update = gr.update(choices=updated_room_list)

        return main_dd_update, manage_dd_update

    except Exception as e:
        gr.Error(f"設定の保存中にエラーが発生しました: {e}")
        traceback.print_exc()
        return gr.update(), gr.update()

def handle_delete_room(folder_name_to_delete: str, confirmed: bool, api_key_name: str):

    NUM_ALL_ROOM_CHANGE_OUTPUTS = 38

    if not confirmed:
        return (gr.update(),) * NUM_ALL_ROOM_CHANGE_OUTPUTS

    if not folder_name_to_delete:
        gr.Warning("削除するルームが選択されていません。")
        return (gr.update(),) * NUM_ALL_ROOM_CHANGE_OUTPUTS

    try:
        room_path_to_delete = os.path.join(constants.ROOMS_DIR, folder_name_to_delete)
        if not os.path.isdir(room_path_to_delete):
            gr.Error(f"削除対象のフォルダが見つかりません: {room_path_to_delete}")
            return (gr.update(),) * NUM_ALL_ROOM_CHANGE_OUTPUTS

        shutil.rmtree(room_path_to_delete)
        gr.Info(f"ルーム「{folder_name_to_delete}」を完全に削除しました。")

        new_room_list = room_manager.get_room_list_for_ui()
        if not new_room_list:
            gr.Warning("全てのルームが削除されました。新しいルームを作成してください。")
            # This is the "empty" state for `initial_load_chat_outputs`
            empty_chat_outputs = (
                None, [], [], "", gr.update(value=None), None, "{}", "", "",
                gr.update(choices=[], value=None), gr.update(choices=[], value=None), gr.update(choices=[], value=None), gr.update(choices=[], value=None),
                "", "", gr.update(choices=[], value=None), "", "", 0.8, 0.95, "高リスクのみブロック", "高リスクのみブロック", "高リスクのみブロック", "高リスクのみブロック",
                False, True, True, False, True, True, "ℹ️ *ルームを選択してください*", None
            )
            # This is the "empty" state for `world_builder_outputs`
            empty_wb_outputs = ({}, gr.update(choices=[]), "",)
            # This is the "empty" state for `session_management_outputs`
            empty_session_outputs = ([], "ルームがありません", gr.update(choices=[]),)
            return empty_chat_outputs + empty_wb_outputs + empty_session_outputs

        new_main_room_folder = new_room_list[0][1]

        return handle_room_change_for_all_tabs(new_main_room_folder, api_key_name)

    except Exception as e:
        gr.Error(f"ルームの削除中にエラーが発生しました: {e}")
        traceback.print_exc()
        return (gr.update(),) * NUM_ALL_ROOM_CHANGE_OUTPUTS


#
# --- ChatGPT Importer Handlers ---
#

def handle_chatgpt_file_upload(file_obj: Optional[Any]) -> Tuple[gr.update, gr.update, list]:
    """
    ChatGPTのjsonファイルがアップロードされたときの処理。
    ファイルをストリーミングで解析し、会話のリストを生成する。
    """
    # file_obj is a single FileData object when file_count="single"
    if file_obj is None:
        return gr.update(choices=[], value=None), gr.update(visible=False), []

    try:
        choices = []
        with open(file_obj.name, 'rb') as f:
            # ijsonを使ってルートレベルの配列をストリーミング
            for conversation in ijson.items(f, 'item'):
                if conversation and 'mapping' in conversation and 'title' in conversation:
                    # 仕様通り、IDはmappingの最初のキー
                    convo_id = next(iter(conversation['mapping']), None)
                    title = conversation.get('title', 'No Title')
                    if convo_id and title:
                        choices.append((title, convo_id))

        if not choices:
            gr.Warning("これは有効なChatGPTエクスポートファイルではないようです。ファイルを確認してください。")
            return gr.update(choices=[], value=None), gr.update(visible=False), []

        sorted_choices = sorted(choices)
        # ドロップダウンを更新し、フォームを表示し、選択肢リストをStateに渡す
        return gr.update(choices=sorted_choices, value=None), gr.update(visible=True), sorted_choices

    except (ijson.JSONError, IOError, StopIteration, Exception) as e:
        gr.Warning("これは有効なChatGPTエクスポートファイルではないようです。ファイルを確認してください。")
        print(f"Error processing ChatGPT export file: {e}")
        traceback.print_exc()
        return gr.update(choices=[], value=None), gr.update(visible=False), []


def handle_chatgpt_thread_selection(choices_list: list, evt: gr.SelectData) -> gr.update:
    """
    会話スレッドが選択されたとき、そのタイトルをルーム名テキストボックスにコピーする。
    """
    if not evt or not choices_list:
        return gr.update()

    selected_id = evt.value
    # choices_listの中から、IDが一致するもののタイトルを探す
    for title, convo_id in choices_list:
        if convo_id == selected_id:
            return gr.update(value=title)

    return gr.update() # 見つからなかった場合は何もしない


def handle_chatgpt_import_button_click(
    file_obj: Optional[Any],
    conversation_id: str,
    room_name: str,
    user_display_name: str
) -> Tuple[gr.update, gr.update, gr.update, gr.update, gr.update, gr.update]:
    """
    「インポート」ボタンがクリックされたときの処理。
    コアロジックを呼び出し、結果に応じてUIを更新する。
    """
    # 1. 入力検証
    if not all([file_obj, conversation_id, room_name]):
        gr.Warning("ファイル、会話スレッド、新しいルーム名はすべて必須です。")
        # 6つのコンポーネントを更新するので6つのupdateを返す
        return tuple(gr.update() for _ in range(6))

    try:
        # 2. コアロジックの呼び出し
        safe_folder_name = chatgpt_importer.import_from_chatgpt_export(
            file_path=file_obj.name,
            conversation_id=conversation_id,
            room_name=room_name,
            user_display_name=user_display_name
        )

        # 3. 結果に応じたUI更新
        if safe_folder_name:
            gr.Info(f"会話「{room_name}」のインポートに成功しました。")

            # UIのドロップダウンを更新するために最新のルームリストを取得
            updated_room_list = room_manager.get_room_list_for_ui()

            # フォームをリセットし、非表示にする
            reset_file = gr.update(value=None)
            hide_form = gr.update(visible=False, value=None) # Dropdownのchoicesもリセット

            # 各ドロップダウンを更新し、新しく作ったルームを選択状態にする
            dd_update = gr.update(choices=updated_room_list, value=safe_folder_name)

            # file, form, room_dd, manage_dd, alarm_dd, timer_dd
            return reset_file, hide_form, dd_update, dd_update, dd_update, dd_update
        else:
            gr.Error("インポート処理中に予期せぬエラーが発生しました。詳細はターミナルを確認してください。")
            return tuple(gr.update() for _ in range(6))

    except Exception as e:
        gr.Error(f"インポート処理中に予期せぬエラーが発生しました。詳細はターミナルを確認してください。")
        print(f"Error during import button click: {e}")
        traceback.print_exc()
        return tuple(gr.update() for _ in range(6))


def _get_display_history_count(api_history_limit_value: str) -> int: return int(api_history_limit_value) if api_history_limit_value.isdigit() else constants.UI_HISTORY_MAX_LIMIT

def handle_chatbot_selection(room_name: str, api_history_limit_state: str, mapping_list: list, evt: gr.SelectData):
    if not room_name or evt.index is None or not mapping_list:
        return None, gr.update(visible=False), gr.update(interactive=True)

    try:
        clicked_ui_index = evt.index[0]
        if not (0 <= clicked_ui_index < len(mapping_list)):
            gr.Warning(f"クリックされたメッセージを特定できませんでした (UI index out of bounds).")
            return None, gr.update(visible=False), gr.update(interactive=True)

        log_f, _, _, _, _ = get_room_files_paths(room_name)
        raw_history = utils.load_chat_log(log_f)
        display_turns = _get_display_history_count(api_history_limit_state)
        visible_raw_history = raw_history[-(display_turns * 2):]

        original_log_index = mapping_list[clicked_ui_index]
        if 0 <= original_log_index < len(visible_raw_history):
            selected_msg = visible_raw_history[original_log_index]
            is_ai_message = selected_msg.get("responder") != "user"
            return (
                selected_msg,
                gr.update(visible=True),
                gr.update(interactive=is_ai_message)
            )
        else:
            gr.Warning(f"クリックされたメッセージを特定できませんでした (Original log index out of bounds).")
            return None, gr.update(visible=False), gr.update(interactive=True)

    except Exception as e:
        print(f"チャットボット選択中のエラー: {e}"); traceback.print_exc()
        return None, gr.update(visible=False), gr.update(interactive=True)

def handle_delete_button_click(message_to_delete: Optional[Dict[str, str]], room_name: str, api_history_limit: str):
    if not message_to_delete:
        return gr.update(), gr.update(), None, gr.update(visible=False)

    log_f, _, _, _, _ = get_room_files_paths(room_name)
    if utils.delete_message_from_log(log_f, message_to_delete):
        gr.Info("ログからメッセージを削除しました。")
    else:
        gr.Error("メッセージの削除に失敗しました。詳細はターミナルを確認してください。")

    effective_settings = config_manager.get_effective_settings(room_name)
    add_timestamp = effective_settings.get("add_timestamp", False)
    history, mapping_list = reload_chat_log(room_name, api_history_limit, add_timestamp)
    return history, mapping_list, None, gr.update(visible=False)

def reload_chat_log(
    room_name: Optional[str],
    api_history_limit_value: str,
    add_timestamp: bool,
    screenshot_mode: bool = False,
    redaction_rules: List[Dict] = None
):
    if not room_name:
        return [], []

    log_f,_,_,_,_ = get_room_files_paths(room_name)
    if not log_f or not os.path.exists(log_f):
        return [], []

    full_raw_history = utils.load_chat_log(log_f)
    display_turns = _get_display_history_count(api_history_limit_value)
    visible_history = full_raw_history[-(display_turns * 2):]
    history, mapping_list = utils.format_history_for_gradio(
        messages=visible_history,
        current_room_folder=room_name,
        add_timestamp=add_timestamp,
        screenshot_mode=screenshot_mode,
        redaction_rules=redaction_rules
    )
    return history, mapping_list

def handle_wb_add_place_button_click(area_selector_value: Optional[str]):
    if not area_selector_value:
        gr.Warning("まず、場所を追加したいエリアを選択してください。")
        return "place", gr.update(visible=False), "#### 新しい場所の作成"
    return "place", gr.update(visible=True), "#### 新しい場所の作成"

def handle_save_memory_click(room_name, json_string_data):
    if not room_name: gr.Warning("ルームが選択されていません。"); return gr.update()
    try: return save_memory_data(room_name, json_string_data)
    except Exception as e: gr.Error(f"記憶の保存中にエラーが発生しました: {e}"); return gr.update()

def handle_reload_memory(room_name: str) -> str:
    if not room_name: gr.Warning("ルームが選択されていません。"); return "{}"
    gr.Info(f"「{room_name}」の記憶を再読み込みしました。"); _, _, _, memory_json_path, _ = get_room_files_paths(room_name); return json.dumps(load_memory_data_safe(memory_json_path), indent=2, ensure_ascii=False)

def load_notepad_content(room_name: str) -> str:
    if not room_name: return ""
    _, _, _, _, notepad_path = get_room_files_paths(room_name)
    if notepad_path and os.path.exists(notepad_path):
        with open(notepad_path, "r", encoding="utf-8") as f: return f.read()
    return ""

def handle_save_notepad_click(room_name: str, content: str) -> str:
    if not room_name: gr.Warning("ルームが選択されていません。"); return content
    _, _, _, _, notepad_path = room_manager.get_room_files_paths(room_name)
    if not notepad_path: gr.Error(f"「{room_name}」のメモ帳パス取得失敗。"); return content
    lines = [f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}] {line.strip()}" if line.strip() and not re.match(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\]", line.strip()) else line.strip() for line in content.strip().split('\n') if line.strip()]
    final_content = "\n".join(lines)
    try:
        with open(notepad_path, "w", encoding="utf-8") as f: f.write(final_content + ('\n' if final_content else ''))
        gr.Info(f"「{room_name}」のメモ帳を保存しました。"); return final_content
    except Exception as e: gr.Error(f"メモ帳の保存エラー: {e}"); return content

def handle_clear_notepad_click(room_name: str) -> str:
    if not room_name: gr.Warning("ルームが選択されていません。"); return ""
    _, _, _, _, notepad_path = room_manager.get_room_files_paths(room_name)
    if not notepad_path: gr.Error(f"「{room_name}」のメモ帳パス取得失敗。"); return ""
    try:
        with open(notepad_path, "w", encoding="utf-8") as f: f.write("")
        gr.Info(f"「{room_name}」のメモ帳を空にしました。"); return ""
    except Exception as e: gr.Error(f"メモ帳クリアエラー: {e}"); return f"エラー: {e}"

def handle_reload_notepad(room_name: str) -> str:
    if not room_name: gr.Warning("ルームが選択されていません。"); return ""
    content = load_notepad_content(room_name); gr.Info(f"「{room_name}」のメモ帳を再読み込みしました。"); return content

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
        all_rows.append({"ID": a.get("id"), "状態": a.get("enabled", False), "時刻": a.get("time"), "予定": schedule_display, "ルーム": a.get("character"), "内容": a.get("context_memo") or ""})
    return pd.DataFrame(all_rows, columns=["ID", "状態", "時刻", "予定", "ルーム", "内容"])

def get_display_df(df_with_id: pd.DataFrame):
    if df_with_id is None or df_with_id.empty: return pd.DataFrame(columns=["状態", "時刻", "予定", "ルーム", "内容"])
    return df_with_id[["状態", "時刻", "予定", "ルーム", "内容"]] if 'ID' in df_with_id.columns else df_with_id

def handle_alarm_selection(evt: gr.SelectData, df_with_id: pd.DataFrame) -> List[str]:
    if not hasattr(evt, 'index') or evt.index is None or df_with_id is None or df_with_id.empty:
        return []
    row_index = evt.index[0]
    if 0 <= row_index < len(df_with_id):
        selected_id = str(df_with_id.iloc[row_index]['ID'])
        return [selected_id]
    return []

def handle_alarm_selection_for_all_updates(evt: gr.SelectData, df_with_id: pd.DataFrame):
    selected_ids = handle_alarm_selection(evt, df_with_id)
    feedback_text = "アラームを選択してください" if not selected_ids else f"{len(selected_ids)} 件のアラームを選択中"

    all_rooms = room_manager.get_room_list()
    default_room = all_rooms[0] if all_rooms else "Default"

    if len(selected_ids) == 1:
        alarm = next((a for a in alarm_manager.load_alarms() if a.get("id") == selected_ids[0]), None)
        if alarm:
            h, m = alarm.get("time", "08:00").split(":")
            days_ja = [DAY_MAP_EN_TO_JA.get(d.lower(), d.upper()) for d in alarm.get("days", [])]

            form_updates = (
                "アラーム更新", alarm.get("context_memo", ""), alarm.get("character", default_room),
                days_ja, alarm.get("is_emergency", False), h, m, selected_ids[0]
            )
            cancel_button_visibility = gr.update(visible=True)
        else:
            form_updates = ("アラーム追加", "", default_room, [], False, "08", "00", None)
            cancel_button_visibility = gr.update(visible=False)
    else:
        form_updates = ("アラーム追加", "", default_room, [], False, "08", "00", None)
        cancel_button_visibility = gr.update(visible=False)

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

def handle_delete_alarms_and_update_ui(selected_ids: list):
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
    all_rooms = room_manager.get_room_list()
    default_room = all_rooms[0] if all_rooms else "Default"
    return (
        "アラーム追加", "", gr.update(choices=all_rooms, value=default_room),
        [], False, "08", "00", None, [], "アラームを選択してください",
        gr.update(visible=False)
    )

def handle_add_or_update_alarm(editing_id, h, m, room, context, days_ja, is_emergency):
    from tools.alarm_tools import set_personal_alarm
    context_memo = context.strip() if context and context.strip() else "時間になりました"
    days_en = [DAY_MAP_JA_TO_EN.get(d) for d in days_ja if d in DAY_MAP_JA_TO_EN]

    if editing_id:
        alarm_manager.delete_alarm(editing_id)
        gr.Info(f"アラームID:{editing_id} を更新しました。")
    else:
        gr.Info(f"新しいアラームを追加しました。")

    set_personal_alarm.func(time=f"{h}:{m}", context_memo=context_memo, room_name=room, days=days_en, date=None, is_emergency=is_emergency)

    new_df_with_ids = render_alarms_as_dataframe()
    all_rooms = room_manager.get_room_list()
    default_room = all_rooms[0] if all_rooms else "Default"

    return (
        new_df_with_ids, get_display_df(new_df_with_ids),
        "アラーム追加", "", gr.update(choices=all_rooms, value=default_room),
        [], False, "08", "00", None, [], "アラームを選択してください",
        gr.update(visible=False)
    )

def handle_timer_submission(timer_type, duration, work, brk, cycles, room, work_theme, brk_theme, api_key_name, normal_theme):
    if not room or not api_key_name:
        return "エラー：ルームとAPIキーを選択してください。"

    try:
        if timer_type == "通常タイマー":
            result_message = timer_tools.set_timer.func(
                duration_minutes=int(duration),
                theme=normal_theme or "時間になりました！",
                room_name=room
            )
            gr.Info(f"通常タイマーを設定しました。")
        elif timer_type == "ポモドーロタイマー":
            result_message = timer_tools.set_pomodoro_timer.func(
                work_minutes=int(work),
                break_minutes=int(brk),
                cycles=int(cycles),
                work_theme=work_theme or "作業終了の時間です。",
                break_theme=brk_theme or "休憩終了の時間です。",
                room_name=room
            )
            gr.Info(f"ポモドーロタイマーを設定しました。")
        else:
            result_message = "エラー: 不明なタイマー種別です。"
        return result_message

    except Exception as e:
        traceback.print_exc()
        return f"タイマー開始エラー: {e}"

def handle_auto_memory_change(auto_memory_enabled: bool):
    config_manager.save_memos_config("auto_memory_enabled", auto_memory_enabled)
    status = "有効" if auto_memory_enabled else "無効"
    gr.Info(f"対話の自動記憶を「{status}」に設定しました。")

def handle_memory_archiving(room_name: str, console_content: str, source: str):
    """
    【v1: 新規作成】
    記憶の生成（アーカイブまたは手動インポート）をサブプロセスとして堅牢に実行する。
    いかなる状況でも、UIがフリーズしないことを保証する。
    """
    # nexus_ark.pyで定義されている出力コンポーネントの数に合わせる
    # (memos_import_button, memory_archive_button, importer_stop_button, importer_process_state,
    #  debug_console_state, debug_console_output, chat_input_multimodal)
    NUM_OUTPUTS = 7

    # 処理中のUI更新を定義
    yield (
        gr.update(value="記憶を生成中...", interactive=False),
        gr.update(value="記憶を生成中...", interactive=False),
        gr.update(visible=True),
        None, # Process State
        console_content, # Console State
        console_content, # Console Output
        gr.update(interactive=False)  # Chat Input
    )

    full_log_output = console_content
    script_path = "memory_archivist.py"

    try:
        gr.Info(f"記憶の生成を開始します... (ソース: {source})")

        proc = subprocess.run(
            [sys.executable, "-X", "utf8", script_path, "--room_name", room_name, "--source", source],
            capture_output=True, text=True, encoding='utf-8', errors='ignore'
        )

        log_chunk = f"\n--- [{script_path} Output] ---\n{proc.stdout}\n{proc.stderr}"
        full_log_output += log_chunk
        yield (
            gr.update(), gr.update(), None,
            full_log_output, full_log_output, gr.update()
        )

        if proc.returncode != 0:
            raise RuntimeError(f"{script_path} failed with return code {proc.returncode}")

        gr.Info("✅ 記憶の生成が、正常に完了しました！")

    except Exception as e:
        error_message = f"記憶の生成中にエラーが発生しました: {e}"
        # loggingは未定義なので、printとtracebackを使用
        print(error_message)
        traceback.print_exc()
        gr.Error(error_message)

    finally:
        # --- 最終処理: UIを必ず元の状態に戻す ---
        yield (
            gr.update(value="手動インポートから記憶を生成", interactive=True),
            gr.update(value="自動アーカイブから記憶を生成", interactive=True),
            gr.update(visible=False), # Stop Button
            None, # Process State
            full_log_output, # Console State
            full_log_output, # Console Output
            gr.update(interactive=True) # Chat Input
        )


def handle_memos_batch_import(room_name: str, console_content: str):
    """
    【v3: 最終FIX版】
    知識グラフの構築を、2段階のサブプロセスとして、堅牢に実行する。
    いかなる状況でも、UIがフリーズしないことを保証する。
    """
    # UIコンポーネントの数をハードコードするのではなく、動的に取得するか、
    # 確実な数（今回は6）を返すようにする。
    NUM_OUTPUTS = 6

    # 処理中のUI更新を定義
    # ★★★ あなたの好みに合わせてテキストを修正 ★★★
    yield (
        gr.update(value="知識グラフ構築中...", interactive=False), # Button
        gr.update(visible=True), # Stop Button (今回は実装しないが将来のため)
        None, # Process State
        console_content, # Console State
        console_content, # Console Output
        gr.update(interactive=False)  # Chat Input
    )

    full_log_output = console_content
    script_path_1 = "batch_importer.py"
    script_path_2 = "soul_injector.py"

    try:
        # --- ステージ1: 骨格の作成 ---
        gr.Info("ステージ1/2: 知識グラフの骨格を作成しています...")

        proc1 = subprocess.run(
            [sys.executable, "-X", "utf8", script_path_1, room_name],
            capture_output=True, text=True, encoding='utf-8', errors='ignore'
        )

        log_chunk = f"\n--- [{script_path_1} Output] ---\n{proc1.stdout}\n{proc1.stderr}"
        full_log_output += log_chunk
        yield (
            gr.update(), gr.update(), None,
            full_log_output, full_log_output, gr.update()
        )

        if proc1.returncode != 0:
            raise RuntimeError(f"{script_path_1} failed with return code {proc1.returncode}")

        gr.Info("ステージ1/2: 骨格の作成に成功しました。")

        # --- ステージ2: 魂の注入 ---
        # ★★★ あなたの好みに合わせてテキストを修正 ★★★
        gr.Info("ステージ2/2: 知識グラフを構築中です...")

        proc2 = subprocess.run(
            [sys.executable, "-X", "utf8", script_path_2, room_name],
            capture_output=True, text=True, encoding='utf-8', errors='ignore'
        )

        log_chunk = f"\n--- [{script_path_2} Output] ---\n{proc2.stdout}\n{proc2.stderr}"
        full_log_output += log_chunk
        yield (
            gr.update(), gr.update(), None,
            full_log_output, full_log_output, gr.update()
        )

        if proc2.returncode != 0:
            raise RuntimeError(f"{script_path_2} failed with return code {proc2.returncode}")

        gr.Info("✅ 知識グラフの構築が、正常に完了しました！")

    except Exception as e:
        error_message = f"知識グラフの構築中にエラーが発生しました: {e}"
        logging.error(error_message)
        logging.error(traceback.format_exc())
        gr.Error(error_message)

    finally:
        # --- 最終処理: UIを必ず元の状態に戻す ---
        yield (
            gr.update(value="知識グラフを構築/更新する", interactive=True), # Button
            gr.update(visible=False), # Stop Button
            None, # Process State
            full_log_output, # Console State
            full_log_output, # Console Output
            gr.update(interactive=True) # Chat Input
        )


def handle_importer_stop(pid: int):
    """
    実行中のインポータープロセスを中断する。
    """
    if pid is None:
        gr.Warning("停止対象のプロセスが見つかりません。")
        return gr.update(interactive=True, value="知識グラフを構築/更新する"), gr.update(visible=False), None, gr.update(interactive=True)

    try:
        process = psutil.Process(pid)
        process.terminate()  # SIGTERMを送信
        gr.Info(f"インポート処理(PID: {pid})に停止信号を送信しました。")
    except psutil.NoSuchProcess:
        gr.Warning(f"プロセス(PID: {pid})は既に終了しています。")
    except Exception as e:
        gr.Error(f"プロセスの停止中にエラーが発生しました: {e}")
        traceback.print_exc()

    return (
        gr.update(interactive=True, value="知識グラフを構築/更新する"),
        gr.update(visible=False),
        None,
        gr.update(interactive=True)
    )

def _run_core_memory_update(room_name: str, api_key: str):
    print(f"--- [スレッド開始] コアメモリ更新処理を開始します (Room: {room_name}) ---")
    try:
        from tools import memory_tools
        result = memory_tools.summarize_and_save_core_memory.func(room_name=room_name, api_key=api_key)
        print(f"--- [スレッド終了] コアメモリ更新処理完了 --- 結果: {result}")
    except Exception: print(f"--- [スレッドエラー] コアメモリ更新中に予期せぬエラー ---"); traceback.print_exc()

def handle_core_memory_update_click(room_name: str, api_key_name: str):
    if not room_name or not api_key_name: gr.Warning("ルームとAPIキーを選択してください。"); return
    api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"): gr.Warning(f"APIキー '{api_key_name}' が有効ではありません。"); return
    gr.Info(f"「{room_name}」のコアメモリ更新をバックグラウンドで開始しました。")
    threading.Thread(target=_run_core_memory_update, args=(room_name, api_key)).start()

# --- Screenshot Redaction Rules Handlers ---

def handle_redaction_rule_select(rules_df: pd.DataFrame, evt: gr.SelectData) -> Tuple[Optional[int], str, str]:
    """DataFrameの行が選択されたときに、その内容を編集フォームに表示する。"""
    if not evt.index:
        # 選択が解除された場合
        return None, "", ""
    try:
        selected_index = evt.index[0]
        if rules_df is None or not (0 <= selected_index < len(rules_df)):
             return None, "", ""

        selected_row = rules_df.iloc[selected_index]
        find_text = selected_row.get("元の文字列 (Find)", "")
        replace_text = selected_row.get("置換後の文字列 (Replace)", "")
        # 選択された行のインデックスを返す
        return selected_index, str(find_text), str(replace_text)
    except (IndexError, KeyError) as e:
        print(f"ルール選択エラー: {e}")
        return None, "", ""

def handle_add_or_update_redaction_rule(
    current_rules: List[Dict],
    selected_index: Optional[int],
    find_text: str,
    replace_text: str
) -> Tuple[pd.DataFrame, List[Dict], None, str, str]:
    """ルールを追加または更新し、ファイルに保存してUIを更新する。"""
    find_text = find_text.strip()
    replace_text = replace_text.strip()

    if not find_text:
        gr.Warning("「元の文字列」は必須です。")
        df = _create_redaction_df_from_rules(current_rules)
        return df, current_rules, selected_index, find_text, replace_text

    if current_rules is None:
        current_rules = []

    # 更新モード
    if selected_index is not None and 0 <= selected_index < len(current_rules):
        # findの値が、自分以外のルールで既に使われていないかチェック
        for i, rule in enumerate(current_rules):
            if i != selected_index and rule["find"] == find_text:
                gr.Warning(f"ルール「{find_text}」は既に存在します。")
                df = _create_redaction_df_from_rules(current_rules)
                return df, current_rules, selected_index, find_text, replace_text
        current_rules[selected_index] = {"find": find_text, "replace": replace_text}
        gr.Info(f"ルール「{find_text}」を更新しました。")
    # 新規追加モード
    else:
        if any(rule["find"] == find_text for rule in current_rules):
            gr.Warning(f"ルール「{find_text}」は既に存在します。更新する場合はリストから選択してください。")
            df = _create_redaction_df_from_rules(current_rules)
            return df, current_rules, selected_index, find_text, replace_text
        current_rules.append({"find": find_text, "replace": replace_text})
        gr.Info(f"新しいルール「{find_text}」を追加しました。")

    config_manager.save_redaction_rules(current_rules)

    # ▼▼▼【ここが修正の核心】▼▼▼
    # 古い、間違ったDataFrame生成ロジックを、
    # 正しいヘルパー関数の呼び出しに置き換える。
    df_for_ui = _create_redaction_df_from_rules(current_rules)
    # ▲▲▲【修正ここまで】▲▲▲

    return df_for_ui, current_rules, None, "", ""

def handle_delete_redaction_rule(
    current_rules: List[Dict],
    selected_index: Optional[int]
) -> Tuple[pd.DataFrame, List[Dict], None, str, str]:
    """選択されたルールを削除する。"""
    if current_rules is None:
        current_rules = []

    if selected_index is None or not (0 <= selected_index < len(current_rules)):
        gr.Warning("削除するルールをリストから選択してください。")
        df = _create_redaction_df_from_rules(current_rules)
        return df, current_rules, selected_index, "", ""

    # ▼▼▼【ここからが修正の核心】▼▼▼
    # Pandasの.dropではなく、Pythonのdel文でリストの要素を直接削除する
    deleted_rule_name = current_rules[selected_index]["find"]
    del current_rules[selected_index]
    # ▲▲▲【修正ここまで】▲▲▲

    config_manager.save_redaction_rules(current_rules)
    gr.Info(f"ルール「{deleted_rule_name}」を削除しました。")

    df_for_ui = _create_redaction_df_from_rules(current_rules)

    # フォームと選択状態をリセット
    return df_for_ui, current_rules, None, "", ""


def _format_text_content_for_gradio(
    main_text_html: str,
    thoughts_html: str,
    speaker_name: str,
    current_ui_index: int,
    total_ui_rows: int
) -> str:
    """
    発言のテキスト部分を、GradioのChatbotで表示するための最終的なHTML文字列に変換する。
    思考ログ、ナビゲーションボタン（▲▼）、メニューアイコン（…）の表示ロジックも内包する。
    """
    current_anchor_id = f"msg-anchor-{current_ui_index}"
    final_html_parts = []

    final_html_parts.append(f"<span id='{current_anchor_id}'></span>")
    final_html_parts.append(f"<strong>{html.escape(speaker_name)}:</strong><br>")

    if thoughts_html:
        # 先に改行文字の置換処理を行い、結果を変数に格納します。
        formatted_thoughts_html = thoughts_html.replace('\n', '<br>')
        # その後、バックスラッシュを含まない変数をf-stringに渡します。
        final_html_parts.append(f"<div class='thoughts'>【Thoughts】<br>{formatted_thoughts_html}</div>")

    if main_text_html:
        final_html_parts.append(main_text_html.replace('\n', '<br>'))

    nav_buttons_list = []
    if current_ui_index > 0:
        nav_buttons_list.append(f"<a href='#msg-anchor-{current_ui_index - 1}' class='message-nav-link' title='前の発言へ' style='text-decoration: none; color: inherit;'>▲</a>")

    if current_ui_index < total_ui_rows - 1:
        nav_buttons_list.append(f"<a href='#msg-anchor-{current_ui_index + 1}' class='message-nav-link' title='次の発言へ' style='text-decoration: none; color: inherit;'>▼</a>")

    nav_buttons_html = "&nbsp;&nbsp;".join(nav_buttons_list)
    menu_icon_html = "<span title='メニュー表示' style='font-weight: bold; cursor: pointer;'>&#8942;</span>"

    final_buttons_list = []
    if nav_buttons_html:
        final_buttons_list.append(nav_buttons_html)
    final_buttons_list.append(menu_icon_html)

    buttons_str = "&nbsp;&nbsp;&nbsp;".join(final_buttons_list)
    button_container = f"<div style='text-align: right; margin-top: 8px; font-size: 1.2em; line-height: 1;'>{buttons_str}</div>"
    final_html_parts.append(button_container)

    return "".join(final_html_parts)

def update_model_state(model): config_manager.save_config("last_model", model); return model

def update_api_key_state(api_key_name):
    config_manager.save_config("last_api_key_name", api_key_name)
    gr.Info(f"APIキーを '{api_key_name}' に設定しました。")
    return api_key_name

def update_api_history_limit_state_and_reload_chat(limit_ui_val: str, room_name: Optional[str], add_timestamp: bool, screenshot_mode: bool = False, redaction_rules: List[Dict] = None):
    key = next((k for k, v in constants.API_HISTORY_LIMIT_OPTIONS.items() if v == limit_ui_val), "all")
    config_manager.save_config("last_api_history_limit_option", key)
    history, mapping_list = reload_chat_log(room_name, key, add_timestamp, screenshot_mode, redaction_rules)
    return key, history, mapping_list

def handle_play_audio_button_click(selected_message: Optional[Dict[str, str]], room_name: str, api_key_name: str):
    if not selected_message:
        gr.Warning("再生するメッセージが選択されていません。")
        yield gr.update(visible=False), gr.update(interactive=True), gr.update(interactive=True)
        return

    yield (
        gr.update(visible=False),
        gr.update(value="音声生成中... ▌", interactive=False),
        gr.update(interactive=False)
    )

    try:
        raw_text = utils.extract_raw_text_from_html(selected_message.get("content"))
        text_to_speak = utils.remove_thoughts_from_text(raw_text)
        if not text_to_speak:
            gr.Info("このメッセージには音声で再生できるテキストがありません。")
            return

        effective_settings = config_manager.get_effective_settings(room_name)
        voice_id, voice_style_prompt = effective_settings.get("voice_id", "iapetus"), effective_settings.get("voice_style_prompt", "")
        api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)
        if not api_key:
            gr.Warning(f"APIキー '{api_key_name}' が見つかりません。")
            return

        from audio_manager import generate_audio_from_text
        gr.Info(f"「{room_name}」の声で音声を生成しています...")
        audio_filepath = generate_audio_from_text(text_to_speak, api_key, voice_id, voice_style_prompt)

        if audio_filepath:
            gr.Info("再生します。")
            yield gr.update(value=audio_filepath, visible=True), gr.update(), gr.update()
        else:
            gr.Error("音声の生成に失敗しました。")

    finally:
        yield (
            gr.update(),
            gr.update(value="🔊 選択した発言を再生", interactive=True),
            gr.update(interactive=True)
        )

def handle_voice_preview(selected_voice_name: str, voice_style_prompt: str, text_to_speak: str, api_key_name: str):
    if not selected_voice_name or not text_to_speak or not api_key_name:
        gr.Warning("声、テキスト、APIキーがすべて選択されている必要があります。")
        yield gr.update(visible=False), gr.update(interactive=True), gr.update(interactive=True)
        return

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
        yield (
            gr.update(),
            gr.update(interactive=True),
            gr.update(value="試聴", interactive=True)
        )

def handle_generate_or_regenerate_scenery_image(room_name: str, api_key_name: str, style_choice: str) -> Optional[str]:
    if not room_name or not api_key_name:
        gr.Warning("ルームとAPIキーを選択してください。")
        return None

    api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)
    if not api_key:
        gr.Warning(f"APIキー '{api_key_name}' が見つかりません。")
        return None

    location_id = utils.get_current_location(room_name)
    existing_image_path = utils.find_scenery_image(room_name, location_id)

    if not location_id:
        gr.Warning("現在地が特定できません。")
        return existing_image_path

    final_prompt = ""
    gr.Info("シーンディレクターAIがプロンプトを構成しています...")
    try:
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

        world_settings_path = room_manager.get_world_settings_path(room_name)
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

        from agent.graph import get_configured_llm
        effective_settings = config_manager.get_effective_settings(room_name)
        scene_director_llm = get_configured_llm(constants.INTERNAL_PROCESSING_MODEL, api_key, effective_settings)

        director_prompt = f"""
You are a master scene director AI for a high-end image generation model.
Your sole purpose is to synthesize all available information into a single, cohesive, and flawless English prompt.

**Objective:**
Generate ONE final, masterful prompt for an image generation AI based on a strict hierarchy of information.

**--- [Primary Directive: The Hierarchy of Truth] ---**
1.  **Analyze the "Base Location Description" FIRST.** Look for any explicit or implicit descriptions of the **time of day, lighting, weather, or atmosphere** (e.g., "always night," "sunlight streaming through," "rainy," "gloomy").
2.  **If such descriptions exist, they are the ABSOLUTE TRUTH.** You MUST base the visual atmosphere of the prompt on these descriptions. In this case, you MUST IGNORE the "Current Scene Conditions" regarding time and season, as the location's inherent properties override reality.
3.  **If, and ONLY IF, the "Base Location Description" contains NO information about time or lighting,** you must then use the "Current Scene Conditions" to determine the time and season for the prompt.

**--- [Core Principles] ---**
-   **Foundation First:** The "Base Location Description" is the undeniable truth for all physical structures, objects, furniture, and materials. Your prompt MUST be a faithful visual representation of these elements.
-   **Strictly Visual:** The output must be a purely visual and descriptive paragraph in English. Exclude any narrative, metaphors, sounds, or non-visual elements.
-   **Mandatory Inclusions:** Your prompt MUST incorporate the specified "Aspect Ratio" and adhere to the "Style Definition".
-   **Absolute Prohibitions:** Strictly enforce all "Negative Prompts".
-   **Output Format:** Output ONLY the final, single-paragraph prompt. Do not include any of your own thoughts or conversational text.

---
**[Information Dossier]**

**1. Base Location Description (Absolute truth for atmosphere if specified, otherwise for objects):**
```
{space_text}
```

**2. Current Scene Conditions (Use ONLY if time/lighting is NOT specified in the description above):**
- Time of Day: {time_of_day}
- Season: {season}

**3. Style Definition (Incorporate this aesthetic):**
- {style_choice_text}

**4. Mandatory Technical Specs:**
- Aspect Ratio: 16:9 landscape aspect ratio.

**5. Negative Prompts (Strictly enforce these exclusions):**
- Absolutely no text, letters, characters, signatures, or watermarks. Do not include people.
---

**Final Master Prompt:**
"""
        final_prompt = scene_director_llm.invoke(director_prompt).content.strip()

    except Exception as e:
        gr.Error(f"シーンディレクターAIによるプロンプト生成中にエラーが発生しました: {e}")
        traceback.print_exc()
        return existing_image_path

    if not final_prompt:
        gr.Error("シーンディレクターAIが有効なプロンプトを生成できませんでした。")
        return existing_image_path

    gr.Info(f"「{style_choice}」で画像を生成します...")
    result = generate_image_tool_func.func(prompt=final_prompt, room_name=room_name, api_key=api_key)

    if "Generated Image:" in result:
        generated_path = result.replace("[Generated Image: ", "").replace("]", "").strip()
        if os.path.exists(generated_path):
            save_dir = os.path.join(constants.ROOMS_DIR, room_name, "spaces", "images")
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
    if not api_key_name:
        gr.Warning("テストするAPIキーが選択されていません。")
        return

    api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        gr.Error(f"APIキー '{api_key_name}' は無効です。config.jsonを確認してください。")
        return

    gr.Info(f"APIキー '{api_key_name}' を使って、必須モデルへの接続をテストしています...")
    import google.genai as genai

    required_models = {
        "models/gemini-2.5-pro": "メインエージェント (agent_node)",
        "models/gemini-2.5-flash": "高速処理 (context_generator)",
    }
    results = []
    all_ok = True

    try:
        client = genai.Client(api_key=api_key)
        for model_name, purpose in required_models.items():
            try:
                client.models.get(model=model_name)
                results.append(f"✅ **{purpose} ({model_name.split('/')[-1]})**: 利用可能です。")
            except Exception as model_e:
                results.append(f"❌ **{purpose} ({model_name.split('/')[-1]})**: 利用できません。")
                print(f"--- モデル '{model_name}' のチェックに失敗: {model_e} ---")
                all_ok = False

        result_message = "\n\n".join(results)
        if all_ok:
            gr.Info(f"✅ **全ての必須モデルが利用可能です！**\n\n{result_message}")
        else:
            gr.Warning(f"⚠️ **一部のモデルが利用できません。**\n\n{result_message}\n\nGoogle AI StudioまたはGoogle Cloudコンソールの設定を確認してください。")

    except Exception as e:
        error_message = f"❌ **APIサーバーへの接続自体に失敗しました。**\n\nAPIキーが無効か、ネットワークの問題が発生している可能性があります。\n\n詳細: {str(e)}"
        print(f"--- API接続テストエラー ---\n{traceback.format_exc()}")
        gr.Error(error_message)

from world_builder import get_world_data, save_world_data

def handle_world_builder_load(room_name: str):
    if not room_name:
        return {}, gr.update(choices=[], value=None), ""

    world_data = get_world_data(room_name)
    area_choices = sorted(world_data.keys())

    world_settings_path = room_manager.get_world_settings_path(room_name)
    raw_content = ""
    if world_settings_path and os.path.exists(world_settings_path):
        with open(world_settings_path, "r", encoding="utf-8") as f:
            raw_content = f.read()

    return world_data, gr.update(choices=area_choices, value=None), raw_content

def handle_room_change_for_all_tabs(room_name: str, api_key_name: str):
    print(f"--- UI司令塔(handle_room_change_for_all_tabs)実行: {room_name} ---")

    # 責務1: 設定をファイルに保存する
    config_manager.save_config("last_room", room_name)

    # 責務2: 新しいヘルパーを呼び出してUIを更新する
    return _update_all_tabs_for_room_change(room_name, api_key_name)

def handle_start_session(main_room: str, participant_list: list) -> tuple:
    if not participant_list:
        gr.Info("会話に参加するルームを1人以上選択してください。")
        return gr.update(), gr.update()

    all_participants = [main_room] + participant_list
    participants_text = "、".join(all_participants)
    status_text = f"現在、**{participants_text}** を招待して会話中です。"
    session_start_message = f"（システム通知：{participants_text} との複数人対話セッションが開始されました。）"

    for room_name in all_participants:
        log_f, _, _, _, _ = room_manager.get_room_files_paths(room_name)
        if log_f:
            utils.save_message_to_log(log_f, "## システム(セッション管理):", session_start_message)

    gr.Info(f"複数人対話セッションを開始しました。参加者: {participants_text}")
    return participant_list, status_text


def handle_end_session(main_room: str, active_participants: list) -> tuple:
    if not active_participants:
        gr.Info("現在、1対1の会話モードです。")
        return [], "現在、1対1の会話モードです。", gr.update(value=[])

    all_participants = [main_room] + active_participants
    session_end_message = "（システム通知：複数人対話セッションが終了しました。）"

    for room_name in all_participants:
        log_f, _, _, _, _ = room_manager.get_room_files_paths(room_name)
        if log_f:
            utils.save_message_to_log(log_f, "## システム(セッション管理):", session_end_message)

    gr.Info("複数人対話セッションを終了し、1対1の会話モードに戻りました。")
    return [], "現在、1対1の会話モードです。", gr.update(value=[])


def handle_wb_area_select(world_data: Dict, area_name: str):
    if not area_name or area_name not in world_data:
        return gr.update(choices=[], value=None)
    places = sorted(world_data[area_name].keys())
    return gr.update(choices=places, value=None)

def handle_wb_place_select(world_data: Dict, area_name: str, place_name: str):
    if not area_name or not place_name:
        return gr.update(value="", visible=False), gr.update(visible=False), gr.update(visible=False)
    content = world_data.get(area_name, {}).get(place_name, "")
    return (
        gr.update(value=content, visible=True),
        gr.update(visible=True),
        gr.update(visible=True)
    )

def handle_wb_save(room_name: str, world_data: Dict, area_name: str, place_name: str, content: str):
    if not room_name or not area_name or not place_name:
        gr.Warning("保存するにはエリアと場所を選択してください。")
        return world_data, gr.update()

    if area_name in world_data and place_name in world_data[area_name]:
        world_data[area_name][place_name] = content
        save_world_data(room_name, world_data)
        gr.Info("世界設定を保存しました。")
    else:
        gr.Error("保存対象のエリアまたは場所が見つかりません。")

    world_settings_path = room_manager.get_world_settings_path(room_name)
    raw_content = ""
    if world_settings_path and os.path.exists(world_settings_path):
        with open(world_settings_path, "r", encoding="utf-8") as f:
            raw_content = f.read()
    return world_data, raw_content

def handle_wb_delete_place(room_name: str, world_data: Dict, area_name: str, place_name: str):
    if not area_name or not place_name:
        gr.Warning("削除するエリアと場所を選択してください。")
        return world_data, gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update()
    if area_name not in world_data or place_name not in world_data[area_name]:
        gr.Warning(f"場所 '{place_name}' がエリア '{area_name}' に見つかりません。")
        return world_data, gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update()

    del world_data[area_name][place_name]
    save_world_data(room_name, world_data)
    gr.Info(f"場所 '{place_name}' を削除しました。")

    area_choices = sorted(world_data.keys())
    place_choices = sorted(world_data.get(area_name, {}).keys())
    world_settings_path = room_manager.get_world_settings_path(room_name)
    raw_content = ""
    if world_settings_path and os.path.exists(world_settings_path):
        with open(world_settings_path, "r", encoding="utf-8") as f:
            raw_content = f.read()
    return (
        world_data,
        gr.update(choices=area_choices, value=area_name),
        gr.update(choices=place_choices, value=None),
        gr.update(value="", visible=False),
        gr.update(visible=False),
        gr.update(visible=False),
        raw_content
    )

def handle_wb_confirm_add(room_name: str, world_data: Dict, selected_area: str, item_type: str, item_name: str):
    if not room_name or not item_name:
        gr.Warning("ルームが選択されていないか、名前が入力されていません。")
        return world_data, gr.update(), gr.update(), gr.update(visible=True), item_name, gr.update()

    item_name = item_name.strip()
    if not item_name:
        gr.Warning("名前が空です。")
        return world_data, gr.update(), gr.update(), gr.update(visible=True), item_name, gr.update()

    raw_content = ""
    if item_type == "area":
        if item_name in world_data:
            gr.Warning(f"エリア '{item_name}' は既に存在します。")
            return world_data, gr.update(), gr.update(), gr.update(visible=True), item_name, gr.update()
        world_data[item_name] = {}
        save_world_data(room_name, world_data)
        gr.Info(f"新しいエリア '{item_name}' を追加しました。")
        area_choices = sorted(world_data.keys())
        world_settings_path = room_manager.get_world_settings_path(room_name)
        if world_settings_path and os.path.exists(world_settings_path):
            with open(world_settings_path, "r", encoding="utf-8") as f: raw_content = f.read()
        return world_data, gr.update(choices=area_choices, value=item_name), gr.update(choices=[], value=None), gr.update(visible=False), "", raw_content

    elif item_type == "place":
        if not selected_area:
            gr.Warning("場所を追加するエリアを選択してください。")
            return world_data, gr.update(), gr.update(), gr.update(visible=True), item_name, gr.update()
        if item_name in world_data.get(selected_area, {}):
            gr.Warning(f"場所 '{item_name}' はエリア '{selected_area}' に既に存在します。")
            return world_data, gr.update(), gr.update(), gr.update(visible=True), item_name, gr.update()
        world_data[selected_area][item_name] = "新しい場所です。説明を記述してください。"
        save_world_data(room_name, world_data)
        gr.Info(f"エリア '{selected_area}' に新しい場所 '{item_name}' を追加しました。")
        place_choices = sorted(world_data[selected_area].keys())
        world_settings_path = room_manager.get_world_settings_path(room_name)
        if world_settings_path and os.path.exists(world_settings_path):
            with open(world_settings_path, "r", encoding="utf-8") as f: raw_content = f.read()
        return world_data, gr.update(), gr.update(choices=place_choices, value=item_name), gr.update(visible=False), "", raw_content
    else:
        gr.Error(f"不明なアイテムタイプです: {item_type}")
        return world_data, gr.update(), gr.update(), gr.update(visible=False), "", gr.update()

def handle_save_world_settings_raw(room_name: str, raw_content: str):
    if not room_name:
        gr.Warning("ルームが選択されていません。")
        return raw_content, gr.update()
    world_settings_path = room_manager.get_world_settings_path(room_name)
    if not world_settings_path:
        gr.Error("世界設定ファイルのパスが取得できませんでした。")
        return raw_content, gr.update()
    try:
        with open(world_settings_path, "w", encoding="utf-8") as f:
            f.write(raw_content)
        gr.Info("RAWテキストとして世界設定を保存しました。構造化エディタに反映されます。")
        new_world_data = get_world_data(room_name)
        new_area_choices = sorted(new_world_data.keys())
        return new_world_data, gr.update(choices=new_area_choices, value=None), gr.update(choices=[], value=None)
    except Exception as e:
        gr.Error(f"世界設定のRAW保存中にエラーが発生しました: {e}")
        return gr.update(), gr.update(), gr.update()

def handle_reload_world_settings_raw(room_name: str) -> str:
    if not room_name:
        gr.Warning("ルームが選択されていません。")
        return ""
    world_settings_path = room_manager.get_world_settings_path(room_name)
    raw_content = ""
    if world_settings_path and os.path.exists(world_settings_path):
        with open(world_settings_path, "r", encoding="utf-8") as f:
            raw_content = f.read()
    gr.Info("世界設定ファイルを再読み込みしました。")
    return raw_content

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

def handle_notification_service_change(service_choice: str):
    if service_choice in ["Discord", "Pushover"]:
        config_manager.save_config("notification_service", service_choice.lower())
        gr.Info(f"通知サービスを「{service_choice}」に設定しました。")
    return service_choice.lower()

def handle_save_discord_webhook(webhook_url: str):
    config_manager.save_config("notification_webhook_url", webhook_url)
    gr.Info("Discord Webhook URLを保存しました。")

def load_system_prompt_content(room_name: str) -> str:
    if not room_name: return ""
    _, system_prompt_path, _, _, _ = get_room_files_paths(room_name)
    if system_prompt_path and os.path.exists(system_prompt_path):
        with open(system_prompt_path, "r", encoding="utf-8") as f:
            return f.read()
    return ""

def handle_save_system_prompt(room_name: str, content: str) -> None:
    if not room_name:
        gr.Warning("ルームが選択されていません。")
        return
    _, system_prompt_path, _, _, _ = get_room_files_paths(room_name)
    if not system_prompt_path:
        gr.Error(f"「{room_name}」のプロンプトパス取得失敗。")
        return
    try:
        with open(system_prompt_path, "w", encoding="utf-8") as f:
            f.write(content)
        gr.Info(f"「{room_name}」の人格プロンプトを保存しました。")
    except Exception as e:
        gr.Error(f"人格プロンプトの保存エラー: {e}")

def handle_reload_system_prompt(room_name: str) -> str:
    if not room_name:
        gr.Warning("ルームが選択されていません。")
        return ""
    content = load_system_prompt_content(room_name)
    gr.Info(f"「{room_name}」の人格プロンプトを再読み込みしました。")
    return content

def handle_save_redaction_rules(rules_df: pd.DataFrame) -> Tuple[List[Dict[str, str]], pd.DataFrame]:
    """DataFrameの内容を検証し、jsonファイルに保存し、更新されたルールとDataFrameを返す。"""
    if rules_df is None:
        rules_df = pd.DataFrame(columns=["元の文字列 (Find)", "置換後の文字列 (Replace)"])

    # 列名が存在しない場合（空のDataFrameなど）に対応
    if '元の文字列 (Find)' not in rules_df.columns or '置換後の文字列 (Replace)' not in rules_df.columns:
        rules_df = pd.DataFrame(columns=["元の文字列 (Find)", "置換後の文字列 (Replace)"])

    rules = [
        {"find": str(row["元の文字列 (Find)"]), "replace": str(row["置換後の文字列 (Replace)"])}
        for index, row in rules_df.iterrows()
        if pd.notna(row["元の文字列 (Find)"]) and str(row["元の文字列 (Find)"]).strip()
    ]
    config_manager.save_redaction_rules(rules)
    gr.Info(f"{len(rules)}件の置換ルールを保存しました。チャット履歴を更新してください。")

    # 更新された（空行が除去された）DataFrameをUIに返す
    # まずPython辞書のリストから新しいDataFrameを作成
    updated_df_data = [{"元の文字列 (Find)": r["find"], "置換後の文字列 (Replace)": r["replace"]} for r in rules]
    updated_df = pd.DataFrame(updated_df_data)

    return rules, updated_df

def handle_delete_redaction_rule(rules_df: pd.DataFrame, selected_index: Optional[int]) -> Tuple[pd.DataFrame, list, None]:
    """DataFrameで選択されたルールを削除する。"""
    if selected_index is None:
        gr.Warning("削除するルールを選択してください。")
        # DataFrameがNoneの場合でもエラーにならないように初期化
        if rules_df is None:
            rules_df = pd.DataFrame(columns=["元の文字列 (Find)", "置換後の文字列 (Replace)"])
        return rules_df, config_manager.load_redaction_rules(), None

    # DataFrameがNoneの場合やインデックスが範囲外の場合の安全策
    if rules_df is None or not (0 <= selected_index < len(rules_df)):
        gr.Warning("選択された行を特定できませんでした。")
        if rules_df is None:
            rules_df = pd.DataFrame(columns=["元の文字列 (Find)", "置換後の文字列 (Replace)"])
        return rules_df, config_manager.load_redaction_rules(), None

    updated_df = rules_df.drop(index=selected_index).reset_index(drop=True)

    rules = [
        {"find": str(row["元の文字列 (Find)"]), "replace": str(row["置換後の文字列 (Replace)"])}
        for index, row in updated_df.iterrows()
        if pd.notna(row["元の文字列 (Find)"]) and str(row["元の文字列 (Find)"]).strip()
    ]
    config_manager.save_redaction_rules(rules)
    gr.Info("選択したルールを削除しました。チャット履歴を更新してください。")
    # 選択状態をリセットするためにNoneを返す
    return updated_df, rules, None


def handle_core_memory_update_click(room_name: str, api_key_name: str):
    if not room_name or not api_key_name: gr.Warning("ルームとAPIキーを選択してください。"); return
    api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"): gr.Warning(f"APIキー '{api_key_name}' が有効ではありません。"); return
    gr.Info(f"「{room_name}」のコアメモリ更新をバックグラウンドで開始しました。")
    threading.Thread(target=_run_core_memory_update, args=(room_name, api_key)).start()

def handle_visualize_graph(room_name: str):
    """
    【新規作成】
    現在の知識グラフを可視化し、その結果をUIに表示する。
    """
    if not room_name:
        gr.Warning("可視化するルームが選択されていません。")
        return gr.update(visible=False)

    script_path = "visualize_graph.py"

    gr.Info(f"ルーム「{room_name}」の知識グラフを可視化しています...")

    try:
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", script_path, room_name],
            capture_output=True, text=True, check=True, encoding='utf-8', errors='ignore'
        )

        # スクリプトの標準出力を解析して、画像のパスを取得
        output = proc.stdout.strip()
        image_path = None
        # 出力の最後の行にパスが含まれていると仮定
        for line in reversed(output.splitlines()):
            if line.strip().endswith(".png"):
                image_path = line.strip()
                break

        if image_path and os.path.exists(image_path):
            gr.Info("知識グラフの可視化に成功しました。")
            return gr.update(value=image_path, visible=True)
        else:
            # スクリプトは成功したが、パスの取得に失敗した場合
            gr.Error("可視化画像のパス取得に失敗しました。詳細はコンソールログを確認してください。")
            print(f"--- [可視化エラー] ---")
            print(f"visualize_graph.pyからの出力:\n{output}")
            return gr.update(visible=False)

    except subprocess.CalledProcessError as e:
        # スクリプト自体がエラーで終了した場合
        error_message = "知識グラフの可視化スクリプト実行中にエラーが発生しました。"
        gr.Error(error_message)
        print(f"--- [可視化エラー] ---")
        print(f"Stderr:\n{e.stderr}")
        return gr.update(visible=False)
    except Exception as e:
        gr.Error(f"可視化処理中に予期せぬエラーが発生しました: {e}")
        return gr.update(visible=False)


def handle_stop_button_click():
    """ストップボタンが押されたときにUIの状態をリセットする。"""
    print("--- [UI] ユーザーによりストップボタンが押されました ---")
    return gr.update(visible=False), gr.update(interactive=True)
