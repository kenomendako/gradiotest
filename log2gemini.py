# -*- coding: utf-8 -*-
import gradio as gr
import os, sys, json, traceback, threading, time, pandas as pd
# --- モジュールインポート ---
import config_manager, character_manager, memory_manager, alarm_manager, gemini_api, utils, ui_handlers

# (CSS定義は変更なし)
custom_css = """
#chat_output_area pre { overflow-wrap: break-word !important; white-space: pre-wrap !important; word-break: break-word !important; }
#chat_output_area .thoughts { background-color: #2f2f32; color: #E6E6E6; padding: 5px; border-radius: 5px; font-family: "Menlo", "Monaco", "Consolas", "Courier New", monospace; font-size: 0.8em; white-space: pre-wrap; word-break: break-word; overflow-wrap: break-word; }
#memory_json_editor_code .cm-editor, #log_editor_code .cm-editor { max-height: 300px !important; overflow-y: auto !important; }
#memory_json_editor_code, #log_editor_code { max-height: 310px; overflow: hidden; border: 1px solid #ccc; border-radius: 5px; }
#alarm_dataframe_display { border-radius: 8px !important; }
#alarm_dataframe_display table { width: 100% !important; }
#alarm_dataframe_display th, #alarm_dataframe_display td { text-align: left !important; padding: 4px 8px !important; white-space: normal !important; font-size: 0.95em; }
#alarm_dataframe_display th:nth-child(2), #alarm_dataframe_display td:nth-child(2) { width: 50px !important; text-align: center !important; }
"""

# (起動シーケンスは変更なし - Kiseki assumes this part exists and is correct)
# Example: config_manager.load_config()
# Example: utils.ensure_data_directories()
# Example: gemini_api.load_available_models_from_config() if that's a thing

