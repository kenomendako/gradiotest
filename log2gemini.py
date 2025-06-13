# -*- coding: utf-8 -*-
import gradio as gr
import os, sys, json, traceback, threading, time, pandas as pd
import config_manager, character_manager, memory_manager, alarm_manager, gemini_api, utils, ui_handlers

# 起動シーケンス (Kiseki Ver.4)
config_manager.load_config()
alarm_manager.load_alarms() # Ensure alarms are loaded from alarms.json
# utils.ensure_data_directories() # REMOVED as per Kiseki Ver.4 - this was the AttributeError cause

if hasattr(gemini_api, 'load_available_models_from_config'): # If such a function exists for dynamic model loading
    gemini_api.load_available_models_from_config()

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
    # (起動前チェックは省略 - Kiseki Ver.4)

    # --- UI State Variables (Kiseki Ver.4 - using global variables from config_manager) ---
    current_character_name = gr.State(config_manager.initial_character_global)
    current_model_name = gr.State(config_manager.initial_model_global)
    current_api_key_name_state = gr.State(config_manager.initial_api_key_name_global)
    send_thoughts_state = gr.State(config_manager.initial_send_thoughts_to_api_global)
    api_history_limit_state = gr.State(config_manager.initial_api_history_limit_option_global)

    alarm_dataframe_original_data = gr.State(pd.DataFrame()) # Stores DataFrame WITH IDs
    selected_alarm_ids_state = gr.State([]) # Stores list of selected alarm IDs

    # --- UIレイアウト定義 (Comprehensive layout from previous attempts, adapted for Kiseki Ver.4) ---
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
                model_dropdown = gr.Dropdown(
                    choices=gemini_api.available_models,
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
            with gr.Accordion(f"📗 キャラクターの記憶 ({memory_filename_global})", open=False) as memory_accordion: # Name from Kiseki Ver.3
                memory_json_editor = gr.Code(label="記憶データ (JSON形式で編集)", language="json", interactive=True, elem_id="memory_json_editor_code")
                save_memory_button = gr.Button(value="想いを綴る", variant="secondary")

            with gr.Accordion("📗 チャットログ編集 (`log.txt`)", open=False) as log_accordion: # Name from Kiseki Ver.3
                log_editor = gr.Code(label="ログ内容 (直接編集可能)", interactive=True, elem_id="log_editor_code")
                save_log_button = gr.Button(value="ログを保存", variant="secondary")
                reload_log_button = gr.Button(value="ログ再読込", variant="secondary")

            with gr.Accordion("🐦 アラーム設定", open=False) as alarm_accordion: # Name from Kiseki Ver.3
                alarm_dataframe = gr.Dataframe(
                    headers=["状態", "時刻", "曜日", "キャラ", "テーマ"],
                    datatype=["bool", "str", "str", "str", "str"],
                    interactive=True, row_count=(5, "dynamic"), col_count=5,
                    wrap=True, elem_id="alarm_dataframe_display"
                )
                delete_alarm_button = gr.Button("✔️ 選択したアラームを削除", variant="stop")
                gr.Markdown("---") # Kiseki Ver.3 had this structure
                with gr.Column(): # Kiseki Ver.3 had this structure
                    gr.Markdown("#### 新規アラーム追加")
                    alarm_hour_dropdown = gr.Dropdown(choices=[str(i).zfill(2) for i in range(24)], label="時", value="08")
                    alarm_minute_dropdown = gr.Dropdown(choices=[str(i).zfill(2) for i in range(60)], label="分", value="00")
                    alarm_char_dropdown = gr.Dropdown(choices=character_manager.get_character_list(), value=config_manager.initial_character_global, label="キャラ")
                    alarm_theme_input = gr.Textbox(label="テーマ", placeholder="例：朝の目覚まし")
                    alarm_prompt_input = gr.Textbox(label="プロンプト（オプション）", placeholder="例：今日も一日頑張ろう！")
                    alarm_days_checkboxgroup = gr.CheckboxGroup(choices=["月", "火", "水", "木", "金", "土", "日"], label="曜日", value=["月", "火", "水", "木", "金"])
                    alarm_add_button = gr.Button("アラーム追加")

            with gr.Accordion("⏱️ タイマー設定", open=False) as timer_accordion: # Name from Kiseki Ver.3
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

            app_version_global = getattr(config_manager, 'APP_VERSION', '不明') # Kiseki Ver.3 structure
            with gr.Accordion("ℹ️ ヘルプ & 情報", open=False): # Name from Kiseki Ver.3
                gr.Markdown(f"バージョン: {app_version_global}")

        with gr.Column(scale=3): # 右カラム
            chatbot_display = gr.Chatbot(label="チャット", height=600, elem_id="chat_output_area", show_copy_button=True, bubble_full_width=False) # Name from Kiseki's demo.load outputs
            with gr.Row():
                chat_input_textbox = gr.Textbox(show_label=False, placeholder="メッセージを入力...", scale=7, elem_id="chat_input_box")
                submit_button = gr.Button("送信", variant="primary", scale=1)
            file_upload_button = gr.Files(label="ファイル添付 (複数可)", type="filepath", elem_id="file_upload_area")
            with gr.Row():
                clear_chat_button = gr.Button("チャット履歴クリア", variant="stop")

    # --- ここからイベントリスナー定義 (Kiseki Ver.4) ---

    # --- 初期化関連 ---
    def initial_load_v4(): # As per Kiseki Ver.4
        df_with_ids = ui_handlers.render_alarms_as_dataframe() # Returns ID-ful
        display_df = ui_handlers.get_display_df(df_with_ids)   # Returns ID-less

        char_name = config_manager.initial_character_global # Use state var value for consistency

        # ui_handlers.update_ui_on_character_change Ver.4 returns 8 items:
        # char_name, chat_hist, "", profile_img, mem_str, alarm_char_val, timer_char_val, log_content
        _, current_chat_hist, _, current_profile_img, current_mem_str, alarm_dd_char, timer_dd_char, current_log_content = ui_handlers.update_ui_on_character_change(char_name)

        # Outputs for demo.load in Kiseki Ver.4:
        # [alarm_dataframe, alarm_dataframe_original_data, chatbot, log_editor, memory_json_editor, profile_image_display, alarm_char_dropdown, timer_char_dropdown]
        return (
            display_df,             # For alarm_dataframe
            df_with_ids,            # For alarm_dataframe_original_data
            current_chat_hist,      # For chatbot_display (named 'chatbot' in Kiseki's list)
            current_log_content,    # For log_editor
            current_mem_str,        # For memory_json_editor
            current_profile_img,    # For profile_image_display
            alarm_dd_char,          # For alarm_char_dropdown
            timer_dd_char           # For timer_char_dropdown
        )

    demo.load(
        fn=initial_load_v4,
        inputs=None, # No inputs needed as it uses global state
        outputs=[
            alarm_dataframe, alarm_dataframe_original_data, chatbot_display, log_editor,
            memory_json_editor, profile_image_display, alarm_char_dropdown, timer_char_dropdown
        ]
    )

    # --- アラーム関連リスナー (Kiseki Ver.4) ---
    def refresh_alarm_ui_v4(): # As per Kiseki Ver.4
        new_df_with_ids = ui_handlers.render_alarms_as_dataframe() # ID-ful
        new_display_df = ui_handlers.get_display_df(new_df_with_ids) # ID-less
        return new_display_df, new_df_with_ids # display_df for alarm_dataframe, id_ful_df for alarm_dataframe_original_data

    alarm_accordion.open(fn=refresh_alarm_ui_v4, outputs=[alarm_dataframe, alarm_dataframe_original_data])

    # Kiseki Ver.4: inputs=[alarm_dataframe, alarm_dataframe_original_data], outputs=[alarm_dataframe_original_data]
    # .then(fn=ui_handlers.render_alarms_as_dataframe, outputs=[alarm_dataframe])
    # My ui_handlers Ver.4 handle_alarm_dataframe_change returns ID-ful.
    # So, the .then() needs to use get_display_df.
    alarm_dataframe.change(
        fn=ui_handlers.handle_alarm_dataframe_change,
        inputs=[alarm_dataframe, alarm_dataframe_original_data], # Sends (DisplayDF from component, IDfulDF from state)
        outputs=[alarm_dataframe_original_data] # Handler returns new IDfulDF for state
    ).then(
        fn=lambda id_df: ui_handlers.get_display_df(id_df), # Convert IDful state to DisplayDF
        inputs=[alarm_dataframe_original_data],
        outputs=[alarm_dataframe] # Update display component
    )

    # Kiseki Ver.4: inputs=[alarm_dataframe_original_data]
    alarm_dataframe.select(
        fn=ui_handlers.handle_alarm_selection,
        inputs=[alarm_dataframe_original_data],
        outputs=[selected_alarm_ids_state],
        show_progress='hidden'
    )

    # Kiseki Ver.4: outputs=[alarm_dataframe]
    # .then(fn=lambda: [], outputs=[selected_alarm_ids_state])
    # .then(fn=refresh_alarm_ui, outputs=[alarm_dataframe, alarm_dataframe_original_data])
    # ui_handlers.handle_delete_selected_alarms (Ver.4) returns ID-ful.
    # The first output must be display-only if it goes to alarm_dataframe component.
    delete_alarm_button.click(
        fn=lambda ids: ui_handlers.get_display_df(ui_handlers.handle_delete_selected_alarms(ids)), # Get display version
        inputs=[selected_alarm_ids_state],
        outputs=[alarm_dataframe] # Update display component
    ).then(
        fn=lambda: [], # Clear selection state
        outputs=[selected_alarm_ids_state]
    ).then(
        fn=refresh_alarm_ui_v4, # Then, refresh both display and original_data state
        outputs=[alarm_dataframe, alarm_dataframe_original_data]
    )

    def add_alarm_and_refresh_v4(h, m, char, theme, prompt, days): # Kiseki Ver.4
        alarm_manager.add_alarm(h, m, char, theme, prompt, days)
        return refresh_alarm_ui_v4() # Returns (display_df, id_ful_df)

    # Kiseki Ver.4: outputs=[alarm_dataframe, alarm_dataframe_original_data]
    # .then(fn=lambda char: ("08", "00", char, "", "", ["月", ...]), ...)
    alarm_add_button.click(
        fn=add_alarm_and_refresh_v4,
        inputs=[alarm_hour_dropdown, alarm_minute_dropdown, alarm_char_dropdown, alarm_theme_input, alarm_prompt_input, alarm_days_checkboxgroup],
        outputs=[alarm_dataframe, alarm_dataframe_original_data]
    ).then(
        fn=lambda char_val: ("08", "00", char_val if char_val else config_manager.initial_character_global, "", "", ["月", "火", "水", "木", "金", "土", "日"]),
        inputs=[current_character_name], # Kiseki Ver.4 uses current_character_name state
        outputs=[alarm_hour_dropdown, alarm_minute_dropdown, alarm_char_dropdown, alarm_theme_input, alarm_prompt_input, alarm_days_checkboxgroup]
    )

    # --- Other Event Listeners (using full definitions from previous correct versions, adapted for Ver.4 ui_handlers) ---
    # Kiseki Ver.4 ui_handlers.update_ui_on_character_change returns 8 outputs.
    # Outputs for character_dropdown.change in Kiseki Ver.4 log2gemini:
    # [current_character_name, chatbot, log_editor, memory_json_editor, profile_image_display, alarm_char_dropdown, timer_char_dropdown] - 7 outputs.
    # My ui_handlers Ver.4 returns 8. I'll map to 8.
    character_dropdown.change(
        fn=ui_handlers.update_ui_on_character_change,
        inputs=[character_dropdown],
        outputs=[
            current_character_name, chatbot_display, chat_input_textbox,
            profile_image_display, memory_json_editor, alarm_char_dropdown,
            timer_char_dropdown, log_editor
        ]
    ).then(fn=refresh_alarm_ui_v4, outputs=[alarm_dataframe, alarm_dataframe_original_data])

    model_dropdown.change(fn=ui_handlers.update_model_state, inputs=[model_dropdown], outputs=[current_model_name])
    api_key_dropdown.change(fn=ui_handlers.update_api_key_state, inputs=[api_key_dropdown], outputs=[current_api_key_name_state])
    add_timestamp_checkbox.change(fn=ui_handlers.update_timestamp_state, inputs=[add_timestamp_checkbox], outputs=[])
    send_thoughts_checkbox.change(fn=ui_handlers.update_send_thoughts_state, inputs=[send_thoughts_checkbox], outputs=[send_thoughts_state])
    api_history_limit_dropdown.change(fn=ui_handlers.update_api_history_limit_state, inputs=[api_history_limit_dropdown], outputs=[api_history_limit_state])

    save_memory_button.click(
        fn=lambda char, mem_str: memory_manager.save_memory_data(char, json.loads(mem_str)) if char and mem_str else gr.Warning("Character or memory content is empty."),
        inputs=[current_character_name, memory_json_editor], outputs=[] # No direct UI output, just info/error
    ).then(fn=lambda: gr.Info("記憶を保存しました。"),outputs=[])


    save_log_button.click(fn=ui_handlers.handle_save_log_button_click, inputs=[current_character_name, log_editor], outputs=[])
    reload_log_button.click(
        fn=ui_handlers.reload_chat_log,
        inputs=[current_character_name],
        outputs=[chatbot_display, log_editor]
    )

    # Kiseki Ver.4 handle_message_submission(*args) returns 4 items.
    # outputs=[chatbot_display, chat_input_textbox, file_upload_button, timer_status_display]
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
