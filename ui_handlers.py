# ui_handlers.py の【真の最終・確定・解決版】

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

# --- モジュールインポート ---
import config_manager
import alarm_manager
import character_manager
from timers import UnifiedTimer
from character_manager import get_character_files_paths
from gemini_api import configure_google_api, send_to_gemini
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

def update_ui_on_character_change(character_name: Optional[str]):
    if not character_name:
        all_chars = character_manager.get_character_list()
        character_name = all_chars[0] if all_chars else "Default"
        if not os.path.exists(os.path.join(config_manager.CHARACTERS_DIR, character_name)):
            character_manager.ensure_character_files(character_name)

    config_manager.save_config("last_character", character_name)
    log_f, _, img_p, mem_p = get_character_files_paths(character_name)
    chat_history = format_history_for_gradio(load_chat_log(log_f, character_name)[-(config_manager.HISTORY_LIMIT * 2):]) if log_f and os.path.exists(log_f) else []
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

# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
# ★★★ これが、ファイル添付を修正する、唯一の正しいハンドラです ★★★
# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
def handle_message_submission(*args: Any) -> Tuple[List, gr.update, gr.update]:
    (textbox_content, chatbot_history, current_character_name, current_model_name,
     current_api_key_name_state, file_input_list, add_timestamp_checkbox,
     send_thoughts_state, api_history_limit_state) = args

    log_f, sys_p, _, mem_p = None, None, None, None
    try:
        if not all([current_character_name, current_model_name, current_api_key_name_state]):
            gr.Warning("キャラクター、モデル、APIキーをすべて選択してください。")
            return chatbot_history, gr.update(), gr.update(value=None)
        log_f, sys_p, _, mem_p = get_character_files_paths(current_character_name)
        if not all([log_f, sys_p, mem_p]):
            gr.Warning(f"キャラクター '{current_character_name}' の必須ファイルパス取得に失敗。")
            return chatbot_history, gr.update(), gr.update(value=None)

        user_prompt = textbox_content.strip() if textbox_content else ""
        if not user_prompt and not file_input_list:
            return chatbot_history, gr.update(), gr.update(value=None)

        # --- 正しいファイル処理ロジック ---
        log_message_content = user_prompt
        # file_input_list は ['path/to/file1.txt', 'path/to/file2.jpg'] のような文字列のリスト
        if file_input_list:
            for file_path in file_input_list:
                log_message_content += f"\n[ファイル添付: {file_path}]"

        user_header = _get_user_header_from_log(log_f, current_character_name)
        timestamp = f"\n{datetime.datetime.now().strftime('%Y-%m-%d (%a) %H:%M:%S')}" if add_timestamp_checkbox else ""
        save_message_to_log(log_f, user_header, log_message_content.strip() + timestamp)

        uploaded_files_info = []
        if file_input_list:
            for file_path in file_input_list:
                mime_type, _ = mimetypes.guess_type(file_path)
                if mime_type is None: mime_type = "application/octet-stream"
                uploaded_files_info.append({"path": file_path, "mime_type": mime_type})
        # --- ここまでが正しいファイル処理ロジック ---

        api_response_text, generated_image_path = send_to_gemini(
            sys_p, log_f, user_prompt, current_model_name,
            current_character_name, send_thoughts_state,
            api_history_limit_state,
            uploaded_files_info,
            mem_p
        )

        if api_response_text or generated_image_path:
            response_to_log = ""
            if generated_image_path:
                response_to_log += f"[Generated Image: {generated_image_path}]\n\n"
            if api_response_text:
                response_to_log += api_response_text
            save_message_to_log(log_f, f"## {current_character_name}:", response_to_log)
    except Exception as e:
        traceback.print_exc()
        gr.Error(f"メッセージ処理中に予期せぬエラーが発生しました: {e}")

    if log_f and os.path.exists(log_f):
        new_log = load_chat_log(log_f, current_character_name)
        new_hist = format_history_for_gradio(new_log[-(config_manager.HISTORY_LIMIT * 2):])
    else:
        new_hist = chatbot_history

    return new_hist, gr.update(value=""), gr.update(value=None)
# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★

# ui_handlers.py のアラーム関連ハンドラ (修正後)

DAY_MAP_EN_TO_JA = {"mon": "月", "tue": "火", "wed": "水", "thu": "木", "fri": "金", "sat": "土", "sun": "日"}
DAY_MAP_JA_TO_EN = {v: k for k, v in DAY_MAP_EN_TO_JA.items()}

