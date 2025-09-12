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
    use_common_prompt: bool, send_core_memory: bool, send_scenery: bool
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
     api_history_limit, debug_mode,
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

def format_history_for_gradio(messages: List[Dict[str, str]], current_room_folder: str, add_timestamp: bool, screenshot_mode: bool = False, redaction_rules: List[Dict] = None) -> Tuple[List[Tuple], List[int]]:
    """
    生ログの辞書リストを、GradioのChatbotコンポーネントが要求する形式に変換する。
    UI上の行と元のログの行を紐付けるマッピングリストも同時に生成する。
    v5: タイムスタンプの動的表示制御を追加。
    """
    if not messages:
        return [], []

    # --- タイムスタンプの表示制御 ---
    # add_timestampがFalseの場合、表示前にメッセージからタイムスタンプを除去する
    if not add_timestamp:
        timestamp_pattern = re.compile(r'\n\n\d{4}-\d{2}-\d{2} \(...\) \d{2}:\d{2}:\d{2}$')
        for msg in messages:
            if msg.get("content"):
                msg["content"] = timestamp_pattern.sub('', msg["content"])

    # --- 置換ルールの準備 ---
    active_rules = []
    if screenshot_mode and redaction_rules:
        active_rules = sorted(redaction_rules, key=lambda x: len(x["find"]), reverse=True)

    def apply_redactions_to_speaker(speaker_name: str) -> str:
        """話者名専用の置換関数。HTMLタグを含めず、テキストのみを返す。"""
        if not screenshot_mode or not active_rules or not speaker_name:
            return speaker_name

        # 話者名は単純なテキスト置換を行う
        temp_speaker_name = speaker_name
        for rule in active_rules:
            # 大文字小文字を区別せずに置換する
            if rule["find"].lower() in temp_speaker_name.lower():
                 # 置換する際、元の単語の大文字小文字の状態をできるだけ維持しようと試みる
                 # （この実装は単純なもので、より複雑なケースには対応しきれない可能性がある）
                 # 例： 'Miho' -> 'Keno', 'miho' -> 'keno'
                try:
                    # 正規表現で大文字小文字を無視して置換
                    temp_speaker_name = re.sub(rule["find"], rule["replace"], temp_speaker_name, flags=re.IGNORECASE)
                except re.error:
                    # 正規表現エラーを避けるためのフォールバック
                    temp_speaker_name = temp_speaker_name.replace(rule["find"], rule["replace"])

        return temp_speaker_name

    def apply_redactions_to_content(text: str) -> str:
        """本文専用の置換関数。HTMLタグでハイライトする。"""
        if not screenshot_mode or not active_rules or not text:
            return html.escape(text) if text else ""

        escaped_text = html.escape(text)
        for rule in active_rules:
            find_str = html.escape(rule["find"])
            # 正規表現のエスケープを行い、安全に置換する
            safe_find_str = re.escape(find_str)
            # 置換後の文字列はHTMLなのでエスケープしない
            replace_str = f'<span style="background-color: #FFFFB3; padding: 1px 3px; border-radius: 3px; color: #333;">{html.escape(rule["replace"])}</span>'
            try:
                # 大文字小文字を無視して置換
                escaped_text = re.sub(safe_find_str, replace_str, escaped_text, flags=re.IGNORECASE)
            except re.error:
                 # 正規表現エラーを避けるためのフォールバック
                escaped_text = escaped_text.replace(find_str, replace_str)

        return escaped_text

    # --- 話者名解決の準備 ---
    current_room_config = room_manager.get_room_config(current_room_folder) or {}
    user_display_name = current_room_config.get("user_display_name", "ユーザー")
    all_rooms_list = room_manager.get_room_list_for_ui()
    folder_to_display_map = {folder: display for display, folder in all_rooms_list}
    known_configs = {}

    # --- Stage 1: 生ログをUI表示要素のリストに分解 ---
    proto_history = []
    user_file_attach_pattern = re.compile(r"\[ファイル添付: ([^\]]+?)\]")
    gen_image_pattern = re.compile(r"\[Generated Image: ([^\]]+?)\]")

    for i, msg in enumerate(messages):
        role = msg.get("role")
        content = msg.get("content", "").strip()
        responder_id = msg.get("responder")
        if not responder_id: continue

        initial_speaker_name = ""
        if role == "USER":
            initial_speaker_name = user_display_name
        elif role == "AGENT":
            if responder_id == current_room_folder:
                initial_speaker_name = current_room_config.get("agent_display_name") or current_room_config.get("room_name", responder_id)
            else:
                if responder_id not in known_configs:
                    known_configs[responder_id] = room_manager.get_room_config(responder_id) if responder_id in folder_to_display_map else {}
                config = known_configs[responder_id]
                initial_speaker_name = config.get("agent_display_name") or config.get("room_name", responder_id) if config else f"{responder_id} [削除済]"
        else:
            initial_speaker_name = responder_id

        final_speaker_name = apply_redactions_to_speaker(initial_speaker_name)

        text_part, media_paths = content, []
        if role == "USER":
            text_part = user_file_attach_pattern.sub("", content).strip()
            media_paths = [p.strip() for p in user_file_attach_pattern.findall(content)]
        elif role == "AGENT":
            text_part = gen_image_pattern.sub("", content).strip()
            media_paths = [p.strip() for p in gen_image_pattern.findall(content)]

        if text_part:
            thoughts_pattern = re.compile(r"【Thoughts】(.*?)【/Thoughts】", re.DOTALL | re.IGNORECASE)
            thought_match = thoughts_pattern.search(text_part)
            thoughts_content = thought_match.group(1).strip() if thought_match else ""
            main_text_content = thoughts_pattern.sub("", text_part).strip()
            proto_history.append({"type": "text", "role": role, "speaker": final_speaker_name, "main_text": main_text_content, "thoughts": thoughts_content, "log_index": i})

        for path in media_paths:
            if os.path.exists(path):
                proto_history.append({"type": "media", "role": role, "speaker": final_speaker_name, "path": path, "log_index": i})

        if not text_part and not media_paths:
            proto_history.append({"type": "text", "role": role, "speaker": final_speaker_name, "main_text": "", "thoughts": "", "log_index": i})

    # --- Stage 2: UI表示要素リストから最終的なGradio形式を生成 ---
    gradio_history, mapping_list = [], []
    total_ui_rows = len(proto_history)

    for ui_index, item in enumerate(proto_history):
        mapping_list.append(item["log_index"])

        if item["type"] == "text":
            formatted_text = _format_text_content_for_gradio(
                apply_redactions_to_content(item["main_text"]),
                apply_redactions_to_content(item["thoughts"]),
                item["speaker"], # こちらは既に置換済みの話者名
                ui_index,
                total_ui_rows
            )
            gradio_history.append((formatted_text, None) if item["role"] == "USER" else (None, formatted_text))

        elif item["type"] == "media":
            media_tuple = (item["path"], os.path.basename(item["path"]))
            gradio_history.append((media_tuple, None) if item["role"] == "USER" else (None, media_tuple))

    return gradio_history, mapping_list

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
    history, mapping_list = format_history_for_gradio(
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

def handle_memory_archiving(room_name: str, console_content: str, source_type: str):
    # 1. UIを処理中モードに更新
    yield (
        gr.update(value="記憶を構築中...", interactive=False),
        gr.update(visible=True), # 中断ボタンを表示
        None, # PIDをリセット
        console_content,
        console_content,
        gr.update(interactive=False),
        gr.update(interactive=False)
    )

    full_log_output = console_content
    script_path = "memory_archivist.py"
    pid = None

    try:
        gr.Info(f"記憶の構築を開始します... (ソース: {source_type})")
        cmd = [sys.executable, "-u", script_path, "--room_name", room_name, "--source", source_type]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='ignore')
        pid = proc.pid

        # 2. PIDをUIのStateに即座に反映
        yield (
            gr.update(), gr.update(), pid,
            full_log_output, full_log_output,
            gr.update(), gr.update()
        )

        # 3. サブプロセスの出力をリアルタイムでUIに反映
        while True:
            line = proc.stdout.readline()
            if not line: break
            line = line.strip()
            print(line)
            full_log_output += line + "\n"
            yield (
                gr.update(), gr.update(), pid,
                full_log_output, full_log_output,
                gr.update(), gr.update()
            )

        proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(f"{script_path} failed with return code {proc.returncode}")

        gr.Info("✅ 記憶の構築が、正常に完了しました！")

    except Exception as e:
        error_message = f"記憶の構築中にエラーが発生しました: {e}"
        print(error_message); traceback.print_exc(); gr.Error(error_message)
    finally:
        # 4. 最終的にUIを元の状態に戻す
        yield (
            gr.update(value="過去ログから記憶を構築", interactive=True),
            gr.update(visible=False), # 中断ボタンを非表示
            None, # PIDをクリア
            full_log_output, full_log_output,
            gr.update(interactive=True), gr.update(interactive=True)
        )


