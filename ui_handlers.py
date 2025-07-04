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
import mimetypes
import rag_manager # 追加
import google.genai as genai # 追加
import gemini_api # 追加

# --- モジュールインポート ---
import config_manager
import alarm_manager
import character_manager
from timers import UnifiedTimer
from character_manager import get_character_files_paths
# gemini_apiモジュールからsend_multimodal_to_geminiのみをインポート
from gemini_api import send_multimodal_to_gemini
from memory_manager import load_memory_data_safe, save_memory_data
from utils import load_chat_log, format_history_for_gradio, save_message_to_log, _get_user_header_from_log, save_log_file

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
    """API履歴送信設定値からUI表示件数を決定する"""
    if api_history_limit_value == "all":
        return config_manager.UI_HISTORY_MAX_LIMIT
    try:
        return int(api_history_limit_value)
    except ValueError:
        return config_manager.UI_HISTORY_MAX_LIMIT # デフォルトまたは不正値の場合

def update_ui_on_character_change(character_name: Optional[str], api_history_limit_value: str):
    if not character_name:
        all_chars = character_manager.get_character_list()
        character_name = all_chars[0] if all_chars else "Default"
        if not os.path.exists(os.path.join(config_manager.CHARACTERS_DIR, character_name)):
            character_manager.ensure_character_files(character_name)

    config_manager.save_config("last_character", character_name)
    log_f, _, img_p, mem_p = get_character_files_paths(character_name)

    display_turns = _get_display_history_count(api_history_limit_value)
    chat_history = format_history_for_gradio(load_chat_log(log_f, character_name)[-(display_turns * 2):]) if log_f and os.path.exists(log_f) else []

    log_content = ""
    if log_f and os.path.exists(log_f):
        try:
            with open(log_f, "r", encoding="utf-8") as f: log_content = f.read()
        except Exception as e: log_content = f"ログ読込エラー: {e}"
    memory_str = json.dumps(load_memory_data_safe(mem_p), indent=2, ensure_ascii=False)
    profile_image = img_p if img_p and os.path.exists(img_p) else None
    return character_name, chat_history, "", profile_image, memory_str, character_name, log_content, character_name

def handle_save_memory_click(character_name, json_string_data):
    if not character_name:
        gr.Warning("キャラクターが選択されていません。")
        return
    try:
        save_memory_data(character_name, json_string_data)
        gr.Info("記憶を保存しました。")
    except json.JSONDecodeError:
        gr.Error("記憶データのJSON形式が正しくありません。")
    except Exception as e:
        gr.Error(f"記憶の保存中にエラーが発生しました: {e}")

