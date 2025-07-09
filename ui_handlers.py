# ui_handlers.py

import pandas as pd
from typing import List, Optional, Dict, Any, Tuple, Union
import gradio as gr
import datetime
import utils
import json
import traceback
import os
import shutil
import re
from PIL import Image
import base64
from langchain_core.messages import AIMessage # AIMessage をインポート

import gemini_api
import mem0_manager
import rag_manager
import config_manager
import alarm_manager
import re # ★★★ 正規表現を扱うために import
import datetime # ★★★ datetime を扱うために import
import character_manager
from timers import UnifiedTimer
from character_manager import get_character_files_paths
from gemini_api import send_multimodal_to_gemini # これは直接呼び出し用なので残す
from memory_manager import load_memory_data_safe, save_memory_data
from utils import load_chat_log, format_history_for_gradio, save_message_to_log, _get_user_header_from_log, save_log_file

def update_token_count(
    textbox_content: Optional[str],
    file_input_list: Optional[List[Any]], # Gradioのファイルオブジェクトのリスト
    current_character_name: str,
    current_model_name: str,
    current_api_key_name_state: str,
    api_history_limit_state: str,
    send_notepad_state: bool # ★★★ この引数を追加 ★★★
) -> str:
    """【改訂】基本入力トークン数を、モデルの上限と共に表示する"""
    if not all([current_character_name, current_model_name, current_api_key_name_state]): # send_notepad_state は bool なので all の判定に含めなくても良い
        return "入力トークン数 (設定不足)" # 初期表示用のデフォルト文字列

    parts_for_api = []
    if textbox_content: # テキスト入力があれば追加
        parts_for_api.append(textbox_content)

    if file_input_list:
        for file_wrapper in file_input_list:
            if not file_wrapper: # file_wrapperがNoneの場合スキップ
                continue
            file_path = file_wrapper.name # file_wrapperはgr.Filesからのオブジェクトで、name属性にパスを持つ
            try:
                # まず画像として開いてみる
                img = Image.open(file_path)
                parts_for_api.append(img) # PIL.Image オブジェクトを渡す
            except Exception:
                # 画像として開けなければテキストファイルとして試す
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        parts_for_api.append(f.read()) # ファイル内容の文字列を渡す
                except Exception as text_e:
                    print(f"トークン計算のためのファイル読み込みに失敗（画像でもテキストでもない可能性）: {file_path}, Error: {text_e}")

    # APIキーをconfig_managerから取得
    api_key = config_manager.API_KEYS.get(current_api_key_name_state)

    # モデルのトークン上限を取得
    limits = gemini_api.get_model_token_limits(current_model_name, api_key)
    limit_str = f" / {limits['input']:,}" if limits and 'input' in limits else ""

    # 基本入力トークン数を計算
    basic_tokens = gemini_api.count_input_tokens(
        character_name=current_character_name,
        model_name=current_model_name,
        parts=parts_for_api,
        api_history_limit_option=api_history_limit_state,
        api_key_name=current_api_key_name_state,
        send_notepad_to_api=send_notepad_state # ★★★ 引数を渡す ★★★
    )

    if basic_tokens >= 0:
        return f"**基本入力:** {basic_tokens:,}{limit_str} トークン"
    elif basic_tokens == -1: # APIキー無効を示す
        return "基本入力: (APIキー無効)"
    else: # 計算エラー (-2など)
        return "基本入力: (計算エラー)"

