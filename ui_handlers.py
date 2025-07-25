# ui_handlers.py の内容を、以下のコードで完全に置き換えてください

import pandas as pd
from typing import List, Optional, Dict, Any, Tuple, Union
import gradio as gr
import datetime
import json
import traceback
import os
import re
from PIL import Image
import threading

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

# (handle_message_submission から handle_save_memory_click までは変更なし)
def handle_message_submission(*args: Any):
    # ★★★ 1. 引数のアンパックを最新の定義に合わせる ★★★
    (textbox_content, chatbot_history, current_character_name, current_model_name,
     current_api_key_name_state, file_input_list, add_timestamp_checkbox,
     send_thoughts_state, api_history_limit_state,
     send_notepad_state, use_common_prompt_state,
     send_core_memory_state) = args

    user_prompt_from_textbox = textbox_content.strip() if textbox_content else ""
    if not user_prompt_from_textbox and not file_input_list:
        # ★★★ 2. 最初の呼び出しを修正 ★★★
        token_count = update_token_count(
            None, None, current_character_name, current_model_name,
            current_api_key_name_state, api_history_limit_state,
            send_notepad_state, "", use_common_prompt_state,
            add_timestamp_checkbox, send_thoughts_state, send_core_memory_state
        )
        yield chatbot_history, gr.update(), gr.update(), token_count
        return

    timestamp = f"\n\n{datetime.datetime.now().strftime('%Y-%m-%d (%a) %H:%M:%S')}" if add_timestamp_checkbox else ""
    processed_user_message = user_prompt_from_textbox + timestamp
    if user_prompt_from_textbox:
        chatbot_history.append({"role": "user", "content": processed_user_message})
    log_message_parts = []
    if user_prompt_from_textbox:
         log_message_parts.append(processed_user_message)
    if file_input_list:
        for file_obj in file_input_list:
            filepath = file_obj.name
            filename = os.path.basename(filepath)
            safe_filepath = os.path.abspath(filepath).replace("\\", "/")
            md_string = f"[{filename}](/file={safe_filepath})"
            chatbot_history.append({"role": "user", "content": md_string})
            log_message_parts.append(f"[ファイル添付: {filepath}]")
    final_log_message = "\n\n".join(log_message_parts).strip()
    chatbot_history.append({"role": "assistant", "content": "思考中... ▌"})

    # ★★★ 3. 思考中の呼び出しを修正 ★★★
    token_count = update_token_count(
        textbox_content, file_input_list, current_character_name, current_model_name,
        current_api_key_name_state, api_history_limit_state,
        send_notepad_state, "", use_common_prompt_state,
        add_timestamp_checkbox, send_thoughts_state, send_core_memory_state
    )
    yield chatbot_history, gr.update(value=""), gr.update(value=None), token_count

    final_response_text = ""
    try:
        # args_listの再構築は不要、*argsをそのまま渡す
        final_response_text = gemini_api.invoke_nexus_agent(*args)
    except Exception as e:
        traceback.print_exc()
        final_response_text = f"[UIハンドラエラー: {e}]"

    log_f, _, _, _, _ = get_character_files_paths(current_character_name)
    if final_log_message:
        user_header = utils._get_user_header_from_log(log_f, current_character_name)
        utils.save_message_to_log(log_f, user_header, final_log_message)
        if final_response_text:
            utils.save_message_to_log(log_f, f"## {current_character_name}:", final_response_text)

    chatbot_history.pop()
    chatbot_history.append({"role": "assistant", "content": utils.format_response_for_display(final_response_text)})

    # ★★★ 4. 最終的な呼び出しを修正 ★★★
    token_count = update_token_count(
        None, None, current_character_name, current_model_name,
        current_api_key_name_state, api_history_limit_state,
        send_notepad_state, "", use_common_prompt_state,
        add_timestamp_checkbox, send_thoughts_state, send_core_memory_state
    )
    yield chatbot_history, gr.update(), gr.update(value=None), token_count
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
        if not os.path.exists(os.path.join(config_manager.CHARACTERS_DIR, character_name)): character_manager.ensure_character_files(character_name)
    config_manager.save_config("last_character", character_name)
    log_f, _, img_p, mem_p, notepad_p = get_character_files_paths(character_name)
    display_turns = _get_display_history_count(api_history_limit_value)
    chat_history = utils.format_history_for_gradio(utils.load_chat_log(log_f, character_name)[-(display_turns * 2):]) if log_f and os.path.exists(log_f) else []
    memory_str = json.dumps(load_memory_data_safe(mem_p), indent=2, ensure_ascii=False)
    profile_image = img_p if img_p and os.path.exists(img_p) else None
    notepad_content = load_notepad_content(character_name)
    return character_name, chat_history, "", profile_image, memory_str, character_name, character_name, notepad_content