def handle_message_submission(*args: Any) -> Tuple[List[Dict[str, Union[str, tuple, None]]], gr.update, gr.update]:
    (textbox_content, chatbot_history, current_character_name, current_model_name,
     current_api_key_name_state, # この行を追加
     file_input_list, add_timestamp_checkbox,
     send_thoughts_state, api_history_limit_state) = args

    # UIから基本的な情報を取得
    log_f, _, _, _ = get_character_files_paths(current_character_name)
    user_prompt_from_textbox = textbox_content.strip() if textbox_content else ""

    # Gemini APIに渡すパーツリストを準備
    parts_for_api = []
    attached_filenames_for_log = []

    # 1. テキスト部分をリストに追加
    if user_prompt_from_textbox:
        parts_for_api.append(user_prompt_from_textbox)

        # --- URL検出処理 ---
        urls = re.findall(r'(https?://\S+)', user_prompt_from_textbox)
        if urls:
            gr.Info(f"メッセージ内のURLを検出しました: {', '.join(urls)}\n内容を読み取ります...")
            # URLはテキストプロンプトの一部として既にparts_for_apiに追加されています。
            # LangGraph側でAIがこれを認識し、read_url_toolの使用を判断することを期待します。

    # 2. ファイル部分をリストに追加
    if file_input_list:
        print(f"--- {len(file_input_list)}個のファイルを処理開始 ---")
        for file_wrapper in file_input_list:
            actual_file_path = file_wrapper.name
            original_filename = os.path.basename(actual_file_path)
            attached_filenames_for_log.append(original_filename)
            try:
                # PIL Imageオブジェクトとして画像を開く
                img = Image.open(actual_file_path)
                parts_for_api.append(img)
                print(f"  - '{original_filename}' を画像として正常に処理。")
            except Exception as e:
                # 画像として開けなかった場合はテキストとして試す
                try:
                    with open(actual_file_path, 'r', encoding='utf-8') as f:
                        file_content = f.read()
                    text_part = f"\n--- 添付ファイル: {original_filename} ---\n{file_content}\n--- {original_filename} ここまで ---"
                    parts_for_api.append(text_part)
                    print(f"  - '{original_filename}' をテキストとして正常に処理。")
                except Exception as e2:
                    print(f"警告: ファイル '{original_filename}' の処理中にエラー: {e2}")
                    traceback.print_exc()


    # --- 入力チェックとログ記録 ---
    if not parts_for_api:
        return chatbot_history, gr.update(), gr.update(value=None)

    log_message_content = user_prompt_from_textbox
    if attached_filenames_for_log:
        log_message_content += "\n[ファイル添付: " + ", ".join(attached_filenames_for_log) + "]"

    user_header = _get_user_header_from_log(log_f, current_character_name)
    timestamp = f"\n{datetime.datetime.now().strftime('%Y-%m-%d (%a) %H:%M:%S')}" if add_timestamp_checkbox else ""
    # ★ユーザーメッセージのログ保存はAPI呼び出し後に移動

    # --- Gemini APIの呼び出し ---
    try:
        # --- APIキーを環境変数に設定 ---
        # これが最も確実なAPIキーの渡し方
        api_key = config_manager.API_KEYS.get(current_api_key_name_state)
        if not api_key or api_key.startswith("YOUR_API_KEY"):
            gr.Warning(f"APIキー '{current_api_key_name_state}' が有効ではありません。")
            # この後、空の履歴などを返して処理を中断する
            return chatbot_history, gr.update(), gr.update(value=None)

        os.environ['GOOGLE_API_KEY'] = api_key # APIキーの設定はLangGraph呼び出し前に行うのが適切

        # ★★★ ここで呼び出す関数を、invoke_nexus_agent に統一する ★★★
        # 古い呼び出し: api_response_text, _ = send_multimodal_to_gemini(...)

        # 新しい呼び出し
        # generated_image_path は invoke_nexus_agent から返されないため、一旦Noneで受けるか、返り値を調整する必要がある。
        # ここではひとまず _ で受けて無視する。画像生成をLangGraphに統合する場合は別途検討。
        api_response_text, _ = gemini_api.invoke_nexus_agent(
            character_name=current_character_name,
            model_name=current_model_name, # invoke_nexus_agent は model_name を使わないが、互換性のために残す
            parts=parts_for_api,
            api_history_limit_option=api_history_limit_state,
            api_key_name=current_api_key_name_state # APIキー名を渡す
        )

        # ★★★【最後の真実】ログ保存は、全てが、終わった、ここで、行う ★★★
        # ユーザー入力の、テキスト部分を、再構築 (log_message_content はAPI呼び出し前に準備済み)
        # タイムスタンプを追加 (timestamp はAPI呼び出し前に準備済み)
        final_log_message = log_message_content.strip() + timestamp

        if final_log_message.strip(): # ユーザー入力があった場合のみ (添付ファイルのみでも可)
            # user_header はAPI呼び出し前に準備済み
            # 1. ユーザーの発言を保存
            utils.save_message_to_log(log_f, user_header, final_log_message)
            # 2. AIの応答を保存
            if api_response_text: # AIの応答があった場合のみ
                utils.save_message_to_log(log_f, f"## {current_character_name}:", api_response_text)

    except Exception as e:
        traceback.print_exc()
        gr.Error(f"メッセージ処理中に予期せぬエラーが発生しました: {e}")

    # --- UIの更新 ---
    if log_f and os.path.exists(log_f):
        new_log = load_chat_log(log_f, current_character_name)
        display_turns = _get_display_history_count(api_history_limit_state)
        new_hist = format_history_for_gradio(new_log[-(display_turns * 2):])
    else:
        new_hist = chatbot_history

    return new_hist, gr.update(value=""), gr.update(value=None)


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
    # ★★★ この2行を完全に削除する ★★★
    # ok, msg = gemini_api.configure_google_api(api_key_name)
    # if ok: gr.Info(f"APIキー '{api_key_name}' 設定成功。")
    # else: gr.Error(f"APIキー '{api_key_name}' 設定失敗: {msg}")

    # この2行は残す
    config_manager.save_config("last_api_key_name", api_key_name)
    gr.Info(f"APIキーを '{api_key_name}' に設定しました。") # ← メッセージを成功確定に変更
    return api_key_name