def render_alarms_as_dataframe():
    """アラームリストからDataFrameを生成する。ID列を含む。"""
    all_alarms = alarm_manager.get_all_alarms() # list of dicts
    df_data = []
    # ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
    # ★★★ ここがlistを正しくループする修正箇所です ★★★
    # ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
    for alarm_data in all_alarms:
        days_ja_str = ", ".join([DAY_MAP_EN_TO_JA.get(d, "?") for d in alarm_data.get("days", [])])
        df_data.append({
            "id": alarm_data.get("id"),
            "状態": alarm_data.get("enabled", False),
            "時刻": alarm_data.get("time", ""),
            "曜日": days_ja_str,
            "キャラ": alarm_data.get("character", ""),
            "テーマ": alarm_data.get("theme", "")
        })
    df = pd.DataFrame(df_data)
    if not df.empty:
        df = df.sort_values(by=["時刻", "曜日"]).reset_index(drop=True)
    return df

def get_display_df(df_with_ids: pd.DataFrame) -> pd.DataFrame:
    """表示用のDataFrameからID列を除外する。"""
    if df_with_ids.empty or "id" not in df_with_ids.columns:
        return pd.DataFrame(columns=["状態", "時刻", "曜日", "キャラ", "テーマ"])
    return df_with_ids[["状態", "時刻", "曜日", "キャラ", "テーマ"]]

# ui_handlers.py (関数を置き換え・最終確定版)

def handle_alarm_selection_and_feedback(df_with_ids: pd.DataFrame, evt: gr.SelectData):
    """Dataframeでの行選択を処理し、選択されたIDとフィードバックメッセージを返す。単一選択・複数選択の両方に対応した堅牢な実装。"""

    # ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
    # ★★★ これが単一選択(タプル)と複数選択(リスト)の両データ形式に対応する【最終・完全・確定版】のロジックです ★★★
    # ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★

    if evt.index is None:
        return [], "アラームを選択してください"

    # どんな場合でも処理できるよう、常にタプルのリスト形式に正規化する
    indices_list = evt.index if isinstance(evt.index, list) else [evt.index]

    if not indices_list:
        return [], "アラームを選択してください"

    # 選択された行のインデックスだけを重複なく抽出
    try:
        selected_row_indices = sorted(list(set([idx[0] for idx in indices_list])))
    except (TypeError, IndexError):
        # 不正なイベントデータの場合
        return [], "選択情報の取得に失敗しました。再度お試しください。"

    if not selected_row_indices or df_with_ids.empty:
        return [], "アラームを選択してください"

    # 行インデックスを使って、元のDataFrameからIDを取得
    try:
        valid_indices = [i for i in selected_row_indices if i < len(df_with_ids)]
        if not valid_indices:
            return [], "選択した行が見つかりません。"
        selected_ids = df_with_ids.iloc[valid_indices]["id"].tolist()
    except (KeyError, IndexError):
        return [], "IDの取得に失敗しました。"

    # フィードバックメッセージを作成
    if len(selected_ids) == 1:
        selected_alarm_row = df_with_ids.iloc[valid_indices[0]]
        feedback_message = f"選択中: 「{selected_alarm_row['テーマ']}」 ({selected_alarm_row['時刻']})"
    else:
        feedback_message = f"{len(selected_ids)}件のアラームを選択中"

    return selected_ids, feedback_message


def load_alarm_to_form(selected_ids: list[str]): # Changed List[str] to list[str] for compatibility
    """単一のアラームが選択された場合、その情報を編集フォームに読み込む。"""
    # 選択解除時、または複数選択時はフォームをリセット
    if not selected_ids or len(selected_ids) != 1:
        char_list = character_manager.get_character_list()
        default_char = char_list[0] if char_list else None
        return gr.update(value="アラーム追加"), "", "", default_char, list(DAY_MAP_JA_TO_EN.values()), "08", "00", None

    alarm_id = selected_ids[0]
    alarm_data = alarm_manager.get_alarm_by_id(alarm_id) # ★ get_alarm -> get_alarm_by_id に修正

    if not alarm_data:
        gr.Warning(f"ID '{alarm_id}'のアラームが見つかりません。")
        return gr.update(value="アラーム追加"), "", "", None, [], "08", "00", None

    hour, minute = alarm_data.get("time", "08:00").split(":")
    days_ja = [DAY_MAP_EN_TO_JA[day] for day in alarm_data.get("days", [])]

    # ★ prompt -> flash_prompt_template にキーを修正
    return (gr.update(value="アラーム更新"), alarm_data.get("theme", ""), alarm_data.get("flash_prompt_template", ""),
            alarm_data.get("character", ""), days_ja, hour, minute, alarm_id)