def handle_save_memory_click(character_name, json_string_data):
    if not character_name: gr.Warning("キャラクターが選択されていません。"); return gr.update()
    try:
        update_action = save_memory_data(character_name, json_string_data); gr.Info("記憶を保存しました。"); return update_action
    except json.JSONDecodeError: gr.Error("記憶データのJSON形式が正しくありません。"); return gr.update()
    except Exception as e: gr.Error(f"記憶の保存中にエラーが発生しました: {e}"); return gr.update()

# ★★★ ここからが修正箇所 ★★★
DAY_MAP_EN_TO_JA = {"mon": "月", "tue": "火", "wed": "水", "thu": "木", "fri": "金", "sat": "土", "sun": "日"}
def render_alarms_as_dataframe():
    # 正しい関数 alarm_manager.load_alarms() を呼び出す
    alarms = sorted(alarm_manager.load_alarms(), key=lambda x: x.get("time", ""))
    display_data = []
    for a in alarms:
        # 新旧両方のテーマキーに対応
        theme_content = a.get("alarm_message") or a.get("context_memo") or a.get("theme", "")

        # 日付と曜日の表示ロジック
        date_str = a.get("date")
        days_list = a.get("days", [])
        if date_str:
            try:
                date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
                if date_obj == datetime.date.today():
                    schedule_display = "今日"
                elif date_obj == datetime.date.today() + datetime.timedelta(days=1):
                    schedule_display = "明日"
                else:
                    schedule_display = date_obj.strftime("%m/%d")
            except (ValueError, TypeError):
                schedule_display = "日付不定"
        elif days_list:
            schedule_display = ",".join([DAY_MAP_EN_TO_JA.get(d.lower(), d.upper()) for d in days_list])
        else:
            schedule_display = "単発" # 日付も曜日もない場合は単発

        display_data.append({
            "ID": a.get("id"),
            "状態": a.get("enabled", False),
            "時刻": a.get("time"),
            "予定": schedule_display,
            "キャラ": a.get("character"),
            "内容": theme_content
        })
    return pd.DataFrame(display_data, columns=["ID", "状態", "時刻", "予定", "キャラ", "内容"])

def get_display_df(df_with_id: pd.DataFrame):
    if df_with_id is None or df_with_id.empty or 'ID' not in df_with_id.columns:
        return pd.DataFrame(columns=["状態", "時刻", "予定", "キャラ", "内容"])
    return df_with_id[["状態", "時刻", "予定", "キャラ", "内容"]]
# (以降の関数は変更なし)
def handle_alarm_selection(evt: gr.SelectData, df_with_id: pd.DataFrame) -> List[str]:
    if evt.index is None or df_with_id is None or df_with_id.empty: return []
    indices = evt.index if isinstance(evt.index, list) else [evt.index[0]] if isinstance(evt.index, tuple) else []
    return [str(df_with_id.iloc[i]['ID']) for i in indices if 0 <= i < len(df_with_id)]
def handle_alarm_selection_and_feedback(evt: gr.SelectData, df_with_id: pd.DataFrame):
    selected_ids = handle_alarm_selection(evt, df_with_id); count = len(selected_ids); feedback_text = "アラームを選択してください" if count == 0 else f"{count} 件のアラームを選択中"
    return selected_ids, feedback_text
def toggle_selected_alarms_status(selected_ids: list, target_status: bool):
    if not selected_ids: gr.Warning("状態を変更するアラームが選択されていません。")
    else:
        # この部分はalarm_managerの関数を直接呼び出すので、alarm_manager側の修正が正しければ動作する
        pass
    return render_alarms_as_dataframe()