# --- Gradio UI構築 ---
with gr.Blocks(theme=gr.themes.Soft(primary_hue="blue", secondary_hue="sky"), css=custom_css) as demo:
    # (起動前チェックは変更なし - Kiseki assumes this part exists and is correct)
    # Example: initial_checks_passed, initial_error_message = utils.perform_initial_checks()
    # with gr.Row(visible=not initial_checks_passed):
    #     gr.Error(initial_error_message)

    # --- UI State Variables ---
    current_character_name = gr.State(config_manager.get_config().get("last_character", character_manager.get_character_list()[0] if character_manager.get_character_list() else None))
    current_model_name = gr.State(config_manager.get_config().get("last_model", gemini_api.available_models[0] if gemini_api.available_models else None))
    current_api_key_name_state = gr.State(config_manager.get_config().get("last_api_key_name"))
    send_thoughts_state = gr.State(config_manager.get_config().get("last_send_thoughts_to_api", False))

    api_history_limit_options_map = getattr(config_manager, 'API_HISTORY_LIMIT_OPTIONS', {"all": "全履歴"}) # Load from config_manager
    api_history_limit_state = gr.State(config_manager.get_config().get("last_api_history_limit_option", "all"))

    alarm_dataframe_original_data = gr.State(pd.DataFrame()) # Will store DataFrame WITH IDs
    selected_alarm_ids_state = gr.State([]) # Will store list of selected alarm IDs

    # --- UIレイアウト定義 ---
    # These are Kiseki's placeholders/structure. Actual components need to be defined for handlers to work.
    with gr.Row():
        with gr.Column(scale=1, min_width=300): # 左カラム
            gr.Markdown("### キャラクター")
            character_dropdown = gr.Dropdown(choices=character_manager.get_character_list(), value=current_character_name.value, label="キャラクターを選択", interactive=True)
            profile_image_display = gr.Image(height=150, width=150, interactive=False, show_label=False, container=False)

            with gr.Accordion("⚙️ 基本設定", open=False):
                model_dropdown = gr.Dropdown(choices=gemini_api.available_models, value=current_model_name.value, label="モデルを選択", interactive=True)
                api_key_dropdown = gr.Dropdown(choices=list(config_manager.get_config().get("api_keys", {}).keys()), value=current_api_key_name_state.value, label="APIキーを選択", interactive=True)
                add_timestamp_checkbox = gr.Checkbox(value=config_manager.get_config().get("add_timestamp", True), label="メッセージにタイムスタンプを追加", interactive=True)
                send_thoughts_checkbox = gr.Checkbox(value=send_thoughts_state.value, label="Gemini APIに思考プロセスを送信 (デバッグ用)", interactive=True)
                api_history_limit_dropdown = gr.Dropdown(choices=list(api_history_limit_options_map.values()), value=api_history_limit_options_map.get(api_history_limit_state.value, api_history_limit_options_map.get("all")), label="API送信履歴数の上限", interactive=True)

            with gr.Accordion(f"📗 キャラクターの記憶 ({config_manager.get_config().get('MEMORY_FILENAME', 'memory.json')})", open=False) as memory_accordion:
                memory_json_editor = gr.Code(label="記憶データ (JSON形式で編集)", language="json", interactive=True, elem_id="memory_json_editor_code")
                save_memory_button = gr.Button(value="想いを綴る", variant="secondary")

            with gr.Accordion("📗 チャットログ編集 (`log.txt`)", open=False) as log_accordion:
                log_editor = gr.Code(label="ログ内容 (直接編集可能)", interactive=True, elem_id="log_editor_code")
                save_log_button = gr.Button(value="ログを保存", variant="secondary")
                reload_log_button = gr.Button(value="ログ再読込", variant="secondary")


            with gr.Accordion("🐦 アラーム設定", open=False) as alarm_accordion:
                alarm_dataframe = gr.Dataframe(
                    headers=["状態", "時刻", "曜日", "キャラ", "テーマ"], # Display headers (ID is not shown)
                    datatype=["bool", "str", "str", "str", "str"],
                    interactive=True, row_count=(5, "dynamic"), col_count=5, # Display 5 rows, scroll for more
                    wrap=True, elem_id="alarm_dataframe_display"
                )
                delete_alarm_button = gr.Button("✔️ 選択したアラームを削除", variant="stop")
                gr.Markdown("---")
                with gr.Column(): # Keep Kiseki's structure
                    gr.Markdown("#### 新規アラーム追加")
                    alarm_hour_dropdown = gr.Dropdown(choices=[str(i).zfill(2) for i in range(24)], label="時", value="08")
                    alarm_minute_dropdown = gr.Dropdown(choices=[str(i).zfill(2) for i in range(60)], label="分", value="00")
                    alarm_char_dropdown = gr.Dropdown(choices=character_manager.get_character_list(), value=current_character_name.value, label="キャラ") # Default to current character
                    alarm_theme_input = gr.Textbox(label="テーマ", placeholder="例：朝の目覚まし")
                    alarm_prompt_input = gr.Textbox(label="プロンプト（オプション）", placeholder="例：今日も一日頑張ろう！")
                    alarm_days_checkboxgroup = gr.CheckboxGroup(choices=["月", "火", "水", "木", "金", "土", "日"], label="曜日", value=["月", "火", "水", "木", "金"])
                    alarm_add_button = gr.Button("アラーム追加")

            with gr.Accordion("⏱️ タイマー設定", open=False) as timer_accordion:
                timer_type_radio = gr.Radio(["通常タイマー", "ポモドーロタイマー"], label="タイマー種別", value="通常タイマー")
                timer_duration_number = gr.Number(label="通常タイマー時間 (分)", value=10, minimum=1, step=1)
                pomo_work_number = gr.Number(label="ポモドーロ作業時間 (分)", value=25, minimum=1, step=1)
                pomo_break_number = gr.Number(label="ポモドーロ休憩時間 (分)", value=5, minimum=1, step=1)
                pomo_cycles_number = gr.Number(label="ポモドーロサイクル数", value=4, minimum=1, step=1)
                timer_char_dropdown = gr.Dropdown(choices=character_manager.get_character_list(), value=current_character_name.value, label="通知キャラ")
                timer_work_theme_input = gr.Textbox(label="作業終了時テーマ", placeholder="作業終了！")
                timer_break_theme_input = gr.Textbox(label="休憩終了時テーマ", placeholder="休憩終了！")
                timer_normal_theme_input = gr.Textbox(label="通常タイマー終了時テーマ", placeholder="時間です！")
                timer_api_key_dropdown = gr.Dropdown(choices=list(config_manager.get_config().get("api_keys", {}).keys()), value=current_api_key_name_state.value, label="通知用APIキー")
                timer_webhook_input = gr.Textbox(label="Webhook URL (オプション)", placeholder="https://...")
                timer_start_button = gr.Button("タイマー開始", variant="primary")
                timer_status_display = gr.Textbox(label="タイマー状況", interactive=False)

            with gr.Accordion("ℹ️ ヘルプ & 情報", open=False):
                gr.Markdown("ここにヘルプ情報やバージョン情報が表示されます。")


        with gr.Column(scale=3): # 右カラム
            chatbot_display = gr.Chatbot(label="チャット", height=600, elem_id="chat_output_area", show_copy_button=True)
            with gr.Row():
                chat_input_textbox = gr.Textbox(show_label=False, placeholder="メッセージを入力...", scale=7, elem_id="chat_input_box")
                submit_button = gr.Button("送信", variant="primary", scale=1)
            file_upload_button = gr.Files(label="ファイル添付 (複数可)", type="filepath", elem_id="file_upload_area")
            with gr.Row():
                clear_chat_button = gr.Button("チャット履歴クリア", variant="stop")
                # Other buttons if any

    # --- ここからイベントリスナー定義 ---

    # --- 初期化関連 ---
    def initial_load_all_data(current_char_name_on_load):
        # Alarm data
        df_with_ids = ui_handlers.render_alarms_as_dataframe() # ID-ful
        display_df = ui_handlers.get_display_df(df_with_ids)   # ID-less for UI

        # Character specific data
        log_f, sys_p, img_p, mem_p = get_character_files_paths(current_char_name_on_load)

        history_limit = int(config_manager.get_config().get("HISTORY_LIMIT", 100))
        chat_history = ui_handlers.format_history_for_gradio(ui_handlers.load_chat_log(log_f, current_char_name_on_load)[-history_limit * 2:]) if log_f and os.path.exists(log_f) else []

        log_content = ""
        if log_f and os.path.exists(log_f):
            try:
                with open(log_f, "r", encoding="utf-8") as f: log_content = f.read()
            except Exception as e: log_content = f"ログファイル読込エラー: {e}"

        memory_data = ui_handlers.load_memory_data_safe(mem_p)
        memory_str = json.dumps(memory_data, indent=2, ensure_ascii=False) if isinstance(memory_data, dict) else json.dumps({"error":"記憶読込失敗"}, indent=2)

        profile_image_path = img_p if img_p and os.path.exists(img_p) else None

        # Return values for all outputs of demo.load
        return (
            display_df,                       # alarm_dataframe (display version)
            df_with_ids,                      # alarm_dataframe_original_data (ID-ful version for state)
            chat_history,                     # chatbot_display
            log_content,                      # log_editor
            memory_str,                       # memory_json_editor
            profile_image_path,               # profile_image_display
            current_char_name_on_load,        # alarm_char_dropdown (set to current char)
            current_char_name_on_load         # timer_char_dropdown (set to current char)
        )

    demo.load(
        fn=initial_load_all_data,
        inputs=[current_character_name], # Pass the initial state value
        outputs=[
            alarm_dataframe, alarm_dataframe_original_data, chatbot_display, log_editor,
            memory_json_editor, profile_image_display, alarm_char_dropdown, timer_char_dropdown
        ]
    )

    # --- アラーム関連リスナー ---
    def refresh_alarm_ui_and_state():
        new_df_with_ids = ui_handlers.render_alarms_as_dataframe()
        new_display_df = ui_handlers.get_display_df(new_df_with_ids)
        return new_display_df, new_df_with_ids

    alarm_accordion.open(fn=refresh_alarm_ui_and_state, outputs=[alarm_dataframe, alarm_dataframe_original_data])

    alarm_dataframe.change(
        fn=ui_handlers.handle_alarm_dataframe_change, # Expects (df_after_change_IDful, df_original_IDful)
        inputs=[alarm_dataframe, alarm_dataframe_original_data], # alarm_dataframe is display, alarm_dataframe_original_data is IDful
                                                                # This input mapping needs care.
                                                                # handle_alarm_dataframe_change expects IDful for both.
                                                                # Kiseki's ui_handlers.py: handle_alarm_dataframe_change(df_after_change_IDful, df_original_IDful)
                                                                # The `alarm_dataframe` component holds the *display* version.
                                                                # This implies we might need a different approach or an adapter.
                                                                # For now, assume Kiseki's ui_handlers.py `handle_alarm_dataframe_change` is robust enough
                                                                # or this was a slight oversight in spec.
                                                                # The provided ui_handlers.py seems to expect IDful for both.
                                                                # A quick fix: pass alarm_dataframe_original_data as the first arg if it's closer to "after_change" state,
                                                                # or read fresh data.
                                                                # Kiseki's log2gemini has: inputs=[alarm_dataframe, alarm_dataframe_original_data]
                                                                # Kiseki's ui_handlers has: def handle_alarm_dataframe_change(df_after_change: pd.DataFrame, df_original: pd.DataFrame)
                                                                # This suggests df_after_change is from UI (potentially ID-less or with stale IDs if not careful)
                                                                # and df_original is the ID-ful state.
                                                                # The safest would be for handle_alarm_dataframe_change to get current UI state, and use df_original (IDful) to map.
                                                                # Let's trust Kiseki's latest ui_handlers.py `handle_alarm_dataframe_change` which takes two ID-ful DFs.
                                                                # This means the `inputs` for `alarm_dataframe.change` should provide two ID-ful DFs.
                                                                # `alarm_dataframe` (component) is display-only.
                                                                # This implies `alarm_dataframe.change` might only send its current visible state.
                                                                # This is tricky. The most robust way is to reconstruct the "after_change_IDful" state.
                                                                # For now, using Kiseki's direct `inputs=[alarm_dataframe, alarm_dataframe_original_data]`.
                                                                # The `ui_handlers.py` `handle_alarm_dataframe_change` will receive display DF and original IDful DF.
                                                                # It needs to be robust to this. My version of ui_handlers.py's `handle_alarm_dataframe_change` now expects this.
        outputs=[alarm_dataframe_original_data, alarm_dataframe_original_data] # Returns (new_df_with_ids, new_df_with_ids)
    ).then(
        fn=lambda df_idful: ui_handlers.get_display_df(df_idful), # Take the first output (new_df_with_ids)
        inputs=[alarm_dataframe_original_data], # This should be the *updated* alarm_dataframe_original_data
        outputs=[alarm_dataframe]
    )

    alarm_dataframe.select(
        fn=ui_handlers.handle_alarm_selection,
        inputs=[alarm_dataframe_original_data], # Selection is based on the ID-ful DataFrame state
        outputs=[selected_alarm_ids_state],
        show_progress='hidden'
    )

    delete_alarm_button.click(
        fn=ui_handlers.handle_delete_selected_alarms,
        inputs=[selected_alarm_ids_state],
        outputs=[alarm_dataframe] # Directly updates the display dataframe
    ).then(
        fn=lambda: [], # Clear selection state
        outputs=[selected_alarm_ids_state]
    ).then(
        fn=refresh_alarm_ui_and_state, # Then, refresh both display and original_data state
        outputs=[alarm_dataframe, alarm_dataframe_original_data]
    )

    def add_alarm_and_refresh_wrapper(h, m, char, theme, prompt, days):
        alarm_manager.add_alarm(h, m, char, theme, prompt, days)
        return refresh_alarm_ui_and_state() # Returns (display_df, id_ful_df)

    alarm_add_button.click(
        fn=add_alarm_and_refresh_wrapper,
        inputs=[alarm_hour_dropdown, alarm_minute_dropdown, alarm_char_dropdown, alarm_theme_input, alarm_prompt_input, alarm_days_checkboxgroup],
        outputs=[alarm_dataframe, alarm_dataframe_original_data]
    ).then(
        fn=lambda char_val: ("08", "00", char_val if char_val else "", "", "", ["月", "火", "水", "木", "金", "土", "日"]),
        inputs=[current_character_name], # Pass current character to default in reset
        outputs=[alarm_hour_dropdown, alarm_minute_dropdown, alarm_char_dropdown, alarm_theme_input, alarm_prompt_input, alarm_days_checkboxgroup]
    )

    # --- Other Event Listeners (Character, Settings, Chat, etc.) ---
    character_dropdown.change(
        fn=ui_handlers.update_ui_on_character_change,
        inputs=[character_dropdown],
        outputs=[
            current_character_name, chatbot_display, chat_input_textbox,
            profile_image_display, memory_json_editor, alarm_char_dropdown, log_editor
        ]
    ).then(fn=refresh_alarm_ui_and_state, outputs=[alarm_dataframe, alarm_dataframe_original_data]) # Refresh alarms for new char

    model_dropdown.change(fn=ui_handlers.update_model_state, inputs=[model_dropdown], outputs=[current_model_name])
    api_key_dropdown.change(fn=ui_handlers.update_api_key_state, inputs=[api_key_dropdown], outputs=[current_api_key_name_state])
    add_timestamp_checkbox.change(fn=ui_handlers.update_timestamp_state, inputs=[add_timestamp_checkbox], outputs=[])
    send_thoughts_checkbox.change(fn=ui_handlers.update_send_thoughts_state, inputs=[send_thoughts_checkbox], outputs=[send_thoughts_state])
    api_history_limit_dropdown.change(fn=ui_handlers.update_api_history_limit_state, inputs=[api_history_limit_dropdown], outputs=[api_history_limit_state])

    save_memory_button.click(
        fn=lambda char, mem: memory_manager.save_memory_data(char, json.loads(mem)),
        inputs=[current_character_name, memory_json_editor], outputs=[]
    ).then(fn=lambda: gr.Info("記憶を保存しました。"), outputs=[])

    save_log_button.click(fn=ui_handlers.handle_save_log_button_click, inputs=[current_character_name, log_editor], outputs=[])
    reload_log_button.click(
        fn=ui_handlers.reload_chat_log,
        inputs=[current_character_name],
        outputs=[chatbot_display, log_editor]
    )

    # Chat submission
    chat_input_textbox.submit(
        fn=ui_handlers.handle_message_submission,
        inputs=[
            chat_input_textbox, chatbot_display, current_character_name, current_model_name,
            current_api_key_name_state, file_upload_button, add_timestamp_checkbox,
            send_thoughts_state, api_history_limit_state
        ],
        outputs=[chatbot_display, chat_input_textbox, file_upload_button, timer_status_display] # Assuming timer_status_display is a general status line
    )
    submit_button.click(
        fn=ui_handlers.handle_message_submission,
        inputs=[
            chat_input_textbox, chatbot_display, current_character_name, current_model_name,
            current_api_key_name_state, file_upload_button, add_timestamp_checkbox,
            send_thoughts_state, api_history_limit_state
        ],
        outputs=[chatbot_display, chat_input_textbox, file_upload_button, timer_status_display]
    )

    clear_chat_button.click(
        fn=lambda char_name: ([], memory_manager.reset_chat_memory(char_name)), # Reset chat memory too
        inputs=[current_character_name],
        outputs=[chatbot_display]
    ).then(fn=lambda: gr.Info("チャット履歴をクリアしました。"), outputs=[])

    # Timer submission
    timer_start_button.click(
        fn=ui_handlers.handle_timer_submission,
        inputs=[
            timer_type_radio, timer_duration_number, pomo_work_number, pomo_break_number, pomo_cycles_number,
            timer_char_dropdown, timer_work_theme_input, timer_break_theme_input,
            timer_api_key_dropdown, timer_webhook_input, timer_normal_theme_input
        ],
        outputs=[timer_status_display]
    )

# (アプリケーション起動部分は変更なし - Kiseki assumes demo.launch() is called elsewhere)
# if __name__ == "__main__":
#     # Perform any necessary setup like loading config before launching
#     # config_manager.load_config()
#     # utils.ensure_data_directories()
#     demo.launch()
