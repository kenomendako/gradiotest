# -*- coding: utf-8 -*-
import gradio as gr
import os
import sys
import json
import traceback
import threading
import time
import pandas as pd

# --- モジュールインポート ---
import config_manager
import character_manager
import memory_manager
import alarm_manager
import gemini_api
import utils
import ui_handlers # ui_handlers.py の関数を呼び出す
# ui_handlersから必要な関数を明示的にインポート
from ui_handlers import (
    # アラーム関連
    render_alarms_as_dataframe,
    handle_alarm_dataframe_change,
    handle_alarm_selection, # Kiseki: log2gemini.py側のラッパーでselected_rowsを処理するため、これは直接使わない可能性あり
    handle_delete_selected_alarms,
    # タイマー関連
    handle_timer_submission,
    # キャラクター・設定変更関連
    update_ui_on_character_change,
    update_model_state,
    update_api_key_state,
    update_timestamp_state,
    update_send_thoughts_state,
    update_api_history_limit_state,
    # ログ・記憶関連
    handle_save_log_button_click,
    reload_chat_log,
    # メッセージ送受信
    handle_message_submission
)

# --- 定数 ---
HISTORY_LIMIT = config_manager.HISTORY_LIMIT

# --- CSS ---
custom_css = """
#chat_output_area pre { overflow-wrap: break-word !important; white-space: pre-wrap !important; word-break: break-word !important; }
#chat_output_area .thoughts { background-color: #2f2f32; color: #E6E6E6; padding: 5px; border-radius: 5px; font-family: "Menlo", "Monaco", "Consolas", "Courier New", monospace; font-size: 0.8em; white-space: pre-wrap; word-break: break-word; overflow-wrap: break-word; }
#chat_output_area .thoughts pre { white-space: pre-wrap !important; word-break: break-word !important; overflow-wrap: break-word !important; }
#chat_output_area .thoughts pre code { white-space: pre-wrap !important; word-break: break-word !important; overflow-wrap: break-word !important; display: block !important; width: 100% !important; }
#memory_json_editor_code .cm-editor, #log_editor_code .cm-editor { max-height: 300px !important; overflow-y: auto !important; }
#memory_json_editor_code, #log_editor_code { max-height: 310px; overflow: hidden; border: 1px solid #ccc; border-radius: 5px; }
#help_accordion code { background-color: #eee; padding: 2px 4px; border-radius: 3px; font-size: 0.9em; }
.time-dropdown-container label { margin-bottom: 2px !important; font-size: 0.9em; }
.time-dropdown-container > div { margin-bottom: 5px !important; }
#alarm_dataframe_display .gr-checkbox label { margin-bottom: 0 !important; }
#alarm_dataframe_display { border-radius: 8px !important; }
#alarm_dataframe_display table { width: 100% !important; }
#alarm_dataframe_display th, #alarm_dataframe_display td { text-align: left !important; padding: 4px 8px !important; font-size: 0.95em; }
#alarm_dataframe_display th:nth-child(1), #alarm_dataframe_display td:nth-child(1) { width: 60px !important; text-align: center !important; } /* 状態 */
#alarm_dataframe_display th:nth-child(2), #alarm_dataframe_display td:nth-child(2) { width: 70px !important; } /* 時刻 */
#alarm_dataframe_display th:nth-child(3), #alarm_dataframe_display td:nth-child(3) { width: 110px !important; } /* 曜日 */
#alarm_dataframe_display th:nth-child(4), #alarm_dataframe_display td:nth-child(4) { width: 130px !important; } /* キャラ */
#alarm_dataframe_display th:nth-child(5), #alarm_dataframe_display td:nth-child(5) { width: auto !important; } /* テーマ */
"""

# --- 起動シーケンス ---
print("設定ファイルを読み込んでいます...")
try:
    config_manager.load_config()
except Exception as e:
    print(f"設定ファイルの読み込み中に致命的なエラーが発生しました: {e}\n{traceback.format_exc()}")
    sys.exit("設定ファイルの読み込みエラーにより終了。")