def handle_add_current_log_to_memory(room_name: str):
    """
    「現在の対話を記憶に追加」ボタンのイベントハンドラ。
    バックグラウンドでmemory_archivistを呼び出す。
    """
    if not room_name:
        gr.Warning("ルームが選択されていません。")
        return

    gr.Info(f"「{room_name}」の現在の対話を、記憶構築キューに追加します...")

    def run_in_background():
        script_path = "memory_archivist.py"
        try:
            cmd = [sys.executable, "-u", script_path, "--room_name", room_name, "--source", "active_log"]
            # ここではUIの更新は行わないため、完了を待つだけで良い
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')

            if result.returncode == 0:
                print(f"--- [バックグラウンド処理完了] 現在の対話の記憶化に成功 ---")
            else:
                print(f"--- [バックグラウンド処理エラー] ---")
                print(result.stdout)
                print(result.stderr)

        except Exception as e:
            print(f"--- [バックグラウンド処理エラー] 記憶化の実行中に予期せぬエラー ---")
            traceback.print_exc()

    # UIをブロックしないように、別スレッドでサブプロセスを実行
    threading.Thread(target=run_in_background).start()


def handle_archivist_stop(pid: int):
    """
    実行中の記憶アーキビストプロセスを中断する。
    """
    if pid is None:
        gr.Warning("停止対象のプロセスが見つかりません。")
    else:
        try:
            if psutil.pid_exists(pid):
                process = psutil.Process(pid)
                process.terminate()  # SIGTERMを送信
                gr.Info(f"記憶構築プロセス(PID: {pid})に停止信号を送信しました。")
            else:
                gr.Warning(f"プロセス(PID: {pid})は既に終了しています。")
        except Exception as e:
            gr.Error(f"プロセスの停止中にエラーが発生しました: {e}")
            traceback.print_exc()

    # UIを必ず元の状態に戻す
    return (
        gr.update(interactive=True, value="過去ログから記憶を構築"),
        gr.update(visible=False),
        None, # PIDをクリア
        gr.update(interactive=True)
    )