def toggle_selected_alarms_status(selected_ids: list[str], new_status: bool): # Changed List[str] to list[str]
    """選択されたアラームの有効/無効を切り替える。"""
    if not selected_ids:
        gr.Warning("操作するアラームが選択されていません。")
        return render_alarms_as_dataframe()

    for alarm_id in selected_ids:
        # ★ update_alarm を正しく使用
        alarm_manager.update_alarm(alarm_id, {"enabled": new_status})

    status_text = "有効化" if new_status else "無効化"
    gr.Info(f"{len(selected_ids)}件のアラームを{status_text}しました。")
    return render_alarms_as_dataframe()

def handle_delete_selected_alarms(selected_ids: list[str]): # Changed List[str] to list[str]
    """選択されたアラームを削除する。"""
    if not selected_ids:
        gr.Warning("削除するアラームが選択されていません。")
        return render_alarms_as_dataframe()

    count = 0
    for alarm_id in selected_ids:
        if alarm_manager.delete_alarm(alarm_id):
            count += 1

    gr.Info(f"{count}件のアラームを削除しました。")
    return render_alarms_as_dataframe()


def handle_add_or_update_alarm(editing_alarm_id, hour, minute, character, theme, flash_prompt, days_ja):
    """アラームの追加または更新を行う。"""
    if not character:
        gr.Warning("キャラクターを選択してください。")
        # 戻り値のタプルの要素数をUIのoutputsに合わせる
        return render_alarms_as_dataframe(), render_alarms_as_dataframe(), "アラーム追加", theme, flash_prompt, character, days_ja, hour, minute, editing_alarm_id

    if not theme or not theme.strip():
        gr.Warning("テーマを入力してください。")
        return render_alarms_as_dataframe(), render_alarms_as_dataframe(), "アラーム追加", theme, flash_prompt, character, days_ja, hour, minute, editing_alarm_id

    # ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
    # ★★★ ここが追加と更新のロジックを正しく分岐させる修正箇所です ★★★
    # ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★

    if editing_alarm_id:  # 更新の場合
        days_en = [DAY_MAP_JA_TO_EN.get(day) for day in days_ja if DAY_MAP_JA_TO_EN.get(day)]
        update_data = {
            "time": f"{hour}:{minute}",
            "character": character,
            "theme": theme,
            "flash_prompt_template": flash_prompt,
            "days": days_en,
        }
        alarm_manager.update_alarm(editing_alarm_id, update_data)
        gr.Info(f"アラーム「{theme}」を更新しました。")
    else:  # 新規追加の場合
        alarm_manager.add_alarm(hour, minute, character, theme, flash_prompt, days_ja)
        gr.Info(f"アラーム「{theme}」を追加しました。")

    # フォームをリセットするための値
    new_df = render_alarms_as_dataframe()
    all_chars = character_manager.get_character_list()
    default_char = all_chars[0] if all_chars else None

    return (new_df, new_df, "アラーム追加", "", "", default_char,
            list(DAY_MAP_JA_TO_EN.values()), "08", "00", None)


def update_model_state(new_model_name: str):
    config_manager.save_config("last_model", new_model_name)
    gr.Info(f"AIモデルを「{new_model_name}」に変更しました。")
    return new_model_name

def update_api_key_state(new_api_key_name: str):
    if new_api_key_name in config_manager.API_KEYS:
        configure_google_api(new_api_key_name)
        config_manager.save_config("last_api_key_name", new_api_key_name)
        gr.Info(f"APIキーを「{new_api_key_name}」に変更しました。")
    else:
        gr.Warning("無効なAPIキー名です。")
    return new_api_key_name

def update_timestamp_state(add_timestamp_enabled: bool):
    config_manager.save_config("add_timestamp_to_log", add_timestamp_enabled)
    status = "有効" if add_timestamp_enabled else "無効"
    gr.Info(f"タイムスタンプ追加を{status}にしました。")

def update_send_thoughts_state(send_thoughts_enabled: bool):
    config_manager.save_config("send_thoughts_to_api", send_thoughts_enabled)
    status = "送信する" if send_thoughts_enabled else "送信しない"
    gr.Info(f"思考過程のAPI送信を「{status}」設定にしました。")
    return send_thoughts_enabled

