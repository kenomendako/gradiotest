# ui_handlers.py の【確定版】

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
import mimetypes
import rag_manager

# --- モジュールインポート ---
import config_manager
import alarm_manager
import character_manager
from timers import UnifiedTimer
from character_manager import get_character_files_paths
from gemini_api import configure_google_api, invoke_rag_graph
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

def handle_message_submission(*args: Any) -> Tuple[List[Tuple[Union[str, Tuple[str, str], None], Union[str, Tuple[str, str], None]]], gr.update, gr.update]:
    (textbox_content, chatbot_history, current_character_name, current_model_name,
     file_input_list, add_timestamp_checkbox,
     send_thoughts_state, api_history_limit_state) = args

    log_f, sys_p, _, mem_p = None, None, None, None
    try:
        if not all([current_character_name, current_model_name]):
            gr.Warning("キャラクターとモデルを選択してください。APIキーは設定画面で確認してください。")
            return chatbot_history, gr.update(), gr.update(value=None)

        log_f, sys_p, _, mem_p = get_character_files_paths(current_character_name)
        if not all([log_f, sys_p, mem_p]):
            gr.Warning(f"キャラクター '{current_character_name}' の必須ファイルパス取得に失敗。")
            return chatbot_history, gr.update(), gr.update(value=None)

        user_prompt_from_textbox = textbox_content.strip() if textbox_content else ""

        # ★★★ ここからがファイル処理の新しいロジックです ★★★

        # テキストファイルの内容を追記するための変数
        text_files_content = ""
        # メディアファイル（画像、音声など）をAPIに渡すためのリスト
        media_files_for_api = []
        # ログに記録するためのファイル名リスト
        attached_filenames_for_log = []

        if file_input_list:
            for file_wrapper in file_input_list:
                actual_file_path = file_wrapper.name
                original_filename = os.path.basename(actual_file_path)
                attached_filenames_for_log.append(original_filename)

                mime_type, _ = mimetypes.guess_type(actual_file_path)
                if mime_type is None:
                    mime_type = "application/octet-stream" # 不明な場合はバイナリとして扱う

                # MIMEタイプに基づいて、テキストファイルかメディアファイルかを判断
                # application/octet-stream もテキストではないと判断する
                if mime_type.startswith('text/') or \
                   mime_type in ['application/json', 'application/javascript', 'application/xml', 'application/x-python', 'text/markdown', 'text/x-markdown', 'text/plain'] or \
                   any(original_filename.endswith(ext) for ext in ['.py', '.md', '.js', '.ts', '.html', '.css', '.xml', '.json', '.txt', '.log']): # 拡張子でも判定
                    # テキストベースのファイルの場合
                    try:
                        with open(actual_file_path, 'r', encoding='utf-8') as f:
                            file_content = f.read()
                        text_files_content += f"\n\n--- 添付ファイル: {original_filename} ---\n\n"
                        text_files_content += file_content
                        text_files_content += f"\n\n--- {original_filename} ここまで ---"
                    except Exception as e:
                        print(f"警告: テキストファイル '{original_filename}' の読み込み中にエラー: {e}")
                        # エラー時もファイル名とエラーの旨をプロンプトに含める
                        text_files_content += f"\n\n[エラー: ファイル '{original_filename}' の読み込みに失敗しました。理由: {e}]"
                else:
                    # メディアベースのファイルの場合 (またはMIMEタイプからテキストと判断できなかったもの)
                    media_files_for_api.append({"path": actual_file_path, "mime_type": mime_type})

        # 最終的なユーザープロンプトを構築
        final_user_prompt = user_prompt_from_textbox + text_files_content

        # ★★★ ここからが修正箇所 ★★★
        if not final_user_prompt.strip() and not media_files_for_api:
            # テキストもファイルも、両方ない場合は何もしない
            return chatbot_history, gr.update(), gr.update(value=None)

        # ログに記録するメッセージを作成
        log_message_content = user_prompt_from_textbox # ユーザーがテキストボックスに書いた内容のみを基本とする
        if attached_filenames_for_log: # 添付ファイルがある場合のみファイル名を追記
            log_message_content += "\n[ファイル添付: " + ", ".join(attached_filenames_for_log) + "]"

        # もしテキスト入力がなく、ファイル添付のみの場合は、
        # ログ記録はファイル名のみで行い、APIにはダミーテキストを渡す
        if not user_prompt_from_textbox.strip() and media_files_for_api:
            final_user_prompt_for_api = "（画像が添付されました）"
        else:
            final_user_prompt_for_api = final_user_prompt.strip()
        # ★★★ 修正ここまで ★★★

        user_header = _get_user_header_from_log(log_f, current_character_name)
        timestamp = f"\n{datetime.datetime.now().strftime('%Y-%m-%d (%a) %H:%M:%S')}" if add_timestamp_checkbox else ""
        # ログには、テキストボックスの入力とファイル名のみを記録（ファイル内容は記録しない）
        save_message_to_log(log_f, user_header, log_message_content.strip() + timestamp)

        # LangChainのMessage形式に合うように画像パーツを準備
        # (この時点ではgemini_api.pyへの受け渡しのみで、グラフ内では未使用)
        lc_image_parts = []
        if media_files_for_api:
            for file_info in media_files_for_api:
                # ここではMIMEタイプとパスのみを渡す（実際のデータ読み込みは不要）
                # 将来、グラフ内で画像認識を行う際に利用
                lc_image_parts.append({"type": "image_url", "image_url": {"url": f"file://{file_info['path']}"}})

        api_response_text, generated_image_path = invoke_rag_graph(
            character_name=current_character_name,
            user_prompt=final_user_prompt_for_api, # 修正：新しい変数を使う
            api_history_limit_option=api_history_limit_state,
            uploaded_file_parts=lc_image_parts
        )

        if api_response_text or generated_image_path:
            cleaned_api_response = api_response_text

            # AIが親切心で追加する可能性のある、あらゆる重複タグを除去する
            if generated_image_path and api_response_text:
                # 1. 我々のシステムが付与した[Generated Image: ...]と全く同じ形式のタグを除去
                tag_to_remove = f"[Generated Image: {generated_image_path}]"
                cleaned_api_response = cleaned_api_response.replace(tag_to_remove, "").strip()

                # 2. AIが生成するMarkdown形式の画像リンクを除去
                #    ファイル名さえ一致すれば、パスの形式（/や\、file:///）が違っても除去できるよう、
                #    正規表現を使って堅牢に対応します。
                # (関数の先頭に import re を追加してください)
                image_filename = os.path.basename(generated_image_path)
                # 例: ![...](.../image_name.png) というパターンに一致
                markdown_pattern = re.compile(r"!\[.*?\]\(.*?" + re.escape(image_filename) + r".*?\)\s*", re.IGNORECASE)
                cleaned_api_response = markdown_pattern.sub("", cleaned_api_response).strip()

            # クリーンアップされた応答を元に、ログに保存するメッセージを構築する
            response_to_log = ""
            if generated_image_path:
                response_to_log += f"[Generated Image: {generated_image_path}]\n\n"
            if cleaned_api_response:
                response_to_log += cleaned_api_response

            # 最終的に何も残らなかった場合を除き、ログに保存する
            if response_to_log.strip():
                 save_message_to_log(log_f, f"## {current_character_name}:", response_to_log)
    except Exception as e:
        traceback.print_exc()
        gr.Error(f"メッセージ処理中に予期せぬエラーが発生しました: {e}")

    if log_f and os.path.exists(log_f):
        new_log = load_chat_log(log_f, current_character_name)
        display_turns = _get_display_history_count(api_history_limit_state) # api_history_limit_state を使用
        new_hist: List[Tuple[Union[str, Tuple[str, str], None], Union[str, Tuple[str, str], None]]] = format_history_for_gradio(new_log[-(display_turns * 2):])
    else:
        new_hist = chatbot_history

    return new_hist, gr.update(value=""), gr.update(value=None) # file_input_list もクリア

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
    ok, msg = configure_google_api(api_key_name)
    config_manager.save_config("last_api_key_name", api_key_name)
    if ok: gr.Info(f"APIキー '{api_key_name}' 設定成功。")
    else: gr.Error(f"APIキー '{api_key_name}' 設定失敗: {msg}")
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

def handle_rag_update_button_click(character_name: str):
    if not character_name:
        gr.Warning("索引を更新するキャラクターが選択されていません。")
        return

    gr.Info(f"キャラクター「{character_name}」のRAG索引の更新を開始します...（ターミナルのログを確認してください）")

    import threading
    def run_update():
        success = rag_manager.create_or_update_index(character_name)
        if success:
            print(f"INFO: RAG索引の更新が正常に完了しました ({character_name})")
        else:
            print(f"ERROR: RAG索引の更新に失敗しました ({character_name})")

    threading.Thread(target=run_update).start()