def handle_message_submission(*args: Any) -> Tuple[List[Dict[str, Union[str, tuple, None]]], gr.update, gr.update, str]:
    (textbox_content, chatbot_history, current_character_name, current_model_name,
     current_api_key_name_state, file_input_list, add_timestamp_checkbox,
     send_thoughts_state, api_history_limit_state) = args

    log_f, _, _, _, _ = get_character_files_paths(current_character_name) # 戻り値の数を5に変更
    user_prompt_from_textbox = textbox_content.strip() if textbox_content else ""

    parts_for_api = []
    attached_filenames_for_log = []

    if user_prompt_from_textbox:
        parts_for_api.append(user_prompt_from_textbox)
        urls = re.findall(r'(https?://\S+)', user_prompt_from_textbox)
        if urls:
            gr.Info(f"メッセージ内のURLを検出しました: {', '.join(urls)}\n内容を読み取ります...")

    if file_input_list:
        for file_wrapper in file_input_list:
            if not file_wrapper: continue
            actual_file_path = file_wrapper.name
            original_filename = os.path.basename(actual_file_path)
            attached_filenames_for_log.append(original_filename)
            try:
                img = Image.open(actual_file_path)
                parts_for_api.append(img)
                print(f"  - '{original_filename}' を画像として正常に処理。")
            except Exception: # 画像でなければテキストとして試す
                try:
                    with open(actual_file_path, 'r', encoding='utf-8') as f:
                        file_content = f.read()
                    # テキストファイルの場合、ファイル名と内容を区別して渡すのが良いかもしれないが、
                    # gemini_api._build_lc_messages_from_ui は文字列をそのまま受け付けるので、ここでは内容のみ
                    parts_for_api.append(file_content)
                    print(f"  - '{original_filename}' をテキストとして正常に処理。")
                except Exception as e2:
                    print(f"警告: ファイル '{original_filename}' の処理中にエラー: {e2}")

    # テキストもファイルもない場合は送信しない
    if not parts_for_api:
        # トークン表示も初期状態に戻す
        initial_token_display = update_token_count(None, None, current_character_name, current_model_name, current_api_key_name_state, api_history_limit_state)
        return chatbot_history, gr.update(), gr.update(value=None), initial_token_display


    log_message_content = user_prompt_from_textbox
    if attached_filenames_for_log:
        log_message_content += "\n[ファイル添付: " + ", ".join(attached_filenames_for_log) + "]"
    timestamp = f"\n{datetime.datetime.now().strftime('%Y-%m-%d (%a) %H:%M:%S')}" if add_timestamp_checkbox else ""

    api_response_text = ""
    final_agent_state: Dict[str, Any] = {} # エージェントの最終状態を格納

    try:
        api_key = config_manager.API_KEYS.get(current_api_key_name_state)
        if not api_key or api_key.startswith("YOUR_API_KEY"):
            gr.Warning(f"APIキー '{current_api_key_name_state}' が有効ではありません。")
            # APIキー無効時もトークン表示を更新
            token_display_on_error = update_token_count(textbox_content, file_input_list, current_character_name, current_model_name, current_api_key_name_state, api_history_limit_state)
            return chatbot_history, gr.update(), gr.update(value=None), token_display_on_error


        os.environ['GOOGLE_API_KEY'] = api_key # LangGraph内で使われる可能性を考慮

        # invoke_nexus_agent は AgentState (TypedDict) またはエラー情報を含むDictを返す
        final_agent_state = gemini_api.invoke_nexus_agent(
            character_name=current_character_name,
            model_name=current_model_name, # これはLangGraphのfinal_model_nameになる
            parts=parts_for_api,
            api_history_limit_option=api_history_limit_state,
            api_key_name=current_api_key_name_state
        )

        if final_agent_state.get("error"): # エラーが返ってきた場合
            api_response_text = f"[エラー: {final_agent_state['error']}]"
        elif final_agent_state and final_agent_state.get('messages'): # 正常なAgentStateの場合
            last_message = final_agent_state['messages'][-1]
            if isinstance(last_message, AIMessage): # LangChainのAIMessageか確認
                api_response_text = last_message.content
            else: # それ以外の場合はcontent属性を見るか文字列化
                api_response_text = str(last_message.content if hasattr(last_message, 'content') else last_message)

        # ログ保存
        final_log_message = log_message_content.strip() + timestamp
        if final_log_message.strip(): # 何かユーザー入力があればログる
            user_header = _get_user_header_from_log(log_f, current_character_name)
            utils.save_message_to_log(log_f, user_header, final_log_message)
            if api_response_text: # AIの応答があればログる
                utils.save_message_to_log(log_f, f"## {current_character_name}:", api_response_text)

            # Mem0への記憶 (エラーでない場合のみ)
            try:
                if api_key and final_log_message.strip() and api_response_text and not api_response_text.startswith("[エラー"):
                    mem0_instance = mem0_manager.get_mem0_instance(current_character_name, api_key)
                    conversation_to_add = [
                        {"role": "user", "content": final_log_message.strip()},
                        {"role": "assistant", "content": api_response_text.strip()}
                    ]
                    mem0_instance.add(messages=conversation_to_add, user_id=current_character_name)
                    print(f"--- Mem0に会話を記憶しました (Character: {current_character_name}) ---")
            except Exception as mem0_e:
                print(f"Mem0への記憶中にエラーが発生しました: {mem0_e}")
                traceback.print_exc()

    except Exception as e:
        traceback.print_exc()
        gr.Error(f"メッセージ処理中に予期せぬエラーが発生しました: {e}")
        api_response_text = f"[予期せぬエラー: {e}]" # エラー時もapi_response_textを設定

    # UI更新用のチャット履歴を準備
    if log_f and os.path.exists(log_f):
        new_log = load_chat_log(log_f, current_character_name)
        display_turns = _get_display_history_count(api_history_limit_state)
        new_hist = format_history_for_gradio(new_log[-(display_turns * 2):])
    else:
        new_hist = chatbot_history

    # トークン表示文字列の生成
    token_output_str = "入力トークン数" # デフォルト
    api_key_for_limits = config_manager.API_KEYS.get(current_api_key_name_state)
    limits = gemini_api.get_model_token_limits(current_model_name, api_key_for_limits)
    limit_str = f" / {limits['input']:,}" if limits and 'input' in limits else ""

    final_token_count = final_agent_state.get("final_token_count", 0) if final_agent_state else 0

    if final_token_count > 0: # LangGraphが最終トークン数を返した場合
        token_output_str = f"**最終入力:** {final_token_count:,}{limit_str} トークン"
    else: # LangGraphがトークン数を返さなかった場合やエラー時は、基本入力に戻す
        # この時点で再度基本入力を計算するか、エラー表示を維持するか。
        # 送信後は一旦リセットされたと見なして、再度計算するのが自然か。
        # ただし、エラーの場合はエラーメッセージを維持したい。
        if api_response_text.startswith("[エラー") or (final_agent_state and final_agent_state.get("error")):
             token_output_str = update_token_count(textbox_content, file_input_list, current_character_name, current_model_name, current_api_key_name_state, api_history_limit_state)
        else: # 正常終了したがfinal_token_countが0の場合（通常はないはずだが）
             token_output_str = update_token_count(None, None, current_character_name, current_model_name, current_api_key_name_state, api_history_limit_state)


    return new_hist, gr.update(value=""), gr.update(value=None), token_output_str