initial_api_key_configured = False
if config_manager.initial_api_key_name_global:
    initial_api_key_configured, init_api_error = gemini_api.configure_google_api(config_manager.initial_api_key_name_global)
    if not initial_api_key_configured: print(f"\n!!! 警告: 初期APIキー '{config_manager.initial_api_key_name_global}' 設定失敗: {init_api_error} !!!")
    else: print(f"初期APIキー '{config_manager.initial_api_key_name_global}' 設定成功。")
elif not config_manager.API_KEYS: print(f"\n!!! 警告: {config_manager.CONFIG_FILE} にAPIキー未設定 ('api_keys')。!!!")
else: print(f"\n!!! 警告: {config_manager.CONFIG_FILE} に有効なデフォルトAPIキー名なし。!!!")

print("アラームデータを読み込んでいます...")
alarm_manager.load_alarms()

# --- Gradio UI構築 ---
with gr.Blocks(theme=gr.themes.Soft(primary_hue="blue", secondary_hue="sky"), css=custom_css) as demo:
    character_list_on_startup = character_manager.get_character_list()

    startup_ready = all([
        character_list_on_startup,
        config_manager.initial_character_global and config_manager.initial_character_global in character_list_on_startup,
        config_manager.AVAILABLE_MODELS_GLOBAL and config_manager.initial_model_global in config_manager.AVAILABLE_MODELS_GLOBAL,
        config_manager.API_KEYS,
        config_manager.initial_api_history_limit_option_global in config_manager.API_HISTORY_LIMIT_OPTIONS,
        config_manager.initial_alarm_model_global,
        isinstance(config_manager.initial_alarm_api_history_turns_global, int)
    ])

    if not startup_ready:
        error_messages = []
        if not character_list_on_startup: error_messages.append(f"キャラクターが見つかりません (`{config_manager.CHARACTERS_DIR}`フォルダ確認)。")
        if not (config_manager.initial_character_global and config_manager.initial_character_global in character_list_on_startup): error_messages.append(f"`config.json` の `last_character` ('{config_manager.initial_character_global}') が無効。")
        if not (config_manager.AVAILABLE_MODELS_GLOBAL and config_manager.initial_model_global in config_manager.AVAILABLE_MODELS_GLOBAL): error_messages.append(f"`config.json` の `last_model` ('{config_manager.initial_model_global}') が無効か、`available_models` に含まれていません。")
        if not config_manager.API_KEYS: error_messages.append("`config.json` に `api_keys` が設定されていません。")
        if not (config_manager.initial_api_history_limit_option_global in config_manager.API_HISTORY_LIMIT_OPTIONS): error_messages.append(f"`config.json` の `last_api_history_limit_option` ('{config_manager.initial_api_history_limit_option_global}') が無効。")
        if not config_manager.initial_alarm_model_global: error_messages.append("`config.json` に `alarm_model` が設定されていません。")
        if not isinstance(config_manager.initial_alarm_api_history_turns_global, int): error_messages.append("`config.json` の `alarm_api_history_turns` が整数ではありません。")

        full_error_message = "## 起動エラー\nアプリケーションの起動に必要な設定が不足しています。\n以下の設定を確認してください:\n\n" + "\n".join([f"- {msg}" for msg in error_messages]) + f"\n\n詳細はコンソールログおよび `{config_manager.CONFIG_FILE}` を確認してください。\n設定を修正してからアプリケーションを再起動してください。"
        gr.Markdown(full_error_message)
        print(f"\n{'='*40}\n!!! 起動に必要な設定が不足しています !!!\n{'='*40}\n" + "\n".join([f"- {msg}" for msg in error_messages]) + f"\n\n詳細はコンソールログおよび `{config_manager.CONFIG_FILE}` を確認してください。Gradio UIは表示されません。")
    else:
        current_character_name = gr.State(config_manager.initial_character_global)
        current_model_name = gr.State(config_manager.initial_model_global)
        current_api_key_name_state = gr.State(config_manager.initial_api_key_name_global)
        send_thoughts_state = gr.State(config_manager.initial_send_thoughts_to_api_global)
        api_history_limit_state = gr.State(config_manager.initial_api_history_limit_option_global)
        alarm_dataframe_original_data = gr.State(pd.DataFrame(columns=["ID", "状態", "時刻", "曜日", "キャラ", "テーマ"]))
        selected_alarm_ids_state = gr.State([])

        gr.Markdown("# AI Chat with Gradio & Gemini")
        with gr.Row():
            with gr.Column(scale=1, min_width=300): # 左カラム
                gr.Markdown("### キャラクター")
                character_dropdown = gr.Dropdown(choices=character_list_on_startup, value=config_manager.initial_character_global, label="キャラクターを選択", interactive=True)

                # Kiseki: current_character_name を使って初期画像を設定するLambdaに変更
                profile_image_display = gr.Image(
                    value=lambda char_name_state: get_character_files_paths(char_name_state)[2] if char_name_state and get_character_files_paths(char_name_state)[2] and os.path.exists(get_character_files_paths(char_name_state)[2]) else None,
                    inputs=[current_character_name],
                    height=150, width=150, interactive=False, show_label=False, container=False
                )

                with gr.Accordion("⚙️ 基本設定", open=False):
                    model_dropdown = gr.Dropdown(choices=config_manager.AVAILABLE_MODELS_GLOBAL, value=config_manager.initial_model_global, label="使用するAIモデル", interactive=True)
                    api_key_dropdown = gr.Dropdown(choices=list(config_manager.API_KEYS.keys()), value=config_manager.initial_api_key_name_global, label="使用するAPIキー", info=f"{config_manager.CONFIG_FILE}で設定", interactive=True)
                    api_history_limit_dropdown = gr.Dropdown(choices=list(config_manager.API_HISTORY_LIMIT_OPTIONS.values()), value=config_manager.API_HISTORY_LIMIT_OPTIONS.get(config_manager.initial_api_history_limit_option_global), label="APIへの履歴送信 (通常対話)", info="対話時のトークン量を調整", interactive=True)
                    send_thoughts_checkbox = gr.Checkbox(value=config_manager.initial_send_thoughts_to_api_global, label="思考過程をAPIに送信", info="OFFでトークン削減可能", interactive=True)

                with gr.Accordion(f"📗 キャラクターの記憶 ({config_manager.MEMORY_FILENAME})", open=False):
                    # Kiseki: current_character_name を使って初期記憶を設定するLambdaに変更
                    memory_json_editor = gr.Code(
                        value=lambda char_name_state: json.dumps(load_memory_data_safe(get_character_files_paths(char_name_state)[3]), indent=2, ensure_ascii=False) if char_name_state else "{}",
                        inputs=[current_character_name], # Kiseki: inputs追加
                        label="記憶データ (JSON形式で編集)", language="json", interactive=True, elem_id="memory_json_editor_code"
                    )
                    save_memory_button = gr.Button(value="想いを綴る", variant="secondary")

                with gr.Accordion("📗 チャットログ編集 (`log.txt`)", open=False):
                    def load_log_for_editor_wrapper(char_name): # Kiseki: ラッパー関数化
                        if not char_name: return "キャラクターを選択してください。"
                        log_f,_,_,_ = get_character_files_paths(char_name)
                        if log_f and os.path.exists(log_f):
                            try:
                                with open(log_f, "r", encoding="utf-8") as f: return f.read()
                            except Exception as e: return f"ログファイル読込エラー: {e}"
                        return "" if log_f else "ログファイルパス取得不可。"
                    log_editor = gr.Code(label="ログ内容 (直接編集可能)", value=load_log_for_editor_wrapper(config_manager.initial_character_global), interactive=True, elem_id="log_editor_code")
                    save_log_button = gr.Button(value="ログを保存", variant="secondary")

                with gr.Accordion("🐦 アラーム設定", open=False) as alarm_accordion_component:
                    alarm_display_headers = ["状態", "時刻", "曜日", "キャラ", "テーマ"]
                    alarm_dataframe = gr.Dataframe(
                        headers=alarm_display_headers, datatype=["bool", "str", "str", "str", "str"],
                        interactive=True, row_count=(0, "dynamic"), col_count=(len(alarm_display_headers), "fixed"),
                        wrap=True, elem_id="alarm_dataframe_display"
                    )
                    delete_alarm_button = gr.Button("選択したアラームを削除")
                    gr.Markdown("---")
                    with gr.Column(visible=True) as alarm_form_area:
                        gr.Markdown("#### 新規アラーム追加")
                        with gr.Row():
                            alarm_hour_dropdown = gr.Dropdown(label="時", choices=[f"{h:02}" for h in range(24)], value="08", interactive=True, scale=1, elem_classes="time-dropdown-container")
                            alarm_minute_dropdown = gr.Dropdown(label="分", choices=[f"{m:02}" for m in range(60)], value="00", interactive=True, scale=1, elem_classes="time-dropdown-container")
                        alarm_char_dropdown = gr.Dropdown(label="キャラクター", choices=character_list_on_startup, value=config_manager.initial_character_global, interactive=True)
                        alarm_theme_input = gr.Textbox(label="ひとことテーマ（必須）", placeholder="例: 今日も一日頑張ろう！", lines=2)
                        alarm_days_checkboxgroup = gr.CheckboxGroup(label="曜日設定", choices=["月", "火", "水", "木", "金", "土", "日"], value=["月", "火", "水", "木", "金", "土", "日"], interactive=True)
                        alarm_prompt_input = gr.Textbox(label="応答指示書（上級者向け・任意）", info="空欄の場合は上の『ひとことテーマ』を元にAIが応答を考えます。", placeholder="プロンプト内で [キャラクター名] と [テーマ内容] が利用可能です。", lines=3)
                        with gr.Row():
                            alarm_add_button = gr.Button("アラームを追加", variant="primary")
                            alarm_clear_button = gr.Button("入力クリア")

                with gr.Accordion("⏰ タイマー設定", open=False):
                    timer_type_dropdown = gr.Dropdown(label="タイマータイプ", choices=["通常タイマー", "ポモドーロタイマー"], value="通常タイマー", interactive=True)
                    timer_duration_input = gr.Number(label="タイマー時間 (分)", value=1, minimum=0.1, interactive=True, visible=True)
                    normal_timer_theme_input = gr.Textbox(label="通常タイマーのテーマ", placeholder="例: タイマー終了！", lines=2, interactive=True, visible=True)
                    work_duration_input = gr.Number(label="作業時間 (分)", value=25, minimum=0.1, interactive=True, visible=False)
                    break_duration_input = gr.Number(label="休憩時間 (分)", value=5, minimum=0.1, interactive=True, visible=False)
                    cycles_input = gr.Number(label="サイクル数", value=4, minimum=1, step=1, interactive=True, visible=False)
                    work_theme_input = gr.Textbox(label="作業テーマ", placeholder="例: 集中して作業しよう！", lines=2, interactive=True, visible=False)
                    break_theme_input = gr.Textbox(label="休憩テーマ", placeholder="例: リラックスして休憩しよう！", lines=2, interactive=True, visible=False)
                    def update_timer_inputs_visibility(timer_type):
                        is_normal = timer_type == "通常タイマー"
                        return gr.update(visible=is_normal), gr.update(visible=is_normal), gr.update(visible=not is_normal), gr.update(visible=not is_normal), gr.update(visible=not is_normal), gr.update(visible=not is_normal), gr.update(visible=not is_normal)
                    timer_type_dropdown.change(fn=update_timer_inputs_visibility, inputs=[timer_type_dropdown], outputs=[timer_duration_input, normal_timer_theme_input, work_duration_input, break_duration_input, cycles_input, work_theme_input, break_theme_input])
                    timer_character_dropdown = gr.Dropdown(label="キャラクター", choices=character_list_on_startup, value=config_manager.initial_character_global, interactive=True)
                    timer_status_output = gr.Textbox(label="タイマー設定状況", interactive=False, placeholder="ここに設定内容が表示されます。")
                    timer_submit_button = gr.Button("タイマー開始")

                with gr.Accordion("ℹ️ ヘルプ", open=False, elem_id="help_accordion"):
                     gr.Markdown(config_manager.load_help_text())

            with gr.Column(scale=3): # 右カラム
                gr.Markdown(f"### チャット (UI表示: 最新{HISTORY_LIMIT}往復)")
                # Kiseki: current_character_name を使って初期チャット履歴を設定するLambdaに変更
                chatbot = gr.Chatbot(
                    value=lambda char_name_state: format_history_for_gradio(load_chat_log(get_character_files_paths(char_name_state)[0], char_name_state)[-(HISTORY_LIMIT*2):]) if char_name_state and get_character_files_paths(char_name_state)[0] and os.path.exists(get_character_files_paths(char_name_state)[0]) else [],
                    inputs=[current_character_name], # Kiseki: inputs追加
                    elem_id="chat_output_area", label="会話履歴", height=550,
                    show_copy_button=True, bubble_full_width=False, render_markdown=True
                )
                with gr.Row(): add_timestamp_checkbox = gr.Checkbox(label="タイムスタンプ付加", value=config_manager.initial_add_timestamp_global, interactive=True, container=False, scale=1)
                textbox = gr.Textbox(placeholder="メッセージを入力してください", lines=3, show_label=False, scale=8)
                with gr.Column(scale=2, min_width=100):
                    submit_button = gr.Button("送信", variant="primary")
                    reload_button = gr.Button("リロード", variant="secondary")
                with gr.Accordion("ファイルを添付", open=False):
                    file_input = gr.Files(label="最大10個のファイルを添付", file_count="multiple", file_types=['image', 'text', 'video', 'audio', '.pdf', '.json', '.xml', '.md', '.py', '.csv', '.yaml', '.yml'], type="filepath", interactive=True)
                error_box = gr.Textbox(label="エラー通知", value="", visible=False, interactive=False, elem_id="error_box", max_lines=4)

        # --- イベントリスナー定義 ---
        def initial_load_data_wrapper(): # Kiseki: 初期ロード用のラッパー関数
            df = render_alarms_as_dataframe()
            # 初期キャラのプロフ画像、記憶、ログもロード
            char_name = config_manager.initial_character_global
            profile_img = get_character_files_paths(char_name)[2] if char_name and get_character_files_paths(char_name)[2] and os.path.exists(get_character_files_paths(char_name)[2]) else None
            memory_str = json.dumps(load_memory_data_safe(get_character_files_paths(char_name)[3]), indent=2, ensure_ascii=False) if char_name else "{}"
            log_str = load_log_for_editor_wrapper(char_name)
            chat_hist = format_history_for_gradio(load_chat_log(get_character_files_paths(char_name)[0], char_name)[-(HISTORY_LIMIT*2):]) if char_name and get_character_files_paths(char_name)[0] and os.path.exists(get_character_files_paths(char_name)[0]) else []
            return df, df, profile_img, memory_str, log_str, chat_hist

        demo.load(
            fn=initial_load_data_wrapper,
            outputs=[
                alarm_dataframe, alarm_dataframe_original_data,
                profile_image_display, memory_json_editor, log_editor, chatbot
            ]
        )

        alarm_dataframe.change(fn=handle_alarm_dataframe_change, inputs=[alarm_dataframe, alarm_dataframe_original_data], outputs=[alarm_dataframe, alarm_dataframe_original_data])

        # Kiseki: alarm_dataframe.select の fn を ui_handlers.handle_alarm_selection に変更
        alarm_dataframe.select(fn=handle_alarm_selection, inputs=[alarm_dataframe], outputs=[selected_alarm_ids_state], show_progress="hidden")

        def wrapped_delete_alarms(ids_list):
            new_df, cleared_ids = handle_delete_selected_alarms(ids_list)
            return new_df, cleared_ids, new_df
        delete_alarm_button.click(fn=wrapped_delete_alarms, inputs=[selected_alarm_ids_state], outputs=[alarm_dataframe, selected_alarm_ids_state, alarm_dataframe_original_data])

        def wrapped_add_alarm(h, m, char, theme, prompt, days, current_char_for_form): # Kiseki: current_char_for_form追加
            success = alarm_manager.add_alarm(h, m, char, theme, prompt, days)
            if success: gr.Info("アラームを追加しました。") # Kiseki: add_alarmはTrue/Falseを返すのでここでInfo/Error
            else: gr.Error("アラームの追加に失敗しました。")
            new_df = render_alarms_as_dataframe()
            form_reset = ("08", "00", current_char_for_form, "", "", ["月", "火", "水", "木", "金", "土", "日"]) # Kiseki: アラーム用キャラDDは現在の選択キャラでリセット
            return new_df, new_df, *form_reset
        alarm_add_button.click(fn=wrapped_add_alarm,
            inputs=[alarm_hour_dropdown, alarm_minute_dropdown, alarm_char_dropdown, alarm_theme_input, alarm_prompt_input, alarm_days_checkboxgroup, current_character_name], # Kiseki: current_character_nameを渡す
            outputs=[alarm_dataframe, alarm_dataframe_original_data, alarm_hour_dropdown, alarm_minute_dropdown, alarm_char_dropdown, alarm_theme_input, alarm_prompt_input, alarm_days_checkboxgroup])

        alarm_clear_button.click(lambda char_name: ("08", "00", char_name, "", "", ["月", "火", "水", "木", "金", "土", "日"]), inputs=[current_character_name], outputs=[alarm_hour_dropdown, alarm_minute_dropdown, alarm_char_dropdown, alarm_theme_input, alarm_prompt_input, alarm_days_checkboxgroup])

        def wrapped_char_change_for_all_updates(char_name):
            char_state, chat_hist, text_clr, profile_img, mem_json, alarm_char_dd_val, log_edit_text = update_ui_on_character_change(char_name)
            new_alarm_df = render_alarms_as_dataframe()
            # Kiseki: アラーム追加フォームのキャラクターも更新
            return char_state, chat_hist, text_clr, profile_img, mem_json, alarm_char_dd_val, log_edit_text, new_alarm_df, new_alarm_df, char_name
        character_dropdown.change(fn=wrapped_char_change_for_all_updates, inputs=[character_dropdown],
            outputs=[
                current_character_name, chatbot, textbox, profile_image_display,
                memory_json_editor, alarm_char_dropdown, log_editor, # Kiseki: alarm_char_dropdown を update_ui_on_character_change の出力で更新
                alarm_dataframe, alarm_dataframe_original_data,
                alarm_char_dropdown # Kiseki: アラーム追加フォームのドロップダウンも更新するため、再度リスト
            ])

        model_dropdown.change(fn=update_model_state, inputs=[model_dropdown], outputs=[current_model_name])
        api_key_dropdown.change(fn=update_api_key_state, inputs=[api_key_dropdown], outputs=[current_api_key_name_state])
        add_timestamp_checkbox.change(fn=update_timestamp_state, inputs=[add_timestamp_checkbox], outputs=None)
        send_thoughts_checkbox.change(fn=update_send_thoughts_state, inputs=[send_thoughts_checkbox], outputs=[send_thoughts_state])
        api_history_limit_dropdown.change(fn=update_api_history_limit_state, inputs=[api_history_limit_dropdown], outputs=[api_history_limit_state])
        save_memory_button.click(fn=save_memory_data, inputs=[current_character_name, memory_json_editor], outputs=[memory_json_editor]) # Kiseki: memory_managerからsave_memory_dataを直接呼び出し

        save_log_button.click(fn=handle_save_log_button_click, inputs=[current_character_name, log_editor], outputs=None).then(
            fn=reload_chat_log, inputs=[current_character_name], outputs=[chatbot, log_editor])

        timer_submit_button.click(fn=handle_timer_submission,
            inputs=[timer_type_dropdown, timer_duration_input, work_duration_input, break_duration_input, cycles_input, timer_character_dropdown, work_theme_input, break_theme_input, api_key_dropdown, gr.State(config_manager.initial_notification_webhook_url_global), normal_timer_theme_input],
            outputs=[timer_status_output])

        submit_button.click(fn=handle_message_submission,
            inputs=[textbox, chatbot, current_character_name, current_model_name, current_api_key_name_state, file_input, add_timestamp_checkbox, send_thoughts_state, api_history_limit_state],
            outputs=[chatbot, textbox, file_input, error_box])

        def show_error_box_wrapper(err_msg): return gr.update(visible=bool(err_msg), value=err_msg)
        error_box.change(fn=show_error_box_wrapper, inputs=[error_box], outputs=[error_box])

        reload_button.click(fn=reload_chat_log, inputs=[current_character_name], outputs=[chatbot, log_editor])