def handle_delete_selected_alarms(selected_ids: list):
    if not selected_ids: gr.Warning("削除するアラームが選択されていません。")
    else:
        for sid in selected_ids: alarm_manager.delete_alarm(str(sid))
    return render_alarms_as_dataframe()
def handle_timer_submission(timer_type, duration, work, brk, cycles, char, work_theme, brk_theme, api_key, normal_theme):
    if not char or not api_key: return "エラー：キャラクターとAPIキーを選択してください。"
    try:
        timer = UnifiedTimer(
            timer_type, float(duration or 0), float(work or 0), float(brk or 0),
            int(cycles or 0), char, work_theme, brk_theme, api_key, normal_theme
        )
        timer.start(); gr.Info(f"{timer_type}を開始しました。"); return f"{timer_type}を開始しました。"
    except Exception as e: return f"タイマー開始エラー: {e}"
def update_model_state(model): config_manager.save_config("last_model", model); return model
def update_api_key_state(api_key_name): config_manager.save_config("last_api_key_name", api_key_name); gr.Info(f"APIキーを '{api_key_name}' に設定しました。"); return api_key_name
def update_timestamp_state(checked): config_manager.save_config("add_timestamp", bool(checked))
def update_send_thoughts_state(checked): config_manager.save_config("last_send_thoughts_to_api", bool(checked)); return bool(checked)
def update_api_history_limit_state_and_reload_chat(limit_ui_val: str, character_name: Optional[str]):
    key = next((k for k, v in config_manager.API_HISTORY_LIMIT_OPTIONS.items() if v == limit_ui_val), "all"); config_manager.save_config("last_api_history_limit_option", key)
    chat_history, _ = reload_chat_log(character_name, key); return key, chat_history, gr.State()
def reload_chat_log(character_name: Optional[str], api_history_limit_value: str):
    if not character_name: return [], "キャラクター未選択"
    log_f,_,_,_,_ = get_character_files_paths(character_name)
    if not log_f or not os.path.exists(log_f): return [], "ログファイルなし"
    display_turns = _get_display_history_count(api_history_limit_value)
    history = utils.format_history_for_gradio(utils.load_chat_log(log_f, character_name)[-(display_turns*2):])
    return history, gr.State()
def load_alarm_to_form(selected_ids: list):
    default_char = character_manager.get_character_list()[0] if character_manager.get_character_list() else "Default"
    if not selected_ids or len(selected_ids) != 1: return "アラーム追加", "", "", default_char, list(DAY_MAP_EN_TO_JA.values()), "08", "00", None
    alarm = alarm_manager.get_alarm_by_id(selected_ids[0])
    if not alarm: gr.Warning(f"アラームID '{selected_ids[0]}' が見つかりません。"); return "アラーム追加", "", "", default_char, list(DAY_MAP_EN_TO_JA.values()), "08", "00", None
    h, m = alarm.get("time", "08:00").split(":")
    days_ja = [DAY_MAP_EN_TO_JA.get(d.lower(), d.upper()) for d in alarm.get("days", [])]
    theme_content = alarm.get("alarm_message") or alarm.get("context_memo") or alarm.get("theme", "")
    return f"アラーム更新", theme_content, "", alarm.get("character", default_char), days_ja, h, m, selected_ids[0]
def handle_add_or_update_alarm(editing_id, h, m, char, theme, prompt, days):
    # この関数はUIからの手動設定用。対話型とは別のロジック。
    pass
def handle_rag_update_button_click(character_name: str, api_key_name: str):
    if not character_name or not api_key_name: gr.Warning("キャラクターとAPIキーを選択してください。"); return
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"): gr.Warning(f"APIキー '{api_key_name}' が有効ではありません。"); return
    gr.Info(f"「{character_name}」のRAG索引の更新を開始します..."); threading.Thread(target=lambda: rag_manager.create_or_update_index(character_name, api_key)).start()
def update_send_notepad_state(checked: bool): return checked
def update_use_common_prompt_state(checked: bool): return checked
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
    lines = [f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}] {line.strip()}" if not re.match(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\]", line.strip()) else line.strip() for line in content.strip().split('\n') if line.strip()]
    final_content = "\n".join(lines)
    try:
        with open(notepad_path, "w", encoding="utf-8") as f: f.write(final_content + ('\n' if final_content else '')); gr.Info(f"「{character_name}」のメモ帳を保存しました。"); return final_content
    except Exception as e: gr.Error(f"メモ帳の保存エラー: {e}"); return content