# (handle_add_new_character 以降の関数は変更なしのため省略)
def handle_add_new_character(character_name: str):
    if not character_name or not character_name.strip():
        gr.Warning("キャラクター名が入力されていません。")
        char_list = character_manager.get_character_list()
        return gr.update(choices=char_list), gr.update(choices=char_list), gr.update(choices=char_list), gr.update()
    safe_name = re.sub(r'[\/*?:"<>|]', "", character_name).strip()
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
    if api_history_limit_value == "all":
        return config_manager.UI_HISTORY_MAX_LIMIT
    try:
        return int(api_history_limit_value)
    except ValueError:
        return config_manager.UI_HISTORY_MAX_LIMIT

def update_ui_on_character_change(character_name: Optional[str], api_history_limit_value: str):
    if not character_name:
        all_chars = character_manager.get_character_list()
        character_name = all_chars[0] if all_chars else "Default"
        if not os.path.exists(os.path.join(config_manager.CHARACTERS_DIR, character_name)):
            character_manager.ensure_character_files(character_name)
    config_manager.save_config("last_character", character_name)
    log_f, _, img_p, mem_p, notepad_p = get_character_files_paths(character_name) # notepad_p を受け取る
    display_turns = _get_display_history_count(api_history_limit_value)
    chat_history = format_history_for_gradio(load_chat_log(log_f, character_name)[-(display_turns * 2):]) if log_f and os.path.exists(log_f) else []
    log_content = ""
    if log_f and os.path.exists(log_f):
        try:
            with open(log_f, "r", encoding="utf-8") as f: log_content = f.read()
        except Exception as e: log_content = f"ログ読込エラー: {e}"
    memory_str = json.dumps(load_memory_data_safe(mem_p), indent=2, ensure_ascii=False)
    profile_image = img_p if img_p and os.path.exists(img_p) else None
    notepad_content = load_notepad_content(character_name) # ★ メモ帳の内容を読み込み
    # 戻り値のタプルの最後に notepad_content を追加
    return character_name, chat_history, "", profile_image, memory_str, character_name, log_content, character_name, notepad_content