# --- アプリケーション起動 ---
if __name__ == "__main__":
    if 'startup_ready' not in locals() or not startup_ready:
        print("\n!!! Gradio UIの初期化中にエラーが発生したか、設定が不足しています。起動を中止します。!!!")
        sys.exit("初期化エラーまたは設定不足により終了。")

    print(f"\n{'='*40}\n Gradio アプリケーション起動準備完了 \n{'='*40}")
    print(f"設定ファイル: {os.path.abspath(config_manager.CONFIG_FILE)}")
    print(f"アラーム設定ファイル: {os.path.abspath(config_manager.ALARMS_FILE)}")
    print(f"キャラクターフォルダ: {os.path.abspath(config_manager.CHARACTERS_DIR)}")
    print(f"初期キャラクター: {config_manager.initial_character_global}")
    print(f"初期モデル (通常対話): {config_manager.initial_model_global}")
    print(f"初期APIキー名: {config_manager.initial_api_key_name_global or '未選択（UIで選択要）'}")
    print(f"タイムスタンプ付加 (初期): {config_manager.initial_add_timestamp_global}")
    print(f"思考過程API送信 (初期): {config_manager.initial_send_thoughts_to_api_global}")
    print(f"API履歴制限 (通常対話): {config_manager.API_HISTORY_LIMIT_OPTIONS.get(config_manager.initial_api_history_limit_option_global, '不明')}")
    print(f"{'-'*20} アラーム設定 {'-'*20}")
    print(f"アラーム機能: 有効")
    print(f"  アラーム用モデル: {config_manager.initial_alarm_model_global}")
    print(f"  アラーム用履歴参照: {config_manager.initial_alarm_api_history_turns_global} 往復")
    print(f"  設定済みアラーム件数: {len(alarm_manager.alarms_data_global)}")
    print(f"  Webhook通知URL: {'設定済み' if config_manager.initial_notification_webhook_url_global else '未設定'}")
    print("="*40)

    print("アラームチェック用バックグラウンドスレッドを開始します...")
    if hasattr(alarm_manager, 'start_alarm_scheduler_thread'):
        alarm_manager.start_alarm_scheduler_thread()
    else:
        alarm_scheduler_thread = threading.Thread(target=alarm_manager.schedule_thread_function, daemon=True)
        alarm_scheduler_thread.start()

    print(f"\nGradio アプリケーションを起動します...")
    server_port = int(os.getenv("GRADIO_SERVER_PORT", 7860))
    print(f"ローカルURL: http://127.0.0.1:{server_port}")

    _script_dir = os.path.dirname(os.path.abspath(__file__))
    attachments_path = os.path.join(_script_dir, "chat_attachments")
    os.makedirs(attachments_path, exist_ok=True)

    try:
        demo.queue().launch(server_name="0.0.0.0", server_port=server_port, share=False, allowed_paths=[attachments_path])
    except KeyboardInterrupt:
        print("\nCtrl+C を検出しました。シャットダウン処理を開始します...")
    except Exception as e:
        print(f"\n!!! Gradio アプリケーションの起動中に予期せぬエラーが発生しました !!!\n{traceback.format_exc()}")
    finally:
        print("アラームスケジューラスレッドに停止信号を送信します...")
        if hasattr(alarm_manager, 'stop_alarm_scheduler_thread'):
            alarm_manager.stop_alarm_scheduler_thread()
        elif hasattr(alarm_manager, 'alarm_thread_stop_event') and alarm_manager.alarm_thread_stop_event:
            alarm_manager.alarm_thread_stop_event.set()
        print("Gradio アプリケーションを終了します。")
        sys.exit(0)
```
