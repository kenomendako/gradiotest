# nexus_ark.py

import os
import sys
# psutil と json と pathlib は utils.py に移管したので、ここでは不要
# import json
# from pathlib import Path
# try:
#     import psutil
# except ImportError:
# ... (ここから既存のロック処理コードを全て削除) ...

# ★★★ ここからが新しいコード ★★★
import utils  # utilsをインポート

# グローバル・ロックの取得とメイン処理の実行
if utils.acquire_lock(): # ★★★ if文でメイン処理を囲む ★★★
    try:
        os.environ["MEM0_TELEMETRY_ENABLED"] = "false"
        import gradio as gr
        import traceback
        import threading
        import time
        import pandas as pd
        import config_manager, character_manager, memory_manager, alarm_manager, gemini_api, utils, ui_handlers
        config_manager.load_config()
        alarm_manager.load_alarms()

        # ... (custom_css や with gr.Blocks(...) など、元のメイン処理のすべてをこのtryブロックの中に含める) ...
        custom_css = """
    #chat_output_area pre { overflow-wrap: break-word !important; white-space: pre-wrap !important; word-break: break-word !important; }
    #chat_output_area .thoughts { background-color: #2f2f32; color: #E6E6E6; padding: 5px; border-radius: 5px; font-family: "Menlo", "Monaco", "Consolas", "Courier New", monospace; font-size: 0.8em; white-space: pre-wrap; word-break: break-word; overflow-wrap: break-word; }

    /* gr.Codeコンポーネント（記憶、ログ）用のスタイル */
    #memory_json_editor_code .cm-editor, #log_editor_code .cm-editor {
        max-height: 300px !important;
        overflow-y: auto !important;
        overflow-x: hidden !important;
        white-space: pre-wrap !important;
        word-break: break-word !important;
        overflow-wrap: break-word !important;
    }

    /* gr.Textboxコンポーネント（メモ帳）用のスタイル */
    #notepad_editor_code textarea { /* セレクタを textarea に変更 */
        max-height: 300px !important; /* 高さを他のエディタの .cm-editor に合わせる */
        overflow-y: auto !important;
        white-space: pre-wrap !important;
        word-break: break-word !important;
        overflow-wrap: break-word !important;
        box-sizing: border-box; /* paddingやborderが高さに含まれるように */
    }

    /* 全てのエディタの親コンテナのスタイル */
    #memory_json_editor_code, #log_editor_code, #notepad_editor_code {
        max-height: 310px;
        /* overflow: hidden; は削除済み */
        border: 1px solid #ccc;
        border-radius: 5px;
        padding: 0; /* Textboxが内部にpaddingを持つ場合があるので親は0に */
    }
    #alarm_dataframe_display { border-radius: 8px !important; }
    #alarm_dataframe_display table { width: 100% !important; }
    #alarm_dataframe_display th, #alarm_dataframe_display td { text-align: left !important; padding: 4px 8px !important; white-space: normal !important; font-size: 0.95em; }
    #alarm_dataframe_display th:nth-child(1), #alarm_dataframe_display td:nth-child(1) { width: 50px !important; text-align: center !important; }
    #selection_feedback { font-size: 0.9em; color: #555; margin-top: 0px; margin-bottom: 5px; padding-left: 5px; }
    #token_count_display { text-align: right; font-size: 0.85em; color: #555; padding-right: 10px; margin-bottom: -5px; } /* margin-bottomを調整 */
    #tpm_note_display { text-align: right; font-size: 0.75em; color: #777; padding-right: 10px; margin-bottom: -10px; margin-top: 0px; } /* 新しいスタイル */
    """
        with gr.Blocks(theme=gr.themes.Soft(primary_hue="blue", secondary_hue="sky"), css=custom_css) as demo:
            character_list_on_startup = character_manager.get_character_list()
            if not character_list_on_startup:
                character_manager.ensure_character_files("Default")
                character_list_on_startup = ["Default"]
            effective_initial_character = config_manager.initial_character_global
            if not effective_initial_character or effective_initial_character not in character_list_on_startup:
                new_char = character_list_on_startup[0] if character_list_on_startup else "Default"
                print(f"警告: 最後に使用したキャラクター '{effective_initial_character}' が見つからないか無効です。'{new_char}' で起動します。")
                effective_initial_character = new_char
                config_manager.save_config("last_character", new_char)
                if new_char == "Default" and "Default" not in character_list_on_startup:
                     character_manager.ensure_character_files("Default")
                     character_list_on_startup = ["Default"]
            current_character_name = gr.State(effective_initial_character)
            current_model_name = gr.State(config_manager.initial_model_global)
            current_api_key_name_state = gr.State(config_manager.initial_api_key_name_global)
            send_thoughts_state = gr.State(config_manager.initial_send_thoughts_to_api_global)
            api_history_limit_state = gr.State(config_manager.initial_api_history_limit_option_global)
            alarm_dataframe_original_data = gr.State(pd.DataFrame())
            selected_alarm_ids_state = gr.State([])
            editing_alarm_id_state = gr.State(None)
            send_notepad_state = gr.State(True)
            use_common_prompt_state = gr.State(True) # ★ デフォルトでON
            with gr.Row():
                with gr.Column(scale=1, min_width=300):
                    profile_image_display = gr.Image(height=150, width=150, interactive=False, show_label=False, container=False)
                    gr.Markdown("### キャラクター")
                    character_dropdown = gr.Dropdown(choices=character_list_on_startup, value=effective_initial_character, label="キャラクターを選択", interactive=True)
                    with gr.Row():
                        new_character_name_textbox = gr.Textbox(placeholder="新しいキャラクター名", show_label=False, scale=3)
                        add_character_button = gr.Button("迎える", variant="secondary", scale=1)
                    with gr.Accordion("⚙️ 基本設定", open=False):
                        model_dropdown = gr.Dropdown(choices=config_manager.AVAILABLE_MODELS_GLOBAL, value=config_manager.initial_model_global, label="使用するAIモデル", interactive=True)
                        api_key_dropdown = gr.Dropdown(choices=list(config_manager.API_KEYS.keys()), value=config_manager.initial_api_key_name_global, label="使用するAPIキー", interactive=True)
                        api_history_limit_dropdown = gr.Dropdown(choices=list(config_manager.API_HISTORY_LIMIT_OPTIONS.values()), value=config_manager.API_HISTORY_LIMIT_OPTIONS.get(config_manager.initial_api_history_limit_option_global, "全ログ"), label="APIへの履歴送信", interactive=True)
                        add_timestamp_checkbox = gr.Checkbox(value=config_manager.initial_add_timestamp_global, label="メッセージにタイムスタンプを追加", interactive=True)
                        send_thoughts_checkbox = gr.Checkbox(value=config_manager.initial_send_thoughts_to_api_global, label="思考過程をAPIに送信", interactive=True)
                        send_notepad_checkbox = gr.Checkbox(value=True, label="メモ帳の内容をAPIに送信", interactive=True)
                        use_common_prompt_checkbox = gr.Checkbox(value=True, label="共通ツールプロンプトを注入", interactive=True) # ★ UI追加
                    with gr.Accordion("📗 記憶とログの編集", open=False):
                        with gr.Tabs():
                            with gr.TabItem("記憶 (memory.json)"):
                                memory_json_editor = gr.Code(label="記憶データ", language="json", interactive=True, elem_id="memory_json_editor_code")
                                with gr.Row():
                                    save_memory_button = gr.Button(value="想いを綴る", variant="secondary")
                                    core_memory_update_button = gr.Button(value="コアメモリを更新", variant="primary") # ★ 追加
                                    rag_update_button = gr.Button(value="手帳の索引を更新", variant="secondary") # variant を secondary に
                            with gr.TabItem("メモ帳 (notepad.md)"):
                                notepad_editor = gr.Textbox(
                                    label="メモ帳の内容",
                                    interactive=True,
                                    elem_id="notepad_editor_code",
                                    lines=15, # 高さを他のエディタと合わせる
                                    autoscroll=True
                                )
                                with gr.Row():
                                    save_notepad_button = gr.Button(value="メモ帳を保存", variant="secondary")
                                    reload_notepad_button = gr.Button(value="再読込", variant="secondary")
                                    clear_notepad_button = gr.Button(value="メモ帳を全削除", variant="stop")
                            with gr.TabItem("ログ (log.txt)"):
                                log_editor = gr.Code(label="ログ内容", interactive=True, elem_id="log_editor_code")
                                with gr.Row():
                                    save_log_button = gr.Button(value="ログを保存", variant="secondary")
                                    editor_reload_button = gr.Button(value="ログ再読込", variant="secondary")
                    with gr.Accordion("⏰ 時間管理", open=False):
                        with gr.Tabs():
                            with gr.TabItem("アラーム"):
                                gr.Markdown("ℹ️ **操作方法**: リストから操作したいアラームの行を選択し、下のボタンで操作します。")
                                alarm_dataframe = gr.Dataframe(headers=["状態", "時刻", "曜日", "キャラ", "テーマ"], datatype=["bool", "str", "str", "str", "str"], interactive=True, row_count=(5, "dynamic"), col_count=5, wrap=True, elem_id="alarm_dataframe_display")
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
                                alarm_days_checkboxgroup = gr.CheckboxGroup(choices=["月", "火", "水", "木", "金", "土", "日"], label="曜日", value=["月", "火", "水", "木", "金", "土", "日"])
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
                with gr.Column(scale=3): # 右側のチャットカラム
                    chatbot_display = gr.Chatbot(type="messages", height=600, elem_id="chat_output_area", show_copy_button=True)
                    chat_input_textbox = gr.Textbox(show_label=False, placeholder="メッセージを入力...", lines=3)

                    token_count_display = gr.Markdown("入力トークン数", elem_id="token_count_display")

                    # ▼▼▼ TPM注釈表示エリアを追加 ▼▼▼
                    tpm_note_display = gr.Markdown("(参考: Gemini 2.5 シリーズ無料枠TPM: 250,000)", elem_id="tpm_note_display")
                    # ▲▲▲ 追加ここまで ▲▲▲

                    with gr.Row():
                        submit_button = gr.Button("送信", variant="primary", scale=4)
                        chat_reload_button = gr.Button("🔄 更新", scale=1)
                    allowed_file_types = ['.png', '.jpg', '.jpeg', '.webp', '.heic', '.heif', '.mp3', '.wav', '.flac', '.aac', '.mp4', '.mov', '.avi', '.webm', '.txt', '.md', '.py', '.js', '.html', '.css', '.pdf', '.xml', '.json']
                    file_upload_button = gr.Files(label="ファイル添付", type="filepath", file_count="multiple", file_types=allowed_file_types)
                    gr.Markdown(f"ℹ️ *複数のファイルを添付できます。対応形式: {', '.join(allowed_file_types)}*")

            # ★★★ トークン計算関連の定義を with gr.Blocks の内側に移動 ★★★
            token_calc_inputs = [
                chat_input_textbox,
                file_upload_button,
                current_character_name,
                current_model_name,
                current_api_key_name_state,
                api_history_limit_state,
        send_notepad_state,
        notepad_editor,
        use_common_prompt_state # ★★★ ここに追加 ★★★
            ]
            token_calc_outputs = token_count_display

            def setup_token_update_events():
                chat_input_textbox.change(fn=ui_handlers.update_token_count, inputs=token_calc_inputs, outputs=token_calc_outputs, show_progress=False)
                file_upload_button.upload(fn=ui_handlers.update_token_count, inputs=token_calc_inputs, outputs=token_calc_outputs)
                file_upload_button.clear(fn=ui_handlers.update_token_count, inputs=token_calc_inputs, outputs=token_calc_outputs)
                notepad_editor.change(fn=ui_handlers.update_token_count, inputs=token_calc_inputs, outputs=token_calc_outputs, show_progress=False) # ★★★ 追加 ★★★

            add_character_button.click(fn=ui_handlers.handle_add_new_character, inputs=[new_character_name_textbox], outputs=[character_dropdown, alarm_char_dropdown, timer_char_dropdown, new_character_name_textbox])
            # initial_load 関数の定義を修正
            # ★★★ 引数の最後に use_common_prompt_state を追加 ★★★
            def initial_load(char_name_to_load, api_history_limit, current_send_notepad_state, use_common_prompt_state):
                df_with_ids = ui_handlers.render_alarms_as_dataframe()
                display_df = ui_handlers.get_display_df(df_with_ids)
                (returned_char_name, current_chat_hist, _, current_profile_img,
                 current_mem_str, alarm_dd_char_val, current_log_content, timer_dd_char_val,
                 current_notepad_content
                ) = ui_handlers.update_ui_on_character_change(char_name_to_load, api_history_limit)

                # ▼▼▼ update_token_count の呼び出しを修正 ▼▼▼
                initial_token_str = ui_handlers.update_token_count(
                    None, None, returned_char_name,
                    config_manager.initial_model_global,
                    config_manager.initial_api_key_name_global,
                    api_history_limit,
                    current_send_notepad_state,
                    current_notepad_content,
                    use_common_prompt_state # ★★★ 最後の引数として、受け取った値を追加 ★★★
                )
                # ▲▲▲ 修正ここまで ▲▲▲

                return (display_df, df_with_ids, current_chat_hist, current_log_content,
                        current_mem_str, current_profile_img, alarm_dd_char_val,
                        timer_dd_char_val, "アラームを選択してください", initial_token_str,
                        current_notepad_content
                       )

            # demo.load の呼び出しを修正
            demo.load(
                fn=initial_load,
                # ★★★ inputs に use_common_prompt_state を追加 ★★★
                inputs=[current_character_name, api_history_limit_state, send_notepad_state, use_common_prompt_state],
                outputs=[
                    alarm_dataframe, alarm_dataframe_original_data, chatbot_display, log_editor, memory_json_editor,
                    profile_image_display, alarm_char_dropdown, timer_char_dropdown, selection_feedback_markdown,
                    token_count_display, notepad_editor # ★ notepad_editor を outputs に追加
                ]
            )

            alarm_dataframe.select(fn=ui_handlers.handle_alarm_selection_and_feedback, inputs=[alarm_dataframe_original_data], outputs=[selected_alarm_ids_state, selection_feedback_markdown], show_progress='hidden').then(fn=ui_handlers.load_alarm_to_form, inputs=[selected_alarm_ids_state], outputs=[alarm_add_button, alarm_theme_input, alarm_prompt_input, alarm_char_dropdown, alarm_days_checkboxgroup, alarm_hour_dropdown, alarm_minute_dropdown, editing_alarm_id_state])
            enable_button.click(fn=lambda ids: ui_handlers.toggle_selected_alarms_status(ids, True), inputs=[selected_alarm_ids_state], outputs=[alarm_dataframe_original_data]).then(fn=lambda df: ui_handlers.get_display_df(df), inputs=[alarm_dataframe_original_data], outputs=[alarm_dataframe])
            disable_button.click(fn=lambda ids: ui_handlers.toggle_selected_alarms_status(ids, False), inputs=[selected_alarm_ids_state], outputs=[alarm_dataframe_original_data]).then(fn=lambda df: ui_handlers.get_display_df(df), inputs=[alarm_dataframe_original_data], outputs=[alarm_dataframe])
            delete_alarm_button.click(fn=ui_handlers.handle_delete_selected_alarms, inputs=[selected_alarm_ids_state], outputs=[alarm_dataframe_original_data]).then(fn=lambda id_df: ui_handlers.get_display_df(id_df), inputs=[alarm_dataframe_original_data], outputs=[alarm_dataframe]).then(fn=lambda: ([], "アラームを選択してください"), outputs=[selected_alarm_ids_state, selection_feedback_markdown])
            alarm_add_button.click(fn=ui_handlers.handle_add_or_update_alarm, inputs=[editing_alarm_id_state, alarm_hour_dropdown, alarm_minute_dropdown, alarm_char_dropdown, alarm_theme_input, alarm_prompt_input, alarm_days_checkboxgroup], outputs=[alarm_dataframe, alarm_dataframe_original_data, alarm_add_button, alarm_theme_input, alarm_prompt_input, alarm_char_dropdown, alarm_days_checkboxgroup, alarm_hour_dropdown, alarm_minute_dropdown, editing_alarm_id_state])
            # character_dropdown.change の outputs に notepad_editor を追加, また .then で呼び出す update_token_count も token_calc_inputs を使うので自動対応
            character_dropdown.change(fn=ui_handlers.update_ui_on_character_change, inputs=[character_dropdown, api_history_limit_state], outputs=[current_character_name, chatbot_display, chat_input_textbox, profile_image_display, memory_json_editor, alarm_char_dropdown, log_editor, timer_char_dropdown, notepad_editor]).then(fn=lambda: (ui_handlers.get_display_df(ui_handlers.render_alarms_as_dataframe()), ui_handlers.render_alarms_as_dataframe()), outputs=[alarm_dataframe, alarm_dataframe_original_data]).then(fn=ui_handlers.update_token_count, inputs=token_calc_inputs, outputs=token_calc_outputs)
            timer_type_radio.change(fn=lambda t: (gr.update(visible=t=="通常タイマー"), gr.update(visible=t=="ポモドーロタイマー"), ""), inputs=[timer_type_radio], outputs=[normal_timer_ui, pomo_timer_ui, timer_status_output])
            model_dropdown.change(fn=ui_handlers.update_model_state, inputs=[model_dropdown], outputs=[current_model_name]).then(fn=ui_handlers.update_token_count, inputs=token_calc_inputs, outputs=token_calc_outputs) # token_calc_inputs を使用
            api_key_dropdown.change(fn=ui_handlers.update_api_key_state, inputs=[api_key_dropdown], outputs=[current_api_key_name_state]).then(fn=ui_handlers.update_token_count, inputs=token_calc_inputs, outputs=token_calc_outputs) # token_calc_inputs を使用
            add_timestamp_checkbox.change(fn=ui_handlers.update_timestamp_state, inputs=[add_timestamp_checkbox], outputs=[])
            send_thoughts_checkbox.change(fn=ui_handlers.update_send_thoughts_state, inputs=[send_thoughts_checkbox], outputs=[send_thoughts_state])
            # ★★★ send_notepad_checkbox のイベントを接続 ★★★
            send_notepad_checkbox.change(
                fn=ui_handlers.update_send_notepad_state,
                inputs=[send_notepad_checkbox],
                outputs=[send_notepad_state]
            ).then( # thenで繋げて、状態変更後すぐにトークン数を更新する
                fn=ui_handlers.update_token_count,
                inputs=token_calc_inputs, # token_calc_inputs を使用
                outputs=token_calc_outputs
            )
            # ★★★ use_common_prompt_checkbox のイベントを接続 ★★★
            use_common_prompt_checkbox.change(
                fn=ui_handlers.update_use_common_prompt_state,
                inputs=[use_common_prompt_checkbox],
                outputs=[use_common_prompt_state]
            ).then(
                fn=ui_handlers.update_token_count,
                inputs=token_calc_inputs, # token_calc_inputs を使用 (自動で use_common_prompt_state を含む)
                outputs=token_calc_outputs
            )
            api_history_limit_dropdown.change(fn=ui_handlers.update_api_history_limit_state_and_reload_chat, inputs=[api_history_limit_dropdown, current_character_name], outputs=[api_history_limit_state, chatbot_display, log_editor]).then(fn=ui_handlers.update_token_count, inputs=token_calc_inputs, outputs=token_calc_outputs) # token_calc_inputs を使用
            memory_json_editor.change(
                fn=lambda: gr.update(variant="primary"),
                inputs=None,
                outputs=[save_memory_button]
            )
            save_memory_button.click(
                fn=ui_handlers.handle_save_memory_click,
                inputs=[current_character_name, memory_json_editor],
                outputs=[memory_json_editor]
            ).then(
                fn=lambda: gr.update(variant="secondary"),
                inputs=None,
                outputs=[save_memory_button]
            )
            # ★ メモ帳関連のボタンイベントを追加 (前回までの修正)
            save_notepad_button.click(fn=ui_handlers.handle_save_notepad_click, inputs=[current_character_name, notepad_editor], outputs=[notepad_editor]) # ★ outputs追加
            reload_notepad_button.click(fn=ui_handlers.handle_reload_notepad, inputs=[current_character_name], outputs=[notepad_editor])
            clear_notepad_button.click(fn=ui_handlers.handle_clear_notepad_click, inputs=[current_character_name], outputs=[notepad_editor])
            save_log_button.click(fn=ui_handlers.handle_save_log_button_click, inputs=[current_character_name, log_editor])
            editor_reload_button.click(fn=ui_handlers.reload_chat_log, inputs=[current_character_name, api_history_limit_state], outputs=[chatbot_display, log_editor])
            chat_reload_button.click(fn=ui_handlers.reload_chat_log, inputs=[current_character_name, api_history_limit_state], outputs=[chatbot_display, log_editor])
            chat_submit_outputs = [chatbot_display, chat_input_textbox, file_upload_button, token_count_display]
            chat_inputs = [
                chat_input_textbox, chatbot_display, current_character_name, current_model_name,
                current_api_key_name_state, file_upload_button, add_timestamp_checkbox,
                send_thoughts_state, api_history_limit_state,
                send_notepad_state,
                use_common_prompt_state # ★★★ ここに追加 ★★★
            ]
            chat_input_textbox.submit(fn=ui_handlers.handle_message_submission, inputs=chat_inputs, outputs=chat_submit_outputs)
            submit_button.click(fn=ui_handlers.handle_message_submission, inputs=chat_inputs, outputs=chat_submit_outputs)
            setup_token_update_events()
            timer_submit_button.click(fn=ui_handlers.handle_timer_submission, inputs=[timer_type_radio, timer_duration_number, pomo_work_number, pomo_break_number, pomo_cycles_number, timer_char_dropdown, timer_work_theme_input, timer_break_theme_input, api_key_dropdown, gr.State(config_manager.initial_notification_webhook_url_global), normal_timer_theme_input], outputs=[timer_status_output])
            rag_update_button.click(fn=ui_handlers.handle_rag_update_button_click, inputs=[current_character_name, current_api_key_name_state], outputs=None)
            core_memory_update_button.click(fn=ui_handlers.handle_core_memory_update_click, inputs=[current_character_name, current_api_key_name_state], outputs=None)
            demo.load(fn=alarm_manager.start_alarm_scheduler_thread, inputs=None, outputs=None)
        if __name__ == "__main__":
            print("\n" + "="*60)
            print("アプリケーションを起動します...")
            print(f"起動後、以下のURLでアクセスしてください。")
            print("")
            print(f"  【PCからアクセスする場合】")
            print(f"  http://127.0.0.1:7860")
            print("")
            print("  【スマホからアクセスする場合（PCと同じWi-Fiに接続してください）】")
            print(f"  http://<お使いのPCのIPアドレス>:7860")
            print("  (IPアドレスが分からない場合は、PCのコマンドプロンプトやターミナルで")
            print("   `ipconfig` (Windows) または `ifconfig` (Mac/Linux) と入力して確認できます)")
            print("="*60 + "\n")
            demo.queue().launch(server_name="0.0.0.0", server_port=7860, share=False, allowed_paths=["."])

    finally:
        utils.release_lock()
# ★★★ ロック取得に失敗した場合は、このifブロックが実行されず、スクリプトが静かに正常終了する ★★★