def update_api_history_limit_state(new_limit_option_value: str):
    # new_limit_option_value は "全ログ" や "直近3往復" のような表示名
    # これを内部的なキー (e.g., "all", "last3") に変換する必要がある
    for key, value in config_manager.API_HISTORY_LIMIT_OPTIONS.items():
        if value == new_limit_option_value:
            internal_key = key
            break
    else: # 見つからなかった場合 (ありえないはずだが念のため)
        internal_key = "all"
        gr.Warning(f"不明な履歴制限オプション: {new_limit_option_value}。デフォルト値を使用します。")

    config_manager.save_config("api_history_limit_option", internal_key)
    gr.Info(f"APIへの履歴送信設定を「{new_limit_option_value}」に変更しました。")
    return internal_key


    # ui_handlers.py

    # (Ensure gradio as gr is imported at the top of the file if not already)
    # import gradio as gr
    # (Ensure traceback is imported at the top if other functions use it,
    # otherwise it's not strictly needed here as the exception is passed)

    def handle_save_log_button_click(character_name: str, log_content: str):
        """ログエディタの内容を保存する。utils.save_log_fileを正しく呼び出す。"""
        if not character_name:
            gr.Warning("キャラクターが選択されていません。")
            return

        try:
            from utils import save_log_file # Function-scoped import
            save_log_file(character_name, log_content)
            gr.Info(f"{character_name}さんのログを保存しました。")
        except Exception as e:
            gr.Error(f"ログの保存中にエラーが発生しました: {e}")

def reload_chat_log(character_name: str):
    if not character_name:
        gr.Warning("キャラクターが選択されていません。")
        return [], ""
    log_file_path, _, _, _ = get_character_files_paths(character_name)
    chat_history = []
    log_content = ""
    if os.path.exists(log_file_path):
        chat_history = format_history_for_gradio(load_chat_log(log_file_path, character_name)[-(config_manager.HISTORY_LIMIT * 2):])
        try:
            with open(log_file_path, "r", encoding="utf-8") as f:
                log_content = f.read()
        except Exception as e:
            log_content = f"ログファイルの読み込みに失敗しました: {e}"
            gr.Error(log_content)
    else:
        gr.Warning(f"{character_name}さんのログファイルが見つかりません。")

    return chat_history, log_content


def handle_timer_submission(timer_type, duration, work_time, break_time, cycles, char_name, work_theme, break_theme, api_key_name, webhook_url, normal_theme):
    if not char_name:
        return "キャラクターを選択してください。"
    if not api_key_name:
        return "APIキーを選択してください。"

    # シングルトンインスタンスを取得
    timer = UnifiedTimer.get_instance()
    # 既存のタイマーが動いていれば停止する
    timer.stop()

    # タイマーの共通プロパティを設定
    timer.set_properties(
        character_name=char_name,
        api_key_name=api_key_name,
        webhook_url=webhook_url
    )

    status_message = ""
    if timer_type == "通常タイマー":
        if not duration or duration <= 0:
            return "タイマー時間を正しく設定してください。"
        theme = normal_theme if normal_theme and normal_theme.strip() else "タイマー終了！"
        timer.set_normal_timer(duration * 60, theme)
        status_message = f"{char_name}さんによる「{theme}」タイマーを{duration}分でセットしました。"

    elif timer_type == "ポモドーロタイマー":
        if not work_time or work_time <=0 or not break_time or break_time <=0 or not cycles or cycles <=0:
             return "ポモドーロタイマーの各時間を正しく設定してください。"
        work_t = work_theme if work_theme and work_theme.strip() else "作業終了！"
        break_t = break_theme if break_theme and break_theme.strip() else "休憩終了！"
        timer.set_pomodoro(work_time * 60, break_time * 60, cycles, work_t, break_t)
        status_message = f"{char_name}さんによるポモドーロタイマーをセットしました (作業{work_time}分, 休憩{break_time}分, {cycles}サイクル)。"

    else:
        return "無効なタイマー種別です。"

    # 設定した内容でタイマーを開始
    timer.start()
    gr.Info(status_message)
    return status_message

# アプリケーション起動時に既存のタイマーインスタンスがあれば停止する
def stop_existing_timer_on_startup():
    # get_instanceは初回呼び出し時にインスタンスを作成するだけ
    timer = UnifiedTimer.get_instance()
    if timer.is_running():
        timer.stop()
        print("アプリケーション再起動のため、既存のタイマーを停止しました。")

stop_existing_timer_on_startup()