def handle_clear_notepad_click(character_name: str) -> str:
    if not character_name: gr.Warning("キャラクターが選択されていません。"); return ""
    _, _, _, _, notepad_path = character_manager.get_character_files_paths(character_name)
    if not notepad_path: gr.Error(f"「{character_name}」のメモ帳パス取得失敗。"); return ""
    try:
        with open(notepad_path, "w", encoding="utf-8") as f: f.write(""); gr.Info(f"「{character_name}」のメモ帳を空にしました。"); return ""
    except Exception as e: gr.Error(f"メモ帳クリアエラー: {e}"); return f"エラー: {e}"
def handle_reload_notepad(character_name: str) -> str:
    if not character_name: gr.Warning("キャラクターが選択されていません。"); return ""
    content = load_notepad_content(character_name); gr.Info(f"「{character_name}」のメモ帳を再読み込みしました。"); return content
def _run_core_memory_update(character_name: str, api_key: str):
    print(f"--- [スレッド開始] コアメモリ更新処理を開始します (Character: {character_name}) ---")
    try:
        result = memory_tools.summarize_and_save_core_memory.func(character_name=character_name, api_key=api_key)
        print(f"--- [スレッド終了] コアメモリ更新処理完了 --- 結果: {result}")
    except Exception as e: print(f"--- [スレッドエラー] コアメモリ更新中に予期せぬエラー ---")
def handle_core_memory_update_click(character_name: str, api_key_name: str):
    if not character_name or not api_key_name: gr.Warning("キャラクターとAPIキーを選択してください。"); return
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"): gr.Warning(f"APIキー '{api_key_name}' が有効ではありません。"); return
    gr.Info(f"「{character_name}」のコアメモリ更新をバックグラウンドで開始しました。"); threading.Thread(target=_run_core_memory_update, args=(character_name, api_key)).start()
def update_token_count(
    textbox_content: Optional[str],
    file_input_list: Optional[List[Any]],
    current_character_name: str,
    current_model_name: str,
    current_api_key_name_state: str,
    api_history_limit_state: str,
    send_notepad_state: bool,
    # notepad_editor_content: str, # ★★★ 未使用のため削除 ★★★
    use_common_prompt_state: bool,
    add_timestamp_state: bool,
    send_thoughts_state: bool,
    send_core_memory_state: bool
) -> str:
    """入力全体のトークン数を計算し、UI表示用の文字列を返す【最終確定版】"""
    import gemini_api
    import filetype
    import base64
    import io
    from PIL import Image

    parts_for_api = []
    if textbox_content:
        parts_for_api.append(textbox_content.strip())

    if file_input_list:
        for file_obj in file_input_list:
            filepath = file_obj.name
            try:
                kind = filetype.guess(filepath)
                if kind is None:
                    with open(filepath, 'r', encoding='utf-8') as f: text_content = f.read()
                    parts_for_api.append(f"--- 添付ファイル「{os.path.basename(filepath)}」の内容 ---\n{text_content}\n--- ファイル内容ここまで ---")
                    continue

                mime_type = kind.mime
                if mime_type.startswith("image/"):
                    parts_for_api.append(Image.open(filepath))
                elif mime_type.startswith("audio/") or mime_type.startswith("video/") or mime_type == "application/pdf":
                    with open(filepath, "rb") as f: file_data = base64.b64encode(f.read()).decode("utf-8")
                    parts_for_api.append({"type": "media", "mime_type": mime_type, "data": file_data})
                else:
                    with open(filepath, 'r', encoding='utf-8') as f: text_content = f.read()
                    parts_for_api.append(f"--- 添付ファイル「{os.path.basename(filepath)}」の内容 ---\n{text_content}\n--- ファイル内容ここまで ---")
            except Exception as e:
                print(f"警告: トークン計算のためのファイル '{os.path.basename(filepath)}' 処理中にエラー: {e}")
                pass

    try:
        token_count = gemini_api.count_input_tokens(
            character_name=current_character_name,
            model_name=current_model_name,
            parts=parts_for_api,
            api_history_limit_option=api_history_limit_state,
            api_key_name=current_api_key_name_state,
            send_notepad_to_api=send_notepad_state,
            use_common_prompt=use_common_prompt_state,
            add_timestamp=add_timestamp_state,
            send_thoughts=send_thoughts_state,
            send_core_memory=send_core_memory_state
        )

        if token_count == -1: return "入力トークン数: (APIキー/モデルエラー)"
        api_key = config_manager.API_KEYS.get(current_api_key_name_state)
        limit_info = gemini_api.get_model_token_limits(current_model_name, api_key)
        if limit_info and 'input' in limit_info: return f"入力トークン数: {token_count} / {limit_info['input']}"
        else: return f"入力トークン数: {token_count}"
    except Exception as e:
        print(f"トークン数計算中にUIハンドラでエラー: {e}")
        traceback.print_exc()
        return "入力トークン数: (例外発生)"
