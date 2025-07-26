# nexus_ark.py をこのコードで完全に置き換えてください

import os
import sys
import utils

os.environ["MEM0_TELEMETRY_ENABLED"] = "false"

if utils.acquire_lock():
    try:
        import gradio as gr
        import pandas as pd
        import config_manager, character_manager, ui_handlers, alarm_manager, gemini_api

        config_manager.load_config()
        alarm_manager.load_alarms()

        custom_css = """
    #chat_output_area pre { overflow-wrap: break-word !important; white-space: pre-wrap !important; word-break: break-word !important; }
    #chat_output_area .thoughts { background-color: #2f2f32; color: #E6E6E6; padding: 5px; border-radius: 5px; font-family: "Menlo", "Monaco", "Consolas", "Courier New", monospace; font-size: 0.8em; white-space: pre-wrap; word-break: break-word; overflow-wrap: break-word !important; }
    #memory_json_editor_code .cm-editor { max-height: 300px !important; overflow-y: auto !important; overflow-x: hidden !important; white-space: pre-wrap !important; word-break: break-word !important; overflow-wrap: break-word !important; }
    #notepad_editor_code textarea { max-height: 300px !important; overflow-y: auto !important; white-space: pre-wrap !important; word-break: break-word !important; overflow-wrap: break-word !important; box-sizing: border-box; }
    #memory_json_editor_code, #notepad_editor_code { max-height: 310px; border: 1px solid #ccc; border-radius: 5px; padding: 0; }
    #alarm_dataframe_display { border-radius: 8px !important; }
    #alarm_dataframe_display table { width: 100% !important; }
    #alarm_dataframe_display th, #alarm_dataframe_display td { text-align: left !important; padding: 4px 8px !important; white-space: normal !important; font-size: 0.95em; }
    #alarm_dataframe_display th:nth-child(1), #alarm_dataframe_display td:nth-child(1) { width: 50px !important; text-align: center !important; }
    #selection_feedback { font-size: 0.9em; color: #555; margin-top: 0px; margin-bottom: 5px; padding-left: 5px; }
    #token_count_display { text-align: right; font-size: 0.85em; color: #555; padding-right: 10px; margin-bottom: 5px; }
    #tpm_note_display { text-align: right; font-size: 0.75em; color: #777; padding-right: 10px; margin-bottom: -5px; margin-top: 0px; }
    """
        with gr.Blocks(theme=gr.themes.Soft(primary_hue="blue", secondary_hue="sky"), css=custom_css) as demo:
            # --- State定義 ---
            character_list_on_startup = character_manager.get_character_list()
            # ... (中略) ...
            send_scenery_state = gr.State(True)
            selected_message_state = gr.State(None)

            with gr.Row():
                with gr.Column(scale=1, min_width=300):
                    profile_image_display = gr.Image(...)
                    gr.Markdown("### キャラクター")
                    character_dropdown = gr.Dropdown(...)

                    with gr.Accordion("空間認識・移動", open=True):
                        current_location_display = gr.Textbox(label="現在の場所", interactive=False)
                        current_scenery_display = gr.Textbox(label="現在の情景描写", interactive=False, lines=3)
                        with gr.Row():
                            location_dropdown = gr.Dropdown(label="移動先を選択", interactive=True, scale=3)
                            change_location_button = gr.Button("移動", scale=1, variant="secondary")
                        update_scenery_button = gr.Button("情景を更新", variant="secondary")

                    with gr.Accordion("⚙️ 基本設定", open=False):
                        # ... send_scenery_checkbox を追加 ...

                    with gr.Accordion("📗 記憶とメモ帳の編集", open=False):
                        with gr.Tabs():
                            with gr.TabItem("記憶 (memory.json)"):
                                memory_json_editor = gr.Code(...)
                                with gr.Row():
                                    save_memory_button = gr.Button(value="想いを綴る", variant="primary")
                                    reload_memory_button = gr.Button(value="更新", variant="secondary")
                                    core_memory_update_button = gr.Button(value="コアメモリを更新", variant="primary")
                                    rag_update_button = gr.Button(value="手帳の索引を更新", variant="primary")
                            with gr.TabItem("メモ帳 (notepad.md)"):
                                # ...
                                save_notepad_button = gr.Button(value="メモ帳を保存", variant="primary")
                                # ...

                    with gr.Accordion("⏰ 時間管理", open=False):
                        # ...

                    with gr.Accordion("新しいキャラクターを迎える", open=False):
                        with gr.Row():
                            new_character_name_textbox = gr.Textbox(...)
                            add_character_button = gr.Button("迎える", variant="secondary")

                with gr.Column(scale=3):
                    # ... (右カラムのUI定義) ...

            # --- イベントリスナーの完全なリスト ---
            # ... (全ての.click, .change, .load をここに記述) ...

            # demo.load は outputs を13個持つ最終版に
            demo.load(
                fn=ui_handlers.handle_initial_load,
                inputs=[...], # 8個の引数
                outputs=[
                    alarm_dataframe, alarm_dataframe_original_data, chatbot_display,
                    profile_image_display, memory_json_editor, alarm_char_dropdown,
                    timer_char_dropdown, selection_feedback_markdown,
                    token_count_display, notepad_editor,
                    location_dropdown, current_location_display, current_scenery_display
                ]
            )

    except Exception as e:
        # ...
    finally:
        utils.release_lock()