def update_timestamp_state(checked): config_manager.save_config("add_timestamp", bool(checked))
def update_send_thoughts_state(checked):
    config_manager.save_config("last_send_thoughts_to_api", bool(checked))
    return bool(checked)

def update_api_history_limit_state_and_reload_chat(limit_ui_val: str, character_name: Optional[str]):
    """API履歴制限設定を更新し、チャットログも再読み込みする"""
    # API履歴制限設定のキーを取得・保存
    key = next((k for k, v in config_manager.API_HISTORY_LIMIT_OPTIONS.items() if v == limit_ui_val), "all")
    config_manager.save_config("last_api_history_limit_option", key)

    # チャットログの再読み込み
    # reload_chat_log 関数は (history, content) を返す
    # ここでは key (例: "10", "all") を api_history_limit_value として渡す
    chat_history, log_content = reload_chat_log(character_name, key)

    return key, chat_history, log_content

def reload_chat_log(character_name: Optional[str], api_history_limit_value: str):
    if not character_name: return [], "キャラクター未選択"
    log_f,_,_,_ = get_character_files_paths(character_name)
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
        if alarm_manager.update_alarm(editing_id, h, m, char, theme, prompt, days):
            gr.Info(f"アラームID '{editing_id}' を更新しました。")
            success = True
        else:
             gr.Warning(f"アラームID '{editing_id}' の更新に失敗しました。")
    else:
        new_alarm_id = alarm_manager.add_alarm(h, m, char, theme, prompt, days)
        if new_alarm_id:
            gr.Info(f"新しいアラーム (ID: {new_alarm_id}) を追加しました。")
            success = True
        else:
            gr.Warning("新しいアラームの追加に失敗しました。")

    df_with_ids = render_alarms_as_dataframe()
    display_df = get_display_df(df_with_ids)

    if success:
        return display_df, df_with_ids, "アラーム追加", "", "", default_char_for_form, ["月","火","水","木","金","土","日"], "08", "00", None
    else:
        return display_df, df_with_ids, alarm_add_button_text, theme, prompt, char, days, h, m, editing_id

def handle_rag_update_button_click(character_name: str, api_key_name: str): # ★★★ api_key_name を引数に追加
    if not character_name:
        gr.Warning("索引を更新するキャラクターが選択されていません。")
        return

    # ★★★【追加】APIキーを取得する ★★★
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"): # 有効なキーかもチェック
        gr.Warning(f"APIキー '{api_key_name}' が有効ではありません。RAG索引の更新を中止します。")
        return

    gr.Info(f"キャラクター「{character_name}」のRAG索引の更新を開始します...（ターミナルのログを確認してください）")

    import threading
    def run_update():
        # ★★★【修正】取得したAPIキーを渡す ★★★
        success = rag_manager.create_or_update_index(character_name, api_key)
        if success:
            print(f"INFO: RAG索引の更新が正常に完了しました ({character_name})")
        else:
            print(f"ERROR: RAG索引の更新に失敗しました ({character_name})")

    threading.Thread(target=run_update).start()