def handle_save_memory_click(character_name, json_string_data):
    if not character_name:
        gr.Warning("キャラクターが選択されていません。")
        return gr.update() # 何も変更しない命令を返す
    try:
        # save_memory_data が返す gr.update() 命令を受け取る
        update_action = save_memory_data(character_name, json_string_data)
        gr.Info("記憶を保存しました。") # 保存成功メッセージはここで表示
        # 受け取った命令を呼び出し元（Gradio）に返す
        return update_action
    except json.JSONDecodeError:
        gr.Error("記憶データのJSON形式が正しくありません。")
        return gr.update() # 何も変更しない命令を返す
    except Exception as e:
        gr.Error(f"記憶の保存中にエラーが発生しました: {e}")
        return gr.update() # 何も変更しない命令を返す

DAY_MAP_EN_TO_JA = {"mon": "月", "tue": "火", "wed": "水", "thu": "木", "fri": "金", "sat": "土", "sun": "日"}

def render_alarms_as_dataframe():
    alarms = alarm_manager.get_all_alarms()
    display_data = []
    for alarm in sorted(alarms, key=lambda x: x.get("time", "")):
        days_ja = [DAY_MAP_EN_TO_JA.get(d, d.upper()) for d in alarm.get('days', [])]
        display_data.append({"ID": alarm.get("id"), "状態": alarm.get("enabled", False), "時刻": alarm.get("time"), "曜日": ",".join(days_ja), "キャラ": alarm.get("character"), "テーマ": alarm.get("theme")})
    return pd.DataFrame(display_data, columns=["ID", "状態", "時刻", "曜日", "キャラ", "テーマ"])

def get_display_df(df_with_id: pd.DataFrame):
    if df_with_id is None or df_with_id.empty or 'ID' not in df_with_id.columns:
        return pd.DataFrame(columns=["状態", "時刻", "曜日", "キャラ", "テーマ"])
    return df_with_id[["状態", "時刻", "曜日", "キャラ", "テーマ"]]

def handle_alarm_selection(evt: gr.SelectData, df_with_id: pd.DataFrame) -> List[str]:
    if evt.index is None or df_with_id is None or df_with_id.empty:
        return []
    indices_to_process: list[int]
    if isinstance(evt.index, int):
        indices_to_process = [evt.index]
    elif isinstance(evt.index, list):
        indices_to_process = evt.index
    else:
        return []
    selected_ids = []
    for i in indices_to_process:
        if 0 <= i < len(df_with_id):
            selected_ids.append(str(df_with_id.iloc[i]['ID']))
    return selected_ids

def handle_alarm_selection_and_feedback(evt: gr.SelectData, df_with_id: pd.DataFrame):
    selected_ids = handle_alarm_selection(evt, df_with_id)
    count = len(selected_ids)
    feedback_text = "アラームを選択してください"
    if count == 1:
        feedback_text = f"1 件のアラームを選択中"
    elif count > 1:
        feedback_text = f"{count} 件のアラームを選択中"
    return selected_ids, feedback_text

