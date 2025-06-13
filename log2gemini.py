# -*- coding: utf-8 -*-
import gradio as gr
import os, sys, json, traceback, threading, time, pandas as pd
import config_manager, character_manager, memory_manager, alarm_manager, gemini_api, utils, ui_handlers

# 起動シーケンス (Kiseki Ver.5)
config_manager.load_config()
alarm_manager.load_alarms()
# utils.ensure_data_directories() # REMOVED in Ver.4
if config_manager.initial_api_key_name_global and hasattr(gemini_api, 'configure_google_api'):
    gemini_api.configure_google_api(config_manager.initial_api_key_name_global)
# No call to gemini_api.load_available_models_from_config() as models come from config_manager

# (CSS定義は変更なし - taken from Kiseki's previous full versions)
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

with gr.Blocks(theme=gr.themes.Soft(primary_hue="blue", secondary_hue="sky"), css=custom_css) as demo:
    # (起動前チェックは省略 - Kiseki Ver.5)

    # --- UI State Variables (Kiseki Ver.5 - using global variables from config_manager) ---
    current_character_name = gr.State(config_manager.initial_character_global)
    current_model_name = gr.State(config_manager.initial_model_global)
    current_api_key_name_state = gr.State(config_manager.initial_api_key_name_global)
    send_thoughts_state = gr.State(config_manager.initial_send_thoughts_to_api_global)
    api_history_limit_state = gr.State(config_manager.initial_api_history_limit_option_global)

    alarm_dataframe_original_data = gr.State(pd.DataFrame())
    selected_alarm_ids_state = gr.State([])

    # --- UIレイアウト定義 (Comprehensive layout from previous attempts, adapted for Kiseki Ver.5) ---
    with gr.Row():
        with gr.Column(scale=1, min_width=300): # 左カラム
            gr.Markdown("### キャラクター")
            character_dropdown = gr.Dropdown(
                choices=character_manager.get_character_list(),
                value=config_manager.initial_character_global,
                label="キャラクターを選択",
                interactive=True
            )
            profile_image_display = gr.Image(height=150, width=150, interactive=False, show_label=False, container=False)

            with gr.Accordion("⚙️ 基本設定", open=False):
                # CRITICAL FIX for Ver.5: Use config_manager.AVAILABLE_MODELS_GLOBAL
                available_models_list = getattr(config_manager, 'AVAILABLE_MODELS_GLOBAL', [])
                if not isinstance(available_models_list, list): # Ensure it's a list
                    available_models_list = []

                model_dropdown = gr.Dropdown(
                    choices=available_models_list, # Corrected model list source
                    value=config_manager.initial_model_global,
                    label="モデルを選択",
                    interactive=True
                )
                api_keys_dict = getattr(config_manager, 'api_keys_config', {})
                if not api_keys_dict and hasattr(config_manager, 'config') and 'api_keys' in config_manager.config:
                    api_keys_dict = config_manager.config['api_keys']

                api_key_dropdown = gr.Dropdown(
                    choices=list(api_keys_dict.keys()),
                    value=config_manager.initial_api_key_name_global,
                    label="APIキーを選択",
                    interactive=True
                )
                add_timestamp_checkbox = gr.Checkbox(
                    value=getattr(config_manager, 'add_timestamp_global', True),
                    label="メッセージにタイムスタンプを追加",
                    interactive=True
                )
                send_thoughts_checkbox = gr.Checkbox(
                    value=config_manager.initial_send_thoughts_to_api_global,
                    label="Gemini APIに思考プロセスを送信 (デバッグ用)",
                    interactive=True
                )

                api_history_options_map = getattr(config_manager, 'API_HISTORY_LIMIT_OPTIONS', {"all": "全履歴"})
                api_history_limit_dropdown = gr.Dropdown(
                    choices=list(api_history_options_map.values()),
                    value=api_history_options_map.get(config_manager.initial_api_history_limit_option_global, api_history_options_map.get("all")),
                    label="API送信履歴数の上限",
                    interactive=True
                )

            memory_filename_global = getattr(config_manager, 'MEMORY_FILENAME_GLOBAL', 'memory.json')
            with gr.Accordion(f"📗 キャラクターの記憶 ({memory_filename_global})", open=False) as memory_accordion:
                memory_json_editor = gr.Code(label="記憶データ (JSON形式で編集)", language="json", interactive=True, elem_id="memory_json_editor_code")
                save_memory_button = gr.Button(value="想いを綴る", variant="secondary")

            with gr.Accordion("📗 チャットログ編集 (`log.txt`)", open=False) as log_accordion:
                log_editor = gr.Code(label="ログ内容 (直接編集可能)", interactive=True, elem_id="log_editor_code")
                save_log_button = gr.Button(value="ログを保存", variant="secondary")
                reload_log_button = gr.Button(value="ログ再読込", variant="secondary")

            # Alarm UI definition from Kiseki Ver.5
            with gr.Accordion("🐦 アラーム設定", open=False) as alarm_accordion:
                alarm_dataframe = gr.Dataframe(
                    headers=["状態", "時刻", "曜日", "キャラ", "テーマ"],
                    datatype=["bool", "str", "str", "str", "str"],
                    interactive=True, row_count=(5, "dynamic"), col_count=5,
                    wrap=True, elem_id="alarm_dataframe_display"
                )
                delete_alarm_button = gr.Button("✔️ 選択したアラームを削除", variant="stop")
                with gr.Column(visible=True): # Kiseki Ver.5 shows this column
                    gr.Markdown("---")
                    gr.Markdown("#### 新規アラーム追加")
                    # (新規アラーム追加フォームは省略 - Kiseki Ver.5)
                    # For completeness, adding the form components from previous versions
                    alarm_hour_dropdown = gr.Dropdown(choices=[str(i).zfill(2) for i in range(24)], label="時", value="08")
                    alarm_minute_dropdown = gr.Dropdown(choices=[str(i).zfill(2) for i in range(60)], label="分", value="00")
                    alarm_char_dropdown = gr.Dropdown(choices=character_manager.get_character_list(), value=config_manager.initial_character_global, label="キャラ")
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
                timer_char_dropdown = gr.Dropdown(choices=character_manager.get_character_list(), value=config_manager.initial_character_global, label="通知キャラ")
                timer_work_theme_input = gr.Textbox(label="作業終了時テーマ", placeholder="作業終了！")
                timer_break_theme_input = gr.Textbox(label="休憩終了時テーマ", placeholder="休憩終了！")
                timer_normal_theme_input = gr.Textbox(label="通常タイマー終了時テーマ", placeholder="時間です！")
                timer_api_key_dropdown = gr.Dropdown(choices=list(api_keys_dict.keys()), value=config_manager.initial_api_key_name_global, label="通知用APIキー")
                timer_webhook_input = gr.Textbox(label="Webhook URL (オプション)", placeholder="https://...")
                timer_start_button = gr.Button("タイマー開始", variant="primary")
                timer_status_display = gr.Textbox(label="タイマー状況", interactive=False)

            app_version_global = getattr(config_manager, 'APP_VERSION', '不明')
            with gr.Accordion("ℹ️ ヘルプ & 情報", open=False):
                gr.Markdown(f"バージョン: {app_version_global}")

        with gr.Column(scale=3): # 右カラム (Kiseki Ver.5 - UI定義は省略)
            # For completeness, adding Chat UI components from previous versions
            chatbot_display = gr.Chatbot(label="チャット", height=600, elem_id="chat_output_area", show_copy_button=True, bubble_full_width=False) # Name: chatbot in Kiseki's demo.load
            with gr.Row():
                chat_input_textbox = gr.Textbox(show_label=False, placeholder="メッセージを入力...", scale=7, elem_id="chat_input_box")
                submit_button = gr.Button("送信", variant="primary", scale=1)
            file_upload_button = gr.Files(label="ファイル添付 (複数可)", type="filepath", elem_id="file_upload_area")
            with gr.Row():
                clear_chat_button = gr.Button("チャット履歴クリア", variant="stop")


    # --- ここからイベントリスナー定義 (Kiseki Ver.5) ---

    # --- 初期化関連 ---
    def initial_load_v5(): # As per Kiseki Ver.5
        df_with_ids = ui_handlers.render_alarms_as_dataframe() # ID-ful
        display_df = ui_handlers.get_display_df(df_with_ids)   # ID-less

        char_name = config_manager.initial_character_global

        # Kiseki Ver.5 ui_handlers.update_ui_on_character_change returns 7 items:
        # char_name, chat_hist, "", profile_img, mem_str, char_name_for_alarm_dd_only, log_content
        # Kiseki Ver.5 log2gemini demo.load outputs (8 items):
        # [alarm_dataframe, alarm_dataframe_original_data, chatbot, log_editor, memory_json_editor, profile_image_display, alarm_char_dropdown, timer_char_dropdown]
        # The ui_handlers function needs to provide enough for these.
        # The 7th item from ui_handler (log_content) goes to log_editor.
        # The 6th item from ui_handler (char_name for alarm_dd) goes to alarm_char_dropdown.
        # We need a value for timer_char_dropdown. Let's assume it's also char_name.

        # Call the 7-output version from ui_handlers.py Ver.5
        returned_char_name, current_chat_hist, _, current_profile_img, current_mem_str, alarm_dd_char_val, current_log_content = ui_handlers.update_ui_on_character_change(char_name)

        return (
            display_df,             # For alarm_dataframe
            df_with_ids,            # For alarm_dataframe_original_data
            current_chat_hist,      # For chatbot_display (Kiseki used 'chatbot')
            current_log_content,    # For log_editor
            current_mem_str,        # For memory_json_editor
            current_profile_img,    # For profile_image_display
            alarm_dd_char_val,      # For alarm_char_dropdown
            alarm_dd_char_val       # For timer_char_dropdown (assuming same as alarm)
        )

    # Kiseki Ver.5 demo.load outputs had 'chatbot'. My component is 'chatbot_display'.
    demo.load(
        fn=initial_load_v5,
        inputs=None,
        outputs=[
            alarm_dataframe, alarm_dataframe_original_data, chatbot_display, log_editor,
            memory_json_editor, profile_image_display, alarm_char_dropdown, timer_char_dropdown
        ]
    )

    # --- アラーム関連リスナー (Kiseki Ver.5) ---
    def refresh_alarm_ui_v5(): # As per Kiseki Ver.5
        new_df_with_ids = ui_handlers.render_alarms_as_dataframe() # ID-ful
        new_display_df = ui_handlers.get_display_df(new_df_with_ids) # ID-less
        return new_display_df, new_df_with_ids

    alarm_accordion.open(fn=refresh_alarm_ui_v5, outputs=[alarm_dataframe, alarm_dataframe_original_data])

    # Kiseki Ver.5: inputs=[alarm_dataframe, alarm_dataframe_original_data], outputs=[alarm_dataframe_original_data]
    # .then(fn=lambda df: ui_handlers.get_display_df(df), inputs=[alarm_dataframe_original_data], outputs=[alarm_dataframe])
    # This is correct. ui_handlers.handle_alarm_dataframe_change (Ver.5) returns ID-ful.
    alarm_dataframe.change(
        fn=ui_handlers.handle_alarm_dataframe_change,
        inputs=[alarm_dataframe, alarm_dataframe_original_data],
        outputs=[alarm_dataframe_original_data]
    ).then(
        fn=lambda id_df: ui_handlers.get_display_df(id_df),
        inputs=[alarm_dataframe_original_data],
        outputs=[alarm_dataframe]
    )

    # Kiseki Ver.5: inputs=[alarm_dataframe_original_data]
    alarm_dataframe.select(
        fn=ui_handlers.handle_alarm_selection,
        inputs=[alarm_dataframe_original_data],
        outputs=[selected_alarm_ids_state],
        show_progress='hidden'
    )

    # Kiseki Ver.5: outputs=[alarm_dataframe_original_data]
    # .then(fn=lambda df: ui_handlers.get_display_df(df), inputs=[alarm_dataframe_original_data], outputs=[alarm_dataframe])
    # .then(fn=lambda: [], outputs=[selected_alarm_ids_state])
    # This is correct. ui_handlers.handle_delete_selected_alarms (Ver.5) returns ID-ful.
    delete_alarm_button.click(
        fn=ui_handlers.handle_delete_selected_alarms,
        inputs=[selected_alarm_ids_state],
        outputs=[alarm_dataframe_original_data]
    ).then(
        fn=lambda id_df: ui_handlers.get_display_df(id_df),
        inputs=[alarm_dataframe_original_data],
        outputs=[alarm_dataframe]
    ).then(
        fn=lambda: [],
        outputs=[selected_alarm_ids_state]
    )

    def add_alarm_and_refresh_v5(h, m, char, theme, prompt, days): # Kiseki Ver.5
        alarm_manager.add_alarm(h, m, char, theme, prompt, days)
        return refresh_alarm_ui_v5() # Returns (display_df, id_ful_df)

    # Kiseki Ver.5: inputs=[...] (assuming full list), outputs=[alarm_dataframe, alarm_dataframe_original_data]
    # .then(fn=lambda char: ("08", "00", char, "", "", ["月", ...]), inputs=[current_character_name], outputs=[...]) (assuming full list)
    alarm_add_button.click(
        fn=add_alarm_and_refresh_v5,
        inputs=[alarm_hour_dropdown, alarm_minute_dropdown, alarm_char_dropdown, alarm_theme_input, alarm_prompt_input, alarm_days_checkboxgroup],
        outputs=[alarm_dataframe, alarm_dataframe_original_data]
    ).then(
        fn=lambda char_val: ("08", "00", char_val if char_val else config_manager.initial_character_global, "", "", ["月", "火", "水", "木", "金", "土", "日"]),
        inputs=[current_character_name],
        outputs=[alarm_hour_dropdown, alarm_minute_dropdown, alarm_char_dropdown, alarm_theme_input, alarm_prompt_input, alarm_days_checkboxgroup]
    )

    # --- Other Event Listeners (Kiseki Ver.5 implies these are largely unchanged from a working state) ---
    # ui_handlers.update_ui_on_character_change (Ver.5) returns 7 items.
    # log2gemini.py character_dropdown.change needs to map these to its 8 outputs.
    # Outputs: current_character_name, chatbot_display, chat_input_textbox, profile_image_display,
    # memory_json_editor, alarm_char_dropdown, timer_char_dropdown, log_editor
    def character_change_wrapper(char_name_from_dd):
        name_state, hist, _, profile_img, mem_str, alarm_char, log_content = ui_handlers.update_ui_on_character_change(char_name_from_dd)
        # Assuming alarm_char can be used for timer_char_dropdown as well
        return name_state, hist, "", profile_img, mem_str, alarm_char, alarm_char, log_content

    character_dropdown.change(
        fn=character_change_wrapper,
        inputs=[character_dropdown],
        outputs=[
            current_character_name, chatbot_display, chat_input_textbox,
            profile_image_display, memory_json_editor, alarm_char_dropdown,
            timer_char_dropdown, log_editor
        ]
    ).then(fn=refresh_alarm_ui_v5, outputs=[alarm_dataframe, alarm_dataframe_original_data])


    model_dropdown.change(fn=ui_handlers.update_model_state, inputs=[model_dropdown], outputs=[current_model_name])
    api_key_dropdown.change(fn=ui_handlers.update_api_key_state, inputs=[api_key_dropdown], outputs=[current_api_key_name_state])
    add_timestamp_checkbox.change(fn=ui_handlers.update_timestamp_state, inputs=[add_timestamp_checkbox], outputs=[])
    send_thoughts_checkbox.change(fn=ui_handlers.update_send_thoughts_state, inputs=[send_thoughts_checkbox], outputs=[send_thoughts_state])
    api_history_limit_dropdown.change(fn=ui_handlers.update_api_history_limit_state, inputs=[api_history_limit_dropdown], outputs=[api_history_limit_state])

    save_memory_button.click(
        fn=lambda char, mem_str: memory_manager.save_memory_data(char, json.loads(mem_str)) if char and mem_str else gr.Warning("Character or memory content is empty."),
        inputs=[current_character_name, memory_json_editor], outputs=[]
    ).then(fn=lambda: gr.Info("記憶を保存しました。"),outputs=[])

    save_log_button.click(fn=ui_handlers.handle_save_log_button_click, inputs=[current_character_name, log_editor], outputs=[])
    reload_log_button.click(
        fn=ui_handlers.reload_chat_log,
        inputs=[current_character_name],
        outputs=[chatbot_display, log_editor]
    )

    # Kiseki Ver.5 ui_handlers.handle_message_submission returns 4 items for outputs.
    chat_submit_outputs = [chatbot_display, chat_input_textbox, file_upload_button, timer_status_display]
    chat_input_textbox.submit(
        fn=ui_handlers.handle_message_submission,
        inputs=[
            chat_input_textbox, chatbot_display, current_character_name, current_model_name,
            current_api_key_name_state, file_upload_button, add_timestamp_checkbox,
            send_thoughts_state, api_history_limit_state
        ],
        outputs=chat_submit_outputs
    )
    submit_button.click(
        fn=ui_handlers.handle_message_submission,
        inputs=[
            chat_input_textbox, chatbot_display, current_character_name, current_model_name,
            current_api_key_name_state, file_upload_button, add_timestamp_checkbox,
            send_thoughts_state, api_history_limit_state
        ],
        outputs=chat_submit_outputs
    )

    clear_chat_button.click(
        fn=lambda char_name_state: ([], memory_manager.reset_chat_memory(char_name_state) if char_name_state else None),
        inputs=[current_character_name],
        outputs=[chatbot_display]
    ).then(fn=lambda: gr.Info("チャット履歴をクリアしました。"), outputs=[])

    timer_start_button.click(
        fn=ui_handlers.handle_timer_submission,
        inputs=[
            timer_type_radio, timer_duration_number, pomo_work_number, pomo_break_number, pomo_cycles_number,
            timer_char_dropdown, timer_work_theme_input, timer_break_theme_input,
            timer_api_key_dropdown, timer_webhook_input, timer_normal_theme_input
        ],
        outputs=[timer_status_display]
    )

# Application launch
# if __name__ == "__main__":
#     demo.launch()