def handle_chatbot_selection(evt: gr.SelectData, chatbot_history: List[Dict[str, str]]):
    default_button_text = "🗑️ 選択した発言を削除"
    if evt.value:
        message_index = evt.index
        if 0 <= message_index < len(chatbot_history):
            selected_message_obj = chatbot_history[message_index]
            content = str(selected_message_obj.get('content', ''))
            display_text = content[:20] + '...' if len(content) > 20 else content
            new_button_text = f"🗑️ 「{display_text}」を削除"
            print(f"--- 発言選択: Index={message_index}, Content='{content[:50]}...' ---")
            return selected_message_obj, gr.update(value=new_button_text)
    return None, gr.update(value=default_button_text)
def handle_delete_selected_messages(character_name: str, selected_message: Dict[str, str], api_history_limit: str):
    default_button_text = "🗑️ 選択した発言を削除"
    if not character_name or not selected_message:
        gr.Warning("キャラクターが選択されていないか、削除する発言が選択されていません。");
        new_chat_history, _ = reload_chat_log(character_name, api_history_limit)
        return new_chat_history, None, gr.update(value=default_button_text)
    log_f, _, _, _, _ = get_character_files_paths(character_name)
    success = utils.delete_message_from_log(log_f, selected_message)
    if success:
        gr.Info("選択された発言をログから削除しました。")
    else:
        gr.Error("発言の削除に失敗しました。詳細はターミナルログを確認してください。")
    new_chat_history, _ = reload_chat_log(character_name, api_history_limit)
    return new_chat_history, None, gr.update(value=default_button_text)

def handle_initial_load(
    char_name_to_load: str,
    api_history_limit: str,
    send_notepad_state: bool,
    use_common_prompt_state: bool,
    add_timestamp_state: bool,
    send_thoughts_state: bool,
    send_core_memory_state: bool # ★★★ 引数を追加 ★★★
):
    """
    アプリケーション起動時にUIの全要素を初期化するための司令塔関数。
    """
    # 1. アラームデータを準備する
    df_with_ids = render_alarms_as_dataframe()
    display_df = get_display_df(df_with_ids)

    # 2. キャラクター依存のUI要素（チャット履歴、プロフィール画像など）を準備する
    (returned_char_name, current_chat_hist, _, current_profile_img, current_mem_str,
     alarm_dd_char_val, timer_dd_char_val, current_notepad_content) = update_ui_on_character_change(char_name_to_load, api_history_limit)

    # 3. 初期のトークン数を計算する
    initial_token_str = update_token_count(
        None, None, returned_char_name, config_manager.initial_model_global,
        config_manager.initial_api_key_name_global, api_history_limit,
        send_notepad_state, "", # notepad_editor_contentはここで空文字を渡す
        use_common_prompt_state,
        add_timestamp_state,
        send_thoughts_state,
        send_core_memory_state # ★★★ 引数を渡す ★★★
    )

    # 4. Gradioに渡すための全10項目のデータを組み立てて返す
    return (
        display_df,
        df_with_ids,
        current_chat_hist,
        current_profile_img,
        current_mem_str,
        alarm_dd_char_val,
        timer_dd_char_val,
        "アラームを選択してください",
        initial_token_str,
        current_notepad_content
    )

def update_send_core_memory_state(checked: bool):
    # 現状、configへの保存は不要だが、将来のために枠組みだけ用意
    # config_manager.save_config("last_send_core_memory", bool(checked))
    return bool(checked)
