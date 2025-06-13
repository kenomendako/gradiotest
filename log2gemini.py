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

# (起動シーケンスは変更なし)
# ...

# --- Gradio UI構築 ---
with gr.Blocks(theme=gr.themes.Soft(primary_hue="blue", secondary_hue="sky"), css=custom_css) as demo:
    # (起動前チェックは変更なし)
    # ...

    # --- UI State Variables ---
    current_character_name = gr.State(config_manager.initial_character_global)
    current_model_name = gr.State(config_manager.initial_model_global)
    current_api_key_name_state = gr.State(config_manager.initial_api_key_name_global)
    send_thoughts_state = gr.State(config_manager.initial_send_thoughts_to_api_global)
    api_history_limit_state = gr.State(config_manager.initial_api_history_limit_option_global)
    alarm_dataframe_original_data = gr.State(pd.DataFrame()) # To store the version of the dataframe with IDs for comparison
    selected_alarm_ids_state = gr.State([]) # Stores IDs of selected alarms

    # --- UIレイアウト定義 ---
    with gr.Row():
        with gr.Column(scale=1, min_width=300): # 左カラム
            # (キャラクター関連UIは変更なし - Kiseki assumes these are defined elsewhere or self-contained)
            gr.Markdown("キャラクター設定") # Placeholder for actual UI
            # Example: character_dropdown = gr.Dropdown(...)
            # Example: profile_image_display = gr.Image(...)
            alarm_char_dropdown = gr.Dropdown(label="アラーム用キャラ", choices=character_manager.get_character_list(), value=config_manager.initial_character_global) # Added for context

            with gr.Accordion("🐦 アラーム設定", open=False) as alarm_accordion:
                alarm_display_headers = ["状態", "時刻", "曜日", "キャラ", "テーマ"]
                alarm_dataframe = gr.Dataframe(
                    headers=alarm_display_headers,
                    datatype=["bool", "str", "str", "str", "str"],
                    interactive=True,
                    row_count=(5, "dynamic"), # Display 5 rows, allow scroll
                    col_count=(len(alarm_display_headers), "fixed"),
                    wrap=True,
                    elem_id="alarm_dataframe_display"
                )
                delete_alarm_button = gr.Button("✔️ 選択したアラームを削除", variant="stop")

                # (新規アラーム追加フォームは変更なし - Kiseki assumes these are defined)
                gr.Markdown("新規アラーム追加") # Placeholder
                alarm_hour_dropdown = gr.Dropdown(choices=[str(i).zfill(2) for i in range(24)], label="時")
                alarm_minute_dropdown = gr.Dropdown(choices=[str(i).zfill(2) for i in range(60)], label="分")
                # alarm_char_dropdown is defined above
                alarm_theme_input = gr.Textbox(label="テーマ")
                alarm_prompt_input = gr.Textbox(label="プロンプト（オプション）")
                alarm_days_checkboxgroup = gr.CheckboxGroup(choices=["月", "火", "水", "木", "金", "土", "日"], label="曜日")
                alarm_add_button = gr.Button("アラーム追加")

            # (タイマーUI、ヘルプUIは変更なし - Kiseki assumes these are defined)
            gr.Markdown("タイマーUI Placeholder")
            gr.Markdown("ヘルプUI Placeholder")

        with gr.Column(scale=3): # 右カラム
            # (チャットUIは変更なし - Kiseki assumes these are defined)
            gr.Markdown("チャットUI Placeholder")
            # Example: chat_history_display = gr.Chatbot(...)
            # Example: chat_input_textbox = gr.Textbox(...)
            # Example: send_button = gr.Button(...)

    # --- ここからイベントリスナー定義 ---
    # Make sure all UI components used in listeners (inputs/outputs) are defined above this line.

    # --- アラーム関連 ---
    def load_and_set_df_for_ui_and_state():
        # This function now needs to fetch the data with IDs for the state,
        # and the display version for the UI component.
        df_display = ui_handlers.render_alarms_as_dataframe()
        df_with_ids = ui_handlers.get_alarms_as_dataframe_with_id() # For the state
        return df_display, df_with_ids

    # Initial load for alarm dataframe and its original_data state
    demo.load(
        fn=load_and_set_df_for_ui_and_state,
        outputs=[alarm_dataframe, alarm_dataframe_original_data]
    )
    # Load when accordion is opened
    alarm_accordion.open(
        fn=load_and_set_df_for_ui_and_state,
        outputs=[alarm_dataframe, alarm_dataframe_original_data]
    )

    # When a cell in alarm_dataframe is changed (e.g., checkbox for '状態')
    alarm_dataframe.change(
        fn=ui_handlers.handle_alarm_dataframe_change,
        inputs=[alarm_dataframe, alarm_dataframe_original_data], # Pass the display df and the original (ID-ful) df
        outputs=[alarm_dataframe] # Output is the updated display df
    ).then(
        fn=ui_handlers.get_alarms_as_dataframe_with_id, # Then, update the original_data state with the fresh ID-ful df from DB
        outputs=[alarm_dataframe_original_data]
    )

    # When rows are selected in the alarm_dataframe
    alarm_dataframe.select(
        fn=ui_handlers.handle_alarm_selection,
        inputs=[alarm_dataframe], # Pass the display dataframe from which selection is made
        outputs=[selected_alarm_ids_state], # Output is the list of selected IDs
        show_progress='hidden'
    )

    # Delete selected alarms button click
    delete_alarm_button.click(
        fn=ui_handlers.handle_delete_selected_alarms,
        inputs=[selected_alarm_ids_state],
        outputs=[alarm_dataframe] # Update the display dataframe
    ).then(
        fn=lambda: [], # Clear the selected_alarm_ids_state
        outputs=[selected_alarm_ids_state]
    ).then(
        fn=load_and_set_df_for_ui_and_state, # Reload both display and original_data state
        outputs=[alarm_dataframe, alarm_dataframe_original_data]
    )

    # Add new alarm button click
    def add_alarm_and_refresh_ui_and_state(h, m, char, theme, prompt, days):
        alarm_manager.add_alarm(h, m, char, theme, prompt, days)
        return load_and_set_df_for_ui_and_state() # Returns two values for outputs

    alarm_add_button.click(
        fn=add_alarm_and_refresh_ui_and_state,
        inputs=[
            alarm_hour_dropdown, alarm_minute_dropdown, alarm_char_dropdown,
            alarm_theme_input, alarm_prompt_input, alarm_days_checkboxgroup
        ],
        outputs=[alarm_dataframe, alarm_dataframe_original_data] # Update both display and original_data state
    ).then(
        fn=lambda char_val: ("08", "00", char_val, "", "", ["月", "火", "水", "木", "金", "土", "日"]), # Reset input fields
        inputs=[current_character_name], # Pass current character to default in reset
        outputs=[
            alarm_hour_dropdown, alarm_minute_dropdown, alarm_char_dropdown,
            alarm_theme_input, alarm_prompt_input, alarm_days_checkboxgroup
        ]
    )

    # (他のイベントリスナーもここに記述 - Kiseki assumes these are defined and use existing components)
    # Example: character_dropdown.change(...)
    # Example: send_button.click(...)

# (アプリケーション起動部分は変更なし)
# demo.launch() etc.
