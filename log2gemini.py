# log2gemini.py (最終・完全・確定版)
import gradio as gr
import os, sys, json, traceback, threading, time, pandas as pd # Keep existing imports
import config_manager, character_manager, memory_manager, alarm_manager, gemini_api, utils, ui_handlers # Keep existing imports

# --- 起動シーケンス ---
config_manager.load_config()
alarm_manager.load_alarms() # Load alarms after config

character_list_on_startup = character_manager.get_character_list()
if not character_list_on_startup:
    character_manager.ensure_character_files("Default") # Create Default if no chars exist
    character_list_on_startup = ["Default"] # Update list

effective_initial_character = config_manager.initial_character_global
# Validate last used character
if not effective_initial_character or effective_initial_character not in character_list_on_startup:
    new_char = character_list_on_startup[0] if character_list_on_startup else "Default"
    # If list was empty and Default was just created, new_char will be "Default"
    print(f"警告: 最後に使用したキャラクター '{effective_initial_character}' が見つかりません。'{new_char}' で起動します。")
    effective_initial_character = new_char
    config_manager.save_config("last_character", new_char) # Save the valid character

config_manager.initial_character_global = effective_initial_character # Ensure global is updated

# API Key initialization
if config_manager.initial_api_key_name_global and config_manager.initial_api_key_name_global in config_manager.API_KEYS:
    gemini_api.configure_google_api(config_manager.initial_api_key_name_global)
else:
    print("警告: 有効なAPIキーが設定されていません。UIから設定してください。")
    # Potentially select the first available key if none is set or last was invalid
    if config_manager.API_KEYS:
        first_available_key = list(config_manager.API_KEYS.keys())[0]
        gemini_api.configure_google_api(first_available_key)
        config_manager.save_config("last_api_key_name", first_available_key)
        config_manager.initial_api_key_name_global = first_available_key # Update global
        print(f"情報: APIキーを'{first_available_key}'に設定しました。")
    else:
        print("エラー: 利用可能なAPIキーがconfig.jsonに登録されていません。アプリケーションを終了します。")
        # sys.exit("No API keys configured.") # Consider if app should exit

# --- CSS定義 ---
custom_css = """
#chat_output_area pre { overflow-wrap: break-word !important; white-space: pre-wrap !important; word-break: break-word !important; }
#chat_output_area .thoughts_details summary { cursor: pointer; color: #888; font-size: 0.9em; margin-bottom: 3px; }
#chat_output_area .thoughts_details summary:hover { color: #bbb; }
#chat_output_area .thoughts_content { background-color: #2f2f32; color: #E6E6E6; padding: 8px; border-radius: 5px; font-family: "Menlo", "Monaco", "Consolas", "Courier New", monospace; font-size: 0.85em; white-space: pre-wrap; word-break: break-word; overflow-wrap: break-word; border: 1px solid #444; margin-top: 2px;}
#memory_json_editor_code .cm-editor, #log_editor_code .cm-editor { max-height: 300px !important; overflow-y: auto !important; }
#memory_json_editor_code, #log_editor_code { max-height: 310px; overflow: hidden; border: 1px solid #ccc; border-radius: 5px; }
#alarm_dataframe_display { border-radius: 8px !important; }
#alarm_dataframe_display table { width: 100% !important; table-layout: fixed; } /* Added table-layout fixed */
#alarm_dataframe_display th, #alarm_dataframe_display td { text-align: left !important; padding: 4px 8px !important; white-space: normal !important; font-size: 0.95em; overflow-wrap: break-word; word-break: break-all; } /* Added word-break */
#alarm_dataframe_display th:nth-child(1), #alarm_dataframe_display td:nth-child(1) { width: 50px !important; text-align: center !important; } /* Status */
#alarm_dataframe_display th:nth-child(2), #alarm_dataframe_display td:nth-child(2) { width: 60px !important; } /* Time */
#alarm_dataframe_display th:nth-child(4), #alarm_dataframe_display td:nth-child(4) { width: 100px !important; } /* Character */
#selection_feedback { font-size: 0.9em; color: #555; margin-top: 0px; margin-bottom: 5px; padding-left: 5px; }
""" # Corrected CSS for thoughts and alarm table

