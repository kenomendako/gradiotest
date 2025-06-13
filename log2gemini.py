# -*- coding: utf-8 -*-
import gradio as gr
import os, sys, json, traceback, threading, time, pandas as pd
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

with gr.Blocks(theme=gr.themes.Soft(primary_hue="blue", secondary_hue="sky"), css=custom_css) as demo:
    # (State定義などは変更なし)
    # ...

    with gr.Accordion("🐦 アラーム設定", open=False) as alarm_accordion:
        # (Dataframe, 削除ボタンの定義は変更なし)
        # ...

        # --- アラーム関連イベントリスナー ---
        def load_and_set_df():
            df = ui_handlers.render_alarms_as_dataframe()
            return df, df

        demo.load(fn=load_and_set_df, outputs=[alarm_dataframe, alarm_dataframe_original_data])
        alarm_accordion.open(fn=load_and_set_df, outputs=[alarm_dataframe, alarm_dataframe_original_data])

        alarm_dataframe.change(
            fn=ui_handlers.handle_alarm_dataframe_change,
            inputs=[alarm_dataframe, alarm_dataframe_original_data],
            outputs=[alarm_dataframe_original_data]
        ).then(fn=ui_handlers.render_alarms_as_dataframe, outputs=alarm_dataframe)

        alarm_dataframe.select(
            fn=ui_handlers.handle_alarm_selection,
            inputs=[alarm_dataframe], outputs=[selected_alarm_ids_state], show_progress='hidden'
        )

        delete_alarm_button.click(
            fn=ui_handlers.handle_delete_selected_alarms,
            inputs=[selected_alarm_ids_state], outputs=[alarm_dataframe]
        ).then(fn=lambda: [], outputs=[selected_alarm_ids_state]).then(
            fn=load_and_set_df, outputs=[alarm_dataframe, alarm_dataframe_original_data]
        )

        def add_alarm_and_refresh(h, m, char, theme, prompt, days):
            alarm_manager.add_alarm(h, m, char, theme, prompt, days)
            df, _ = load_and_set_df()
            return df, df
        alarm_add_button.click(
            fn=add_alarm_and_refresh,
            inputs=[alarm_hour_dropdown, alarm_minute_dropdown, alarm_char_dropdown, alarm_theme_input, alarm_prompt_input, alarm_days_checkboxgroup],
            outputs=[alarm_dataframe, alarm_dataframe_original_data]
        ).then(
            fn=lambda char: ("08", "00", char, "", "", ["月", "火", "水", "木", "金", "土", "日"]),
            inputs=[current_character_name],
            outputs=[alarm_hour_dropdown, alarm_minute_dropdown, alarm_char_dropdown, alarm_theme_input, alarm_prompt_input, alarm_days_checkboxgroup]
        )
        # (他のリスナーも同様に省略)
    # ...