def toggle_selected_alarms_status(selected_ids: list, target_status: bool):
    if not selected_ids:
        gr.Warning("状態を変更するアラームが選択されていません。")
    else:
        changed_count = 0
        status_text = "有効" if target_status else "無効"
        for alarm_id in selected_ids:
            alarm = alarm_manager.get_alarm_by_id(alarm_id)
            if alarm and alarm.get("enabled") != target_status:
                if alarm_manager.toggle_alarm_enabled(alarm_id): changed_count += 1
        if changed_count > 0: gr.Info(f"{changed_count}件のアラームを「{status_text}」に変更しました。")
    return render_alarms_as_dataframe()

def handle_delete_selected_alarms(selected_ids: list):
    if not selected_ids:
        gr.Warning("削除するアラームが選択されていません。")
    else:
        deleted_count = sum(1 for sid in selected_ids if alarm_manager.delete_alarm(str(sid)))
        if deleted_count > 0: gr.Info(f"{deleted_count}件のアラームを削除しました。")
    return render_alarms_as_dataframe()

def handle_timer_submission(timer_type, duration, work, brk, cycles, char, work_theme, brk_theme, api_key, webhook, normal_theme):
    if not char or not api_key: return "エラー：キャラクターとAPIキーを選択してください。"
    try:
        timer = UnifiedTimer(timer_type, float(duration or 0), float(work or 0), float(brk or 0), int(cycles or 0), char, work_theme, brk_theme, api_key, webhook, normal_theme)
        timer.start()
        gr.Info(f"{timer_type}を開始しました。")
        return f"{timer_type}を開始しました。"
    except Exception as e: return f"タイマー開始エラー: {e}"

def update_model_state(model):
    config_manager.save_config("last_model", model)
    return model

def update_api_key_state(api_key_name):
    config_manager.save_config("last_api_key_name", api_key_name)
    gr.Info(f"APIキーを '{api_key_name}' に設定しました。")
    return api_key_name

def update_timestamp_state(checked): config_manager.save_config("add_timestamp", bool(checked))
def update_send_thoughts_state(checked):
    config_manager.save_config("last_send_thoughts_to_api", bool(checked))
    return bool(checked)

def update_api_history_limit_state_and_reload_chat(limit_ui_val: str, character_name: Optional[str]):
    key = next((k for k, v in config_manager.API_HISTORY_LIMIT_OPTIONS.items() if v == limit_ui_val), "all")
    config_manager.save_config("last_api_history_limit_option", key)
    chat_history, log_content = reload_chat_log(character_name, key)
    return key, chat_history, log_content

def reload_chat_log(character_name: Optional[str], api_history_limit_value: str):
    if not character_name: return [], "キャラクター未選択"
    log_f,_,_,_,_ = get_character_files_paths(character_name) # 戻り値の数を5に変更
    if not log_f or not os.path.exists(log_f): return [], "ログファイルなし"
    display_turns = _get_display_history_count(api_history_limit_value)
    history = format_history_for_gradio(load_chat_log(log_f, character_name)[-(display_turns*2):])
    content = ""
    if log_f and os.path.exists(log_f):
        with open(log_f, "r", encoding="utf-8") as f: content = f.read()
    return history, content

def handle_save_log_button_click(character_name, log_content):
    if not character_name: gr.Error("キャラクターが選択されていません。")
    else:
        save_log_file(character_name, log_content)
        gr.Info(f"'{character_name}'のログを保存しました。")

def load_alarm_to_form(selected_ids: list):
    default_char = character_manager.get_character_list()[0] if character_manager.get_character_list() else "Default"
    if not selected_ids or len(selected_ids) != 1:
        return "アラーム追加", "", "", default_char, ["月","火","水","木","金","土","日"], "08", "00", None
    alarm_id_str = selected_ids[0]
    alarm = alarm_manager.get_alarm_by_id(alarm_id_str)
    if not alarm:
        gr.Warning(f"アラームID '{alarm_id_str}' が見つかりません。")
        return "アラーム追加", "", "", default_char, ["月","火","水","木","金","土","日"], "08", "00", None
    h, m = alarm.get("time", "08:00").split(":")
    days_en = alarm.get("days", [])
    days_ja = [DAY_MAP_EN_TO_JA.get(d.lower(), d.upper()) for d in days_en]
    return f"アラーム更新", alarm.get("theme", ""), alarm.get("flash_prompt_template", ""), alarm.get("character", default_char), days_ja, h, m, alarm_id_str