with gr.Blocks(theme=gr.themes.Soft(primary_hue="blue", secondary_hue="sky"), css=custom_css) as demo:
    # --- UI State定義 ---
    current_character_name = gr.State(effective_initial_character)
    current_model_name = gr.State(config_manager.initial_model_global)
    current_api_key_name_state = gr.State(config_manager.initial_api_key_name_global)
    send_thoughts_state = gr.State(config_manager.initial_send_thoughts_to_api_global)
    api_history_limit_state = gr.State(config_manager.initial_api_history_limit_option_global)

    alarm_dataframe_original_data = gr.State(pd.DataFrame(columns=["id", "状態", "時刻", "曜日", "キャラ", "テーマ"])) # Initialize with columns
    selected_alarm_ids_state = gr.State([])
    editing_alarm_id_state = gr.State(None)

    # --- UIレイアウト定義 ---
    with gr.Row():
        with gr.Column(scale=1, min_width=300):
            profile_image_display = gr.Image(height=150, width=150, interactive=False, show_label=False, container=False, value=None) # Initialize with None
            gr.Markdown("### キャラクター")
            character_dropdown = gr.Dropdown(choices=character_list_on_startup, value=effective_initial_character, label="キャラクターを選択", interactive=True)
            with gr.Row():
                new_character_name_textbox = gr.Textbox(placeholder="新しいキャラクター名", show_label=False, scale=3)
                add_character_button = gr.Button("迎える", variant="secondary", scale=1)

            with gr.Accordion("⚙️ 基本設定", open=False):
                model_dropdown = gr.Dropdown(choices=config_manager.AVAILABLE_MODELS_GLOBAL, value=config_manager.initial_model_global, label="使用するAIモデル", interactive=True)
                api_key_dropdown = gr.Dropdown(choices=list(config_manager.API_KEYS.keys()), value=config_manager.initial_api_key_name_global, label="使用するAPIキー", interactive=True)
                api_history_limit_dropdown = gr.Dropdown(
                    choices=list(config_manager.API_HISTORY_LIMIT_OPTIONS.values()), # Use values for display
                    value=config_manager.API_HISTORY_LIMIT_OPTIONS.get(config_manager.initial_api_history_limit_option_global, config_manager.API_HISTORY_LIMIT_OPTIONS[config_manager.DEFAULT_API_HISTORY_LIMIT_OPTION]), # Get display value
                    label="APIへの履歴送信", interactive=True
                )
                add_timestamp_checkbox = gr.Checkbox(value=config_manager.initial_add_timestamp_global, label="メッセージにタイムスタンプを追加", interactive=True)
                send_thoughts_checkbox = gr.Checkbox(value=config_manager.initial_send_thoughts_to_api_global, label="思考過程をAPIに送信", interactive=True)

            with gr.Accordion("📗 記憶とログの編集", open=False):
                with gr.Tabs():
                    with gr.TabItem("記憶 (memory.json)"):
                        memory_json_editor = gr.Code(label="記憶データ", language="json", interactive=True, elem_id="memory_json_editor_code")
                        save_memory_button = gr.Button(value="想いを綴る", variant="secondary")
                    with gr.TabItem("ログ (log.txt)"):
                        log_editor = gr.Code(label="ログ内容", interactive=True, elem_id="log_editor_code") # Removed language="markdown" for plain text
                        with gr.Row():
                            save_log_button = gr.Button(value="ログを保存", variant="secondary")
                            editor_reload_button = gr.Button(value="ログ再読込", variant="secondary")

            with gr.Accordion("⏰ 時間管理", open=False):
                with gr.Tabs():
                    with gr.TabItem("アラーム"):
                        gr.Markdown("ℹ️ **操作方法**: リストから操作したいアラームの行を選択し、下のボタンで操作します。")
                        alarm_dataframe_display_only = gr.Dataframe(headers=["状態", "時刻", "曜日", "キャラ", "テーマ"], datatype=["bool", "str", "str", "str", "str"], interactive=True, row_count=(5, "dynamic"), col_count=5, wrap=True, elem_id="alarm_dataframe_display")
                        selection_feedback_markdown = gr.Markdown("アラームを選択してください", elem_id="selection_feedback")
                        with gr.Row():
                            enable_button = gr.Button("✔️ 選択を有効化")
                            disable_button = gr.Button("❌ 選択を無効化")
                            delete_alarm_button = gr.Button("🗑️ 選択したアラームを削除", variant="stop")
                        gr.Markdown("---"); gr.Markdown("#### 新規 / 更新")
                        alarm_hour_dropdown = gr.Dropdown(choices=[str(i).zfill(2) for i in range(24)], label="時", value="08")
                        alarm_minute_dropdown = gr.Dropdown(choices=[str(i).zfill(2) for i in range(60)], label="分", value="00")
                        alarm_char_dropdown = gr.Dropdown(choices=character_list_on_startup, value=effective_initial_character, label="キャラ")
                        alarm_theme_input = gr.Textbox(label="テーマ", placeholder="例：朝の目覚まし")
                        alarm_prompt_input = gr.Textbox(label="プロンプト（オプション）", placeholder="例：今日も一日頑張ろう！")
                        alarm_days_checkboxgroup = gr.CheckboxGroup(choices=list(ui_handlers.DAY_MAP_JA_TO_EN.keys()), label="曜日", value=list(ui_handlers.DAY_MAP_JA_TO_EN.keys())) # Use JA days
                        alarm_add_button = gr.Button("アラーム追加")

                    with gr.TabItem("タイマー"):
                        timer_type_radio = gr.Radio(["通常タイマー", "ポモドーロタイマー"], label="タイマー種別", value="通常タイマー")
                        with gr.Column(visible=True) as normal_timer_ui:
                            timer_duration_number = gr.Number(label="タイマー時間 (分)", value=10, minimum=1, step=1)
                            normal_timer_theme_input = gr.Textbox(label="通常タイマーのテーマ", placeholder="例: タイマー終了！")
                        with gr.Column(visible=False) as pomo_timer_ui:
                            pomo_work_number = gr.Number(label="作業時間 (分)", value=25, minimum=1, step=1)
                            pomo_break_number = gr.Number(label="休憩時間 (分)", value=5, minimum=1, step=1)
                            pomo_cycles_number = gr.Number(label="サイクル数", value=4, minimum=1, step=1)
                            timer_work_theme_input = gr.Textbox(label="作業終了時テーマ", placeholder="作業終了！")
                            timer_break_theme_input = gr.Textbox(label="休憩終了時テーマ", placeholder="休憩終了！")
                        timer_char_dropdown = gr.Dropdown(choices=character_list_on_startup, value=effective_initial_character, label="通知キャラ", interactive=True)
                        timer_status_output = gr.Textbox(label="タイマー設定状況", interactive=False, placeholder="ここに設定内容が表示されます。")
                        timer_submit_button = gr.Button("タイマー開始", variant="primary")

        with gr.Column(scale=3):
            chatbot_display = gr.Chatbot(type="messages", height=600, elem_id="chat_output_area", show_copy_button=True, bubble_full_width=False)
            chat_input_textbox = gr.Textbox(show_label=False, placeholder="メッセージを入力...", lines=3)
            with gr.Row():
                submit_button = gr.Button("送信", variant="primary", scale=4)
                chat_reload_button = gr.Button("🔄 更新", scale=1)

            # Simplified allowed_file_types for brevity, use user's full list if needed
            allowed_file_types = ['.txt', '.md', '.json', '.csv', '.png', '.jpg', '.jpeg', '.pdf']
            file_upload_button = gr.Files(label="ファイル添付 (複数可)", type="filepath", file_count="multiple", file_types=allowed_file_types)
            # Accordion for file types can be added back if user's full list is used
            # with gr.Accordion("📎 対応ファイル形式一覧", open=False):
            #     gr.Markdown("（ファイル形式一覧は省略）")

    # --- イベントリスナー定義 ---
    # Wrapper for initial load to set multiple outputs correctly
    def initial_load_ui_elements(char_name_to_load):
        # This call returns: character_name, chat_history, "", img_p, memory_str, character_name, log_content, character_name
        (current_char_val, current_chat_hist_val, _, current_profile_img_val,
         current_mem_str_val, alarm_dd_char_val, current_log_content_val, timer_dd_char_val
        ) = ui_handlers.update_ui_on_character_change(char_name_to_load)

        df_with_ids = ui_handlers.render_alarms_as_dataframe() # Contains 'id'
        display_df = ui_handlers.get_display_df(df_with_ids)   # No 'id'

        return (
            display_df, # For alarm_dataframe_display_only
            df_with_ids, # For alarm_dataframe_original_data (hidden state)
            current_chat_hist_val,
            current_log_content_val,
            current_mem_str_val,
            current_profile_img_val,
            alarm_dd_char_val, # For alarm_char_dropdown
            timer_dd_char_val, # For timer_char_dropdown
            "アラームを選択してください", # For selection_feedback_markdown
            current_char_val # For current_character_name (state)
        )

    # demo.load to populate UI elements on startup
    demo.load(
        fn=initial_load_ui_elements,
        inputs=[current_character_name], # Use the initial state
        outputs=[
            alarm_dataframe_display_only, alarm_dataframe_original_data,
            chatbot_display, log_editor, memory_json_editor,
            profile_image_display, alarm_char_dropdown, timer_char_dropdown,
            selection_feedback_markdown, current_character_name # Ensure current_character_name state is updated
        ]
    )

    # Character change event
    character_dropdown.change(
        fn=ui_handlers.update_ui_on_character_change,
        inputs=[character_dropdown],
        outputs=[
            current_character_name, chatbot_display, chat_input_textbox,
            profile_image_display, memory_json_editor, alarm_char_dropdown,
            log_editor, timer_char_dropdown
        ]
    ).then( # Chain .then to update alarm dataframe after character change
        fn=lambda: (ui_handlers.get_display_df(ui_handlers.render_alarms_as_dataframe()), ui_handlers.render_alarms_as_dataframe()),
        outputs=[alarm_dataframe_display_only, alarm_dataframe_original_data]
    )

    add_character_button.click(
        fn=ui_handlers.handle_add_new_character,
        inputs=[new_character_name_textbox],
        outputs=[character_dropdown, alarm_char_dropdown, timer_char_dropdown, new_character_name_textbox]
    )

    # Alarm UI events
    alarm_dataframe_display_only.select( # Select on the display-only dataframe
        fn=ui_handlers.handle_alarm_selection_and_feedback,
        inputs=[alarm_dataframe_original_data], # Use original data (with IDs) for logic
        outputs=[selected_alarm_ids_state, selection_feedback_markdown],
        show_progress='hidden'
    )
    # ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
    # ★★★ アラームフォーム更新は、選択されたIDのState変数が変更された時にトリガー ★★★
    # ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
    selected_alarm_ids_state.change( # Trigger form update when selected_alarm_ids_state changes
        fn=ui_handlers.load_alarm_to_form,
        inputs=[selected_alarm_ids_state],
        outputs=[
            alarm_add_button, alarm_theme_input, alarm_prompt_input,
            alarm_char_dropdown, alarm_days_checkboxgroup,
            alarm_hour_dropdown, alarm_minute_dropdown, editing_alarm_id_state
        ]
    )


    enable_button.click(
        fn=ui_handlers.toggle_selected_alarms_status,
        inputs=[selected_alarm_ids_state, gr.State(True)],
        outputs=[alarm_dataframe_original_data] # Update original data
    ).then( # Then update the display-only dataframe
        fn=lambda df: ui_handlers.get_display_df(df),
        inputs=[alarm_dataframe_original_data],
        outputs=[alarm_dataframe_display_only]
    )

    disable_button.click(
        fn=ui_handlers.toggle_selected_alarms_status,
        inputs=[selected_alarm_ids_state, gr.State(False)],
        outputs=[alarm_dataframe_original_data]
    ).then(
        fn=lambda df: ui_handlers.get_display_df(df),
        inputs=[alarm_dataframe_original_data],
        outputs=[alarm_dataframe_display_only]
    )

    delete_alarm_button.click(
        fn=ui_handlers.handle_delete_selected_alarms,
        inputs=[selected_alarm_ids_state],
        outputs=[alarm_dataframe_original_data]
    ).then(
        fn=lambda df: ui_handlers.get_display_df(df),
        inputs=[alarm_dataframe_original_data],
        outputs=[alarm_dataframe_display_only]
    ).then( # Reset selection state after delete
        fn=lambda: ([], "アラームを選択してください", None), # Clear selected_ids and editing_id
        outputs=[selected_alarm_ids_state, selection_feedback_markdown, editing_alarm_id_state]
    )

    alarm_add_button.click(
        fn=ui_handlers.handle_add_or_update_alarm,
        inputs=[
            editing_alarm_id_state, alarm_hour_dropdown, alarm_minute_dropdown,
            alarm_char_dropdown, alarm_theme_input, alarm_prompt_input,
            alarm_days_checkboxgroup
        ],
        outputs=[ # This handler returns a tuple for multiple outputs
            alarm_dataframe_original_data, # First output in tuple
            alarm_dataframe_display_only,  # Second output in tuple
            alarm_add_button, alarm_theme_input, alarm_prompt_input,
            alarm_char_dropdown, alarm_days_checkboxgroup,
            alarm_hour_dropdown, alarm_minute_dropdown, editing_alarm_id_state
        ]
    )

    # Timer UI events
    timer_type_radio.change(
        fn=lambda t: (gr.update(visible=t=="通常タイマー"), gr.update(visible=t=="ポモドーロタイマー"), ""),
        inputs=[timer_type_radio],
        outputs=[normal_timer_ui, pomo_timer_ui, timer_status_output]
    )
    timer_submit_button.click(
        fn=ui_handlers.handle_timer_submission,
        inputs=[
            timer_type_radio, timer_duration_number, pomo_work_number, pomo_break_number,
            pomo_cycles_number, timer_char_dropdown, timer_work_theme_input,
            timer_break_theme_input, api_key_dropdown,
            gr.State(config_manager.initial_notification_webhook_url_global), # Pass as state
            normal_timer_theme_input
        ],
        outputs=[timer_status_output]
    )

    # Config change events
    model_dropdown.change(fn=ui_handlers.update_model_state, inputs=[model_dropdown], outputs=[current_model_name])
    api_key_dropdown.change(fn=ui_handlers.update_api_key_state, inputs=[api_key_dropdown], outputs=[current_api_key_name_state])
    add_timestamp_checkbox.change(fn=ui_handlers.update_timestamp_state, inputs=[add_timestamp_checkbox], outputs=[])
    send_thoughts_checkbox.change(fn=ui_handlers.update_send_thoughts_state, inputs=[send_thoughts_checkbox], outputs=[send_thoughts_state])
    api_history_limit_dropdown.change(fn=ui_handlers.update_api_history_limit_state, inputs=[api_history_limit_dropdown], outputs=[api_history_limit_state])

    # Log and Memory editor events
    save_memory_button.click(fn=ui_handlers.handle_save_memory_click, inputs=[current_character_name, memory_json_editor])
    save_log_button.click(fn=ui_handlers.handle_save_log_button_click, inputs=[current_character_name, log_editor])
    editor_reload_button.click(fn=ui_handlers.reload_chat_log, inputs=[current_character_name], outputs=[chatbot_display, log_editor])

    # Chat submission events
    chat_reload_button.click(fn=ui_handlers.reload_chat_log, inputs=[current_character_name], outputs=[chatbot_display, log_editor])

    chat_submit_event_inputs = [
        chat_input_textbox, chatbot_display, current_character_name,
        current_model_name, current_api_key_name_state, file_upload_button,
        add_timestamp_checkbox, send_thoughts_state, api_history_limit_state
    ]
    chat_submit_event_outputs = [chatbot_display, chat_input_textbox, file_upload_button]

    chat_input_textbox.submit(fn=ui_handlers.handle_message_submission, inputs=chat_submit_event_inputs, outputs=chat_submit_event_outputs)
    submit_button.click(fn=ui_handlers.handle_message_submission, inputs=chat_submit_event_inputs, outputs=chat_submit_event_outputs)

    # App startup functions (deferred imports inside these handlers are key)
    demo.load(fn=ui_handlers.stop_existing_timer_on_startup, inputs=None, outputs=None)
    demo.load(fn=alarm_manager.start_alarm_scheduler_thread, inputs=None, outputs=None)


# --- Application Launch ---
if __name__ == "__main__":
    pc_url = "http://127.0.0.1:7860"
    print("\n" + "="*60)
    print("アプリケーションを起動します...")
    print(f"起動後、以下のURLでアクセスしてください。")
    print(f"  【PCからアクセスする場合】\n  {pc_url}")
    print("  【スマホからアクセスする場合（PCと同じWi-Fiに接続してください）】")
    print(f"  http://<お使いのPCのIPアドレス>:7860")
    print("  (IPアドレスが分からない場合は、PCのコマンドプロンプトやターミナルで `ipconfig` (Windows) または `ifconfig` (Mac/Linux) と入力して確認できます)")
    print("="*60 + "\n")
    demo.queue().launch(server_name="0.0.0.0", server_port=7860, share=False)