def handle_add_or_update_alarm(editing_id, h, m, char, theme, prompt, days):
    default_char_for_form = character_manager.get_character_list()[0] if character_manager.get_character_list() else "Default"
    alarm_add_button_text = "アラーム更新" if editing_id else "アラーム追加"
    if not char:
        gr.Warning("キャラクターが選択されていません。")
        df_with_ids = render_alarms_as_dataframe()
        display_df = get_display_df(df_with_ids)
        return display_df, df_with_ids, alarm_add_button_text, theme, prompt, char, days, h, m, editing_id
    success = False
    if editing_id:
        # Not implemented yet
        pass
    else:
        if alarm_manager.add_alarm(h, m, char, theme, prompt, days):
            gr.Info(f"新しいアラームを追加しました。")
            success = True
        else:
            gr.Warning("新しいアラームの追加に失敗しました。")
    df_with_ids = render_alarms_as_dataframe()
    display_df = get_display_df(df_with_ids)
    if success:
        return display_df, df_with_ids, "アラーム追加", "", "", default_char_for_form, ["月","火","水","木","金","土","日"], "08", "00", None
    else:
        return display_df, df_with_ids, alarm_add_button_text, theme, prompt, char, days, h, m, editing_id

def handle_rag_update_button_click(character_name: str, api_key_name: str):
    if not character_name:
        gr.Warning("索引を更新するキャラクターが選択されていません。")
        return
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        gr.Warning(f"APIキー '{api_key_name}' が有効ではありません。RAG索引の更新を中止します。")
        return
    gr.Info(f"キャラクター「{character_name}」のRAG索引の更新を開始します...（ターミナルのログを確認してください）")
    import threading
    def run_update():
        success = rag_manager.create_or_update_index(character_name, api_key)
        if success:
            print(f"INFO: RAG索引の更新が正常に完了しました ({character_name})")
        else:
            print(f"ERROR: RAG索引の更新に失敗しました ({character_name})")
    threading.Thread(target=run_update).start()

# --- メモ帳送信設定ハンドラ ---
def update_send_notepad_state(checked: bool):
    """メモ帳送信設定の状態を更新する（保存はしない想定、UIのStateに反映される）"""
    # config_manager を使って永続化も可能だが、今回はUIのStateのみ更新
    return checked

# --- メモ帳 (notepad.md) UIハンドラ ---

def load_notepad_content(character_name: str) -> str:
    """指定されたキャラクターの notepad.md の内容を返す"""
    if not character_name:
        return ""
    _, _, _, _, notepad_path = get_character_files_paths(character_name)
    if notepad_path and os.path.exists(notepad_path):
        with open(notepad_path, "r", encoding="utf-8") as f:
            return f.read()
    return ""

def handle_save_notepad_click(character_name: str, content: str) -> str: # AI Studio案では handle_save_notepad
    """
    メモ帳の内容を受け取り、タイムスタンプを自動整形して保存する。
    整形後の内容を返す。
    """
    if not character_name:
        gr.Warning("キャラクターが選択されていません。")
        return content # 何もせず元の内容を返す

    _, _, _, _, notepad_path = character_manager.get_character_files_paths(character_name)
    if not notepad_path: # notepad_path が None の場合のエラーハンドリング
        gr.Error(f"キャラクター「{character_name}」のメモ帳パスの取得に失敗しました。")
        return content

    lines = content.strip().split('\n')
    processed_lines = []
    # タイムスタンプの形式をチェックする正規表現パターン
    timestamp_pattern = re.compile(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\]")

    for line in lines:
        stripped_line = line.strip()
        if not stripped_line:
            continue # 空行は無視

        # 行頭がタイムスタンプ形式でなければ、新しく付与する
        if not timestamp_pattern.match(stripped_line):
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
            processed_lines.append(f"[{timestamp}] {stripped_line}")
        else:
            # 既にタイムスタンプがあれば、そのまま追加
            processed_lines.append(stripped_line)

    final_content = "\n".join(processed_lines)

    try:
        # notepad.md ファイルに書き込む（ファイル末尾に改行を入れると管理しやすい）
        with open(notepad_path, "w", encoding="utf-8") as f:
            f.write(final_content + '\n' if final_content else "") # 空の場合は改行も不要
        gr.Info(f"「{character_name}」のメモ帳を保存しました。")
        return final_content # 整形後の内容をUIに反映させるために返す
    except Exception as e:
        error_msg = f"メモ帳の保存中にエラーが発生しました: {e}"
        gr.Error(error_msg)
        traceback.print_exc() # エラー詳細をターミナルに出力
        return content # エラー時は元の内容を返す

def handle_clear_notepad_click(character_name: str) -> str: # AI Studio案では handle_clear_notepad
    """
    メモ帳の内容をすべてクリアする。
    """
    if not character_name:
        gr.Warning("キャラクターが選択されていません。")
        return "" # 空文字列を返してエディタをクリア期待

    _, _, _, _, notepad_path = character_manager.get_character_files_paths(character_name)
    if not notepad_path: # notepad_path が None の場合のエラーハンドリング
        gr.Error(f"キャラクター「{character_name}」のメモ帳パスの取得に失敗しました。")
        return "" # 現状の内容を維持（あるいはエラー表示に適した文字列）

    try:
        # ファイルを空にする
        with open(notepad_path, "w", encoding="utf-8") as f:
            f.write("") # 空の文字列を書き込む
        gr.Info(f"「{character_name}」のメモ帳を空にしました。")
        return "" # UIのエディタも空にするために空文字列を返す
    except Exception as e:
        error_msg = f"メモ帳のクリア中にエラーが発生しました: {e}"
        gr.Error(error_msg)
        traceback.print_exc() # エラー詳細をターミナルに出力
        # エラー時は何を返すか？ UIをクリアせず元の内容を維持するか、エラーメッセージをエディタに出すか。
        # ここではクリアを試みたが失敗した、という状況なので空文字列を返してUIクリアを試みる。
        # あるいは、gr.update() で元の内容を維持する方が親切かもしれない。
        # AI Studio案では f"エラー: {e}" を返しているので、それに倣う。ただし、gr.Codeは文字列をそのまま表示する。
        return f"エラー発生: {e}" # UIにエラーメッセージを表示させる

def handle_reload_notepad(character_name: str) -> str:
    """
    指定されたキャラクターの notepad.md ファイルを読み込み、その内容を返す。
    UIのメモ帳エディタを更新するために使用する。
    """
    if not character_name:
        gr.Warning("キャラクターが選択されていません。")
        return ""

    # キャラクターに対応するメモ帳ファイルのパスを取得
    # get_character_files_paths は5つの値を返すので、不要なものは _ で受け取る
    _, _, _, _, notepad_path = character_manager.get_character_files_paths(character_name)

    if notepad_path and os.path.exists(notepad_path):
        try:
            with open(notepad_path, "r", encoding="utf-8") as f:
                content = f.read()
            gr.Info(f"「{character_name}」のメモ帳を再読み込みしました。")
            return content
        except Exception as e:
            error_msg = f"メモ帳の読み込み中にエラーが発生しました: {e}"
            gr.Error(error_msg)
            return error_msg # エラー時もメッセージをエディタに表示するならこれでOK
    else:
        # ファイルが存在しない場合は空の文字列を返す
        gr.Info(f"「{character_name}」のメモ帳は存在しないか空です。") # 存在しない場合も通知
        return ""
