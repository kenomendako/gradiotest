import gradio as gr
import os
import sys
import json
import traceback
import threading
import time
import pandas as pd # Kisekiが追加
# google.api_core.exceptions は直接使われていないようなので一旦コメントアウト (必要なら復活)
# import google.api_core.exceptions

# --- 分割したモジュールをインポート ---
import config_manager
import character_manager
import memory_manager
import alarm_manager # アラームマネージャは引き続き使用
import gemini_api
import utils
import ui_handlers # ui_handlers.py の関数を呼び出すために必要
# Kiseki: 以下の行はui_handlers.pyに新しい関数が定義されたので、ここでの直接インポートは不要になるか、
# ui_handlers.<function_name> の形で呼び出す。ここでは直接インポートする形を維持。
from ui_handlers import (
    handle_timer_submission,
    render_alarms_as_dataframe,
    handle_alarm_dataframe_change,
    handle_alarm_selection,
    handle_delete_selected_alarms
)


# --- 定数 (UI関連) ---
HISTORY_LIMIT = config_manager.HISTORY_LIMIT

# --- Gradio アプリケーションの構築 ---
# (custom_css は変更なしのため省略)
custom_css = """
#chat_output_area pre {
    overflow-wrap: break-word !important;
    white-space: pre-wrap !important;
    word-break: break-word !important;
}
#chat_output_area .thoughts {
    background-color: #2f2f32;
    color: #E6E6E6;
    padding: 5px;
    border-radius: 5px;
    font-family: "Menlo", "Monaco", "Consolas", "Courier New", monospace;
    font-size: 0.8em;
    white-space: pre-wrap;
    word-break: break-word;
    overflow-wrap: break-word;
}
#chat_output_area .thoughts pre {
    white-space: pre-wrap !important;
    word-break: break-word !important;
    overflow-wrap: break-word !important;
}
#chat_output_area .thoughts pre code {
    white-space: pre-wrap !important;
    word-break: break-word !important;
    overflow-wrap: break-word !important;
    display: block !important;
    width: 100% !important;
}
#memory_json_editor_code .cm-editor, #log_editor_code .cm-editor { max-height: 300px !important; overflow-y: auto !important; }
#memory_json_editor_code, #log_editor_code { max-height: 310px; overflow: hidden; border: 1px solid #ccc; border-radius: 5px; }
#help_accordion code { background-color: #eee; padding: 2px 4px; border-radius: 3px; font-size: 0.9em; }
.time-dropdown-container label { margin-bottom: 2px !important; font-size: 0.9em; }
.time-dropdown-container > div { margin-bottom: 5px !important; }
/* Kiseki: アラームDataframe用のCSSを追加 */
#alarm_dataframe_display .gr-checkbox label { margin-bottom: 0 !important; } /* チェックボックスのラベル下マージン調整 */
#alarm_dataframe_display { border-radius: 8px !important; }
#alarm_dataframe_display table { width: 100% !important; }
#alarm_dataframe_display th, #alarm_dataframe_display td { text-align: left !important; padding: 4px 8px !important; }
#alarm_dataframe_display th:nth-child(1), #alarm_dataframe_display td:nth-child(1) { width: 60px !important; text-align: center !important; } /* 状態 */
#alarm_dataframe_display th:nth-child(2), #alarm_dataframe_display td:nth-child(2) { width: 70px !important; } /* 時刻 */
#alarm_dataframe_display th:nth-child(3), #alarm_dataframe_display td:nth-child(3) { width: 100px !important; } /* 曜日 */
#alarm_dataframe_display th:nth-child(4), #alarm_dataframe_display td:nth-child(4) { width: 120px !important; } /* キャラ */
#alarm_dataframe_display th:nth-child(5), #alarm_dataframe_display td:nth-child(5) { width: auto !important; } /* テーマ */
"""

# --- 起動シーケンス ---
print("設定ファイルを読み込んでいます...")
try:
    config_manager.load_config()
except Exception as e:
    print(f"設定ファイルの読み込み中に致命的なエラーが発生しました: {e}")
    traceback.print_exc()
    sys.exit("設定ファイルの読み込みエラーにより終了。")

initial_api_key_configured = False
init_api_error = "初期APIキー名が設定されていません。"
if config_manager.initial_api_key_name_global:
    initial_api_key_configured, init_api_error = gemini_api.configure_google_api(config_manager.initial_api_key_name_global)
    if not initial_api_key_configured:
        print(f"\n !!! 警告: 初期APIキー '{config_manager.initial_api_key_name_global}' の設定に失敗しました: {init_api_error} !!!")
    else:
        print(f"初期APIキー '{config_manager.initial_api_key_name_global}' の設定に成功しました。")
elif not config_manager.API_KEYS:
     print(f"\n !!! 警告: {config_manager.CONFIG_FILE} にAPIキーが設定されていません ('api_keys')。 !!!")
else:
    print(f"\n !!! 警告: {config_manager.CONFIG_FILE} 内に有効なデフォルトAPIキー名が見つかりません。 !!!")

print("アラームデータを読み込んでいます...")
alarm_manager.load_alarms()


with gr.Blocks(theme=gr.themes.Soft(primary_hue="blue", secondary_hue="sky"), css=custom_css) as demo:
    character_list_on_startup = character_manager.get_character_list()
    startup_ready = all([
        character_list_on_startup,
        config_manager.initial_character_global and config_manager.initial_character_global in character_list_on_startup,
        config_manager.AVAILABLE_MODELS_GLOBAL,
        config_manager.initial_model_global and config_manager.initial_model_global in config_manager.AVAILABLE_MODELS_GLOBAL,
        config_manager.API_KEYS,
        config_manager.initial_api_history_limit_option_global and config_manager.initial_api_history_limit_option_global in config_manager.API_HISTORY_LIMIT_OPTIONS,
        config_manager.initial_alarm_model_global,
        isinstance(config_manager.initial_alarm_api_history_turns_global, int)
    ])

    if not startup_ready:
        error_details = []
        if not character_list_on_startup: error_details.append(f"キャラクターが見つかりません。`{config_manager.CHARACTERS_DIR}` 確認。")
        # (他のエラーチェックも同様に追加)
        # Kiseki: エラー詳細の拡充
        if not config_manager.initial_character_global or config_manager.initial_character_global not in character_list_on_startup : error_details.append(f"config.jsonのlast_character ('{config_manager.initial_character_global}') が無効。")
        if not config_manager.AVAILABLE_MODELS_GLOBAL : error_details.append("config.jsonにavailable_models未設定。")
        elif not config_manager.initial_model_global or config_manager.initial_model_global not in config_manager.AVAILABLE_MODELS_GLOBAL : error_details.append(f"config.jsonのlast_model ('{config_manager.initial_model_global}') がavailable_modelsにない。")
        if not config_manager.API_KEYS : error_details.append("config.jsonにapi_keys未設定。")
        if not config_manager.initial_api_history_limit_option_global or config_manager.initial_api_history_limit_option_global not in config_manager.API_HISTORY_LIMIT_OPTIONS : error_details.append(f"config.jsonのlast_api_history_limit_option ('{config_manager.initial_api_history_limit_option_global}') が無効。")
        if not config_manager.initial_alarm_model_global : error_details.append("config.jsonにalarm_model未設定。")
        if not isinstance(config_manager.initial_alarm_api_history_turns_global, int) : error_details.append("config.jsonのalarm_api_history_turnsが整数でない。")

        print("\n" + "="*40 + "\n !!! 起動に必要な設定が不足しています !!!\n" + "="*40) # Kiseki: コンソールにもエラー出力
        for detail in error_details: print(f"- {detail}")
        print("\n詳細はコンソールログおよび config.json を確認してください。\nGradio UIは表示されません。")

        gr.Markdown(f"## 起動エラー\n設定不足です。\n\n{chr(10).join(['- ' + item for item in error_details])}\n\n`{config_manager.CONFIG_FILE}`を確認し再起動してください。")
    else:
        current_character_name = gr.State(config_manager.initial_character_global)
        current_model_name = gr.State(config_manager.initial_model_global)
        current_api_key_name_state = gr.State(config_manager.initial_api_key_name_global)
        send_thoughts_state = gr.State(config_manager.initial_send_thoughts_to_api_global)
        api_history_limit_state = gr.State(config_manager.initial_api_history_limit_option_global)

        alarm_dataframe_original_data = gr.State(pd.DataFrame(columns=["ID", "状態", "時刻", "曜日", "キャラ", "テーマ"]))
        selected_alarm_ids_state = gr.State([]) # Kiseki: selected_alarm_ids_state をここで定義


        gr.Markdown("# AI Chat with Gradio & Gemini")

        with gr.Row():
            with gr.Column(scale=1, min_width=300):
                gr.Markdown("### キャラクター")
                character_dropdown = gr.Dropdown(choices=character_list_on_startup, value=config_manager.initial_character_global, label="キャラクターを選択", interactive=True)

                def get_initial_profile_image(char_name):
                    if not char_name: return None
                    _, _, img_path, _ = character_manager.get_character_files_paths(char_name); return img_path
                profile_image_display = gr.Image(value=get_initial_profile_image(config_manager.initial_character_global), height=150, width=150, interactive=False, show_label=False, container=False)

                with gr.Accordion("⚙️ 基本設定", open=False):
                    model_dropdown = gr.Dropdown(choices=config_manager.AVAILABLE_MODELS_GLOBAL, value=config_manager.initial_model_global, label="使用するAIモデル", interactive=True)
                    api_key_dropdown = gr.Dropdown(choices=list(config_manager.API_KEYS.keys()), value=config_manager.initial_api_key_name_global, label="使用するAPIキー", info=f"{config_manager.CONFIG_FILE}で設定", interactive=True)
                    api_history_limit_dropdown = gr.Dropdown(choices=list(config_manager.API_HISTORY_LIMIT_OPTIONS.values()), value=config_manager.API_HISTORY_LIMIT_OPTIONS.get(config_manager.initial_api_history_limit_option_global), label="APIへの履歴送信 (通常対話)", info="対話時のトークン量を調整", interactive=True)
                    send_thoughts_checkbox = gr.Checkbox(value=config_manager.initial_send_thoughts_to_api_global, label="思考過程をAPIに送信", info="OFFでトークン削減可能", interactive=True)

                with gr.Accordion(f"📗 キャラクターの記憶 ({config_manager.MEMORY_FILENAME})", open=False):
                    def get_initial_memory_data_str(char_name: str) -> str:
                         if not char_name: return "{}"
                         _, _, _, mem_path = character_manager.get_character_files_paths(char_name)
                         mem_data = memory_manager.load_memory_data_safe(mem_path)
                         return json.dumps(mem_data, indent=2, ensure_ascii=False) if isinstance(mem_data, dict) else json.dumps({"error": "Failed to load"}, indent=2)
                    memory_json_editor = gr.Code(value=get_initial_memory_data_str(config_manager.initial_character_global), label="記憶データ (JSON形式で編集)", language="json", interactive=True, elem_id="memory_json_editor_code")
                    save_memory_button = gr.Button(value="想いを綴る", variant="secondary")

                with gr.Accordion("📗 チャットログ編集 (`log.txt`)", open=False):
                    def get_initial_log_data_str(char_name: str) -> str:
                        if not char_name: return "キャラクターを選択してください。"
                        log_f, _, _, _ = character_manager.get_character_files_paths(char_name)
                        if log_f and os.path.exists(log_f):
                            try:
                                with open(log_f, "r", encoding="utf-8") as f: return f.read()
                            except Exception as e: return f"ログファイルの読み込みに失敗しました: {e}"
                        return "" if log_f else "キャラクターのログファイルパスが見つかりません。"
                    log_editor = gr.Code(label="ログ内容 (直接編集可能)", value=get_initial_log_data_str(config_manager.initial_character_global), interactive=True, elem_id="log_editor_code")
                    save_log_button = gr.Button(value="ログを保存", variant="secondary")

                with gr.Accordion("🐦 アラーム設定", open=False) as alarm_accordion:
                    alarm_display_headers = ["状態", "時刻", "曜日", "キャラ", "テーマ"]
                    alarm_dataframe = gr.Dataframe(
                        headers=alarm_display_headers,
                        datatype=["bool", "str", "str", "str", "str"],
                        interactive=True, # Kiseki: interactive=True のまま (チェックボックス操作のため)
                        row_count=(0, "dynamic"),
                        col_count=(len(alarm_display_headers), "fixed"),
                        wrap=True,
                        elem_id="alarm_dataframe_display"
                        # Kiseki: multiselect=True は削除済みの想定
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
                    timer_duration_input = gr.Number(label="タイマー時間 (分)", value=1, interactive=True, visible=True)
                    normal_timer_theme_input = gr.Textbox(label="通常タイマーのテーマ", placeholder="例: タイマー終了！", lines=2, interactive=True, visible=True)
                    work_duration_input = gr.Number(label="作業時間 (分)", value=25, interactive=True, visible=False)
                    break_duration_input = gr.Number(label="休憩時間 (分)", value=5, interactive=True, visible=False)
                    cycles_input = gr.Number(label="サイクル数", value=4, interactive=True, visible=False)
                    work_theme_input = gr.Textbox(label="作業テーマ", placeholder="例: 集中して作業しよう！", lines=2, interactive=True, visible=False)
                    break_theme_input = gr.Textbox(label="休憩テーマ", placeholder="例: リラックスして休憩しよう！", lines=2, interactive=True, visible=False)
                    def update_timer_inputs(timer_type):
                        is_normal = timer_type == "通常タイマー"
                        return gr.update(visible=is_normal), gr.update(visible=is_normal), gr.update(visible=not is_normal), gr.update(visible=not is_normal), gr.update(visible=not is_normal), gr.update(visible=not is_normal), gr.update(visible=not is_normal)
                    timer_type_dropdown.change(fn=update_timer_inputs, inputs=[timer_type_dropdown], outputs=[timer_duration_input, normal_timer_theme_input, work_duration_input, break_duration_input, cycles_input, work_theme_input, break_theme_input])
                    timer_character_dropdown = gr.Dropdown(label="キャラクター", choices=character_list_on_startup, value=config_manager.initial_character_global, interactive=True)
                    timer_status_output = gr.Textbox(label="タイマー設定状況", interactive=False, placeholder="ここに設定内容が表示されます。")
                    timer_submit_button = gr.Button("タイマー開始")


                with gr.Accordion("ℹ️ ヘルプ", open=False, elem_id="help_accordion"):
                     gr.Markdown(f"""
                        ### 基本操作
                        - 左上でキャラクター、AIモデル、APIキーを選択します。
                        - 右下のテキストボックスにメッセージを入力し、「送信」ボタンまたは `Shift+Enter` で送信します。
                        - 「画像を添付」で画像をアップロードまたはペーストして、テキストと一緒に送信できます。
                        - 「タイムスタンプ付加」にチェックを入れると、送信メッセージの末尾に日時が追加されます。

                        ### 設定項目 (`{config_manager.CONFIG_FILE}`)
                        - `api_keys`: Google AI Studio等で取得したAPIキーを `{{"キー名": "実際のキー"}}` の形式で追加します。
                        - `available_models`: 使用したいGeminiモデル名をリストで指定します (例: `["gemini-1.5-pro-latest", "gemini-1.5-flash-latest"]`)。
                        - `default_model`, `default_api_key_name`: 起動時にデフォルトで選択されるモデルとAPIキーの名前。
                        - `add_timestamp`: タイムスタンプ付加機能のデフォルトON/OFF。
                        - `last_send_thoughts_to_api`: 思考過程をAPIに送るかのデフォルト設定。OFFでトークン節約。
                        - `last_api_history_limit_option`: 通常対話時にAPIへ送る履歴量のデフォルト（"10"～"60", "all"）。
                        - `alarm_model`: アラーム通知の応答生成に使用するモデル名（Flash推奨）。
                        - `alarm_api_history_turns`: アラーム応答生成時に参照する会話履歴の往復数（0で履歴参照なし）。
                        - `notification_webhook_url`: アラーム通知を送るWebhook URL (Google Chat, Slack等)。`null` または `""` で無効。

                        ### キャラクター設定 (`{config_manager.CHARACTERS_DIR}/<キャラ名>/`)
                        - `SystemPrompt.txt`: キャラクターの性格や応答指示を記述します。思考過程指示 (`【Thoughts】...【/Thoughts】`) もここに含めます。
                        - `{config_manager.MEMORY_FILENAME}`: キャラクターの記憶データ。UIの「記憶」欄で編集・保存できます。
                        - `log.txt`: 会話履歴。アラーム通知もここに記録されます。
                        - `{config_manager.PROFILE_IMAGE_FILENAME}`: キャラクター画像 (任意)。

                        ### アラーム機能 (New Dataframe UI)
                        - 「🐦 アラーム設定」アコーディオン内で設定します。
                        - **表示**: 設定済みのアラームが表形式（Dataframe）で表示されます。「状態」列のチェックボックスでアラームの有効/無効を切り替えられます。変更は即座に保存されます。
                        - **追加**: 下部のフォームに時刻、キャラクター、テーマなどを入力し「アラームを追加」ボタンで新規アラームを登録します。
                        - **削除**: Dataframeの行を選択 (クリック) し、「選択したアラームを削除」ボタンを押すと、選択されたアラームが削除されます。(現状、単行選択のみ対応の可能性あり。複数行選択して一括削除する挙動はGradioのバージョンや設定に依存します。)
                        - **ID列**: アラームのユニークIDは内部データとして保持されますが、UIの表には表示されません。
                        - 時刻になると、指定キャラがテーマに基づいたメッセージを生成し、ログに記録、Webhook通知（設定時）を行います。
                        - 応答生成には軽量モデル (`alarm_model`) と短い履歴 (`alarm_api_history_turns`) が参照され、記憶も参照されます。

                        *注意:* Webhook URLは `{config_manager.CONFIG_FILE}` に直接記述するため、ファイルの取り扱いには十分注意してください。
                        """)


            with gr.Column(scale=3): # 右カラム
                gr.Markdown(f"### チャット (UI表示: 最新{HISTORY_LIMIT}往復)")
                def load_initial_history_formatted(char_name):
                    if not char_name: return []
                    log_file, _, _, _ = character_manager.get_character_files_paths(char_name)
                    return utils.format_history_for_gradio(utils.load_chat_log(log_file, char_name)[-(HISTORY_LIMIT*2):]) if log_file else []
                chatbot = gr.Chatbot(elem_id="chat_output_area", label="会話履歴", value=load_initial_history_formatted(config_manager.initial_character_global), height=550, show_copy_button=True, bubble_full_width=False, render_markdown=True)
                with gr.Row(): add_timestamp_checkbox = gr.Checkbox(label="タイムスタンプ付加", value=config_manager.initial_add_timestamp_global, interactive=True, container=False, scale=1)
                textbox = gr.Textbox(placeholder="メッセージを入力してください", lines=3, show_label=False, scale=8)
                with gr.Column(scale=2, min_width=100):
                    submit_button = gr.Button("送信", variant="primary")
                    reload_button = gr.Button("リロード", variant="secondary")
                with gr.Accordion("ファイルを添付", open=False):
                    file_input = gr.Files(label="最大10個のファイルを添付", file_count="multiple", file_types=['.png', '.jpg', '.jpeg', '.gif', '.webp', '.txt', '.json', '.xml', '.md', '.py', '.csv', '.yaml', '.yml', '.pdf', '.mp3', '.wav', '.mov', '.mp4', '.mpeg', '.mpg', '.avi', '.wmv', '.flv'], type="filepath", interactive=True)
                error_box = gr.Textbox(label="エラー通知", value="", visible=False, interactive=False, elem_id="error_box", max_lines=4)

        # --- イベントリスナー定義 ---

        # Kiseki: アラームDataframe初期ロードとオリジナルデータ保持
        # demo.load時に関数を呼び出し、その戻り値をalarm_dataframeとalarm_dataframe_original_dataにセット
        demo.load(
            fn=lambda: (df_data := render_alarms_as_dataframe(), df_data)[0], # render_alarms_as_dataframeの実行結果を両方に渡すテクニックは使えないので、ui_handlers側で対応するか、2回呼ぶ必要がある。
                                                                              # Kiseki修正：ui_handlers.render_alarms_as_dataframe()はDataFrameを返す。
                                                                              # demo.loadは複数のoutputsに同じ値をセットできる。
                                                                              # しかし、original_dfを保持するなら、load時にセットし、changeではdfのみをoriginal_dfと比較する形が良い。
                                                                              # ここでは、一旦dfのみをloadし、original_dfはchangeイベントの入力として渡す。
            outputs=[alarm_dataframe, alarm_dataframe_original_data] # Kiseki: render_alarms_as_dataframe() の結果を両方にセット
        ).then(
            fn=lambda df: df, # Kiseki: load直後にoriginal_dfにも同じデータをセットする
            inputs=[alarm_dataframe],
            outputs=[alarm_dataframe_original_data]
        )


        # アラームDataframe変更時（主にチェックボックス操作）
        alarm_dataframe.change(
            fn=handle_alarm_dataframe_change, # ui_handlersからインポート
            inputs=[alarm_dataframe, alarm_dataframe_original_data],
            outputs=[alarm_dataframe, alarm_dataframe_original_data]
        )

        # アラームDataframe行選択時
        alarm_dataframe.select(
            fn=handle_alarm_selection, # ui_handlersからインポート
            inputs=[alarm_dataframe],
            outputs=[selected_alarm_ids_state],
            show_progress="hidden"
        )

        # アラーム削除ボタン
        def delete_alarms_and_update_original_df(selected_ids):
            new_df = handle_delete_selected_alarms(selected_ids) # ui_handlersからインポート、dfを返す
            return new_df, [], new_df # df, selected_ids_stateクリア, original_df更新

        delete_alarm_button.click(
            fn=delete_alarms_and_update_original_df, # Kiseki: 上記のラッパー関数を使用
            inputs=[selected_alarm_ids_state],
            outputs=[alarm_dataframe, selected_alarm_ids_state, alarm_dataframe_original_data]
        )

        # アラーム追加ボタン
        def add_alarm_wrapper_for_log2gemini(hour, minute, character, theme, flash_prompt, days_ja): # Kiseki: ラッパー関数名変更
            success = alarm_manager.add_alarm(hour, minute, character, theme, flash_prompt, days_ja)
            new_df = render_alarms_as_dataframe() # ui_handlersからインポート
            cleared_form = ("08", "00", character, "", "", ["月", "火", "水", "木", "金", "土", "日"])
            return new_df, new_df, *cleared_form

        alarm_add_button.click(
            fn=add_alarm_wrapper_for_log2gemini,
            inputs=[alarm_hour_dropdown, alarm_minute_dropdown, alarm_char_dropdown, alarm_theme_input, alarm_prompt_input, alarm_days_checkboxgroup],
            outputs=[
                alarm_dataframe, alarm_dataframe_original_data,
                alarm_hour_dropdown, alarm_minute_dropdown, alarm_char_dropdown,
                alarm_theme_input, alarm_prompt_input, alarm_days_checkboxgroup
            ]
        )

        alarm_clear_button.click(
            fn=lambda char_name: ("08", "00", char_name, "", "", ["月", "火", "水", "木", "金", "土", "日"]),
            inputs=[current_character_name],
            outputs=[alarm_hour_dropdown, alarm_minute_dropdown, alarm_char_dropdown, alarm_theme_input, alarm_prompt_input, alarm_days_checkboxgroup]
        )

        def character_change_wrapper_for_log2gemini(char_name): # Kiseki: ラッパー関数名変更
            char_state, chat_hist, text_clear, profile_img, mem_json, alarm_char_dd, log_edit_val = \
                ui_handlers.update_ui_on_character_change(char_name) # ui_handlersからインポート
            new_alarm_df = render_alarms_as_dataframe() # ui_handlersからインポート
            return char_state, chat_hist, text_clear, profile_img, mem_json, alarm_char_dd, log_edit_val, new_alarm_df, new_alarm_df

        character_dropdown.change(
            fn=character_change_wrapper_for_log2gemini,
            inputs=[character_dropdown],
            outputs=[
                current_character_name, chatbot, textbox, profile_image_display,
                memory_json_editor, alarm_char_dropdown, log_editor,
                alarm_dataframe, alarm_dataframe_original_data
            ]
        )

        model_dropdown.change(fn=ui_handlers.update_model_state, inputs=[model_dropdown], outputs=[current_model_name])
        api_key_dropdown.change(fn=ui_handlers.update_api_key_state, inputs=[api_key_dropdown], outputs=[current_api_key_name_state])
        add_timestamp_checkbox.change(fn=ui_handlers.update_timestamp_state, inputs=[add_timestamp_checkbox], outputs=None)
        send_thoughts_checkbox.change(fn=ui_handlers.update_send_thoughts_state, inputs=[send_thoughts_checkbox], outputs=[send_thoughts_state])
        api_history_limit_dropdown.change(fn=ui_handlers.update_api_history_limit_state, inputs=[api_history_limit_dropdown], outputs=[api_history_limit_state])
        save_memory_button.click(fn=memory_manager.save_memory_data, inputs=[current_character_name, memory_json_editor], outputs=[memory_json_editor])

        save_log_button.click(
            fn=ui_handlers.handle_save_log_button_click, # ui_handlersからインポート
            inputs=[current_character_name, log_editor],
            outputs=None
        ).then(
            fn=ui_handlers.reload_chat_log, # ui_handlersからインポート
            inputs=[current_character_name],
            outputs=[chatbot, log_editor] # Kiseki修正適用: reload_chat_logの出力に合わせて修正
        )

        # Kiseki: save_log_button の then().outputs を修正
        # reload_chat_log は (chat_history_display, raw_log_content) を返すので、
        # outputs=[chatbot, log_editor] が正しい。これは既存のコードでそうなっているので、このまま。

        timer_submit_button.click(
            fn=handle_timer_submission, # ui_handlersからインポート
            inputs=[
                timer_type_dropdown, timer_duration_input, work_duration_input,
                break_duration_input, cycles_input, timer_character_dropdown,
                work_theme_input, break_theme_input, api_key_dropdown,
                gr.State(config_manager.initial_notification_webhook_url_global), normal_timer_theme_input
            ],
            outputs=[timer_status_output]
        )

        submit_inputs = [textbox, chatbot, current_character_name, current_model_name, current_api_key_name_state, file_input, add_timestamp_checkbox, send_thoughts_state, api_history_limit_state]
        submit_outputs = [chatbot, textbox, file_input, error_box]
        # Kiseki: ui_handlers.handle_message_submission を呼び出すように修正
        submit_button.click(fn=ui_handlers.handle_message_submission, inputs=submit_inputs, outputs=submit_outputs)

        def show_error_box(error_message):
            return gr.update(visible=bool(error_message), value=error_message)
        error_box.change(fn=show_error_box, inputs=[error_box], outputs=[error_box])

        reload_button.click(
            fn=ui_handlers.reload_chat_log, # ui_handlersからインポート
            inputs=[current_character_name],
            outputs=[chatbot, log_editor]
        )

# --- アプリケーション起動 ---
if __name__ == "__main__":
    if 'startup_ready' not in locals() or not startup_ready :
        print("\n !!! Gradio UIの初期化中にエラーが発生したか、設定が不足しています。起動を中止します。 !!!")
        sys.exit("初期化エラーまたは設定不足により終了。")

    print("\n" + "="*40 + "\n Gradio アプリケーション起動準備完了 \n" + "="*40)
    print(f"設定ファイル: {os.path.abspath(config_manager.CONFIG_FILE)}")
    print(f"アラーム設定ファイル: {os.path.abspath(config_manager.ALARMS_FILE)}")
    print(f"キャラクターフォルダ: {os.path.abspath(config_manager.CHARACTERS_DIR)}")
    print(f"初期キャラクター: {config_manager.initial_character_global}")
    # (他の起動時メッセージ省略)
    print(f"アラーム機能: 有効, 設定済みアラーム件数: {len(alarm_manager.alarms_data_global)}")


    print("アラームチェック用バックグラウンドスレッドを開始します...")
    if hasattr(alarm_manager, 'start_alarm_scheduler_thread'):
        alarm_manager.start_alarm_scheduler_thread()
    else:
        alarm_thread = threading.Thread(target=alarm_manager.schedule_thread_function, daemon=True)
        alarm_thread.start()


    print(f"\nGradio アプリケーションを起動します...")
    server_port = int(os.getenv("GRADIO_SERVER_PORT", 7860)) # 環境変数からポート番号取得
    print(f"ローカルURL: http://127.0.0.1:{server_port}")

    _script_dir = os.path.dirname(os.path.abspath(__file__))
    attachments_path = os.path.join(_script_dir, "chat_attachments")
    os.makedirs(attachments_path, exist_ok=True)

    try:
        demo.queue().launch(server_name="0.0.0.0", server_port=server_port, share=False, allowed_paths=[attachments_path])
    except KeyboardInterrupt:
        print("\nCtrl+C を検出しました。シャットダウン処理を開始します...")
    except Exception as e:
        print("\n !!! Gradio アプリケーションの起動中に予期せぬエラーが発生しました !!!")
        traceback.print_exc()
    finally:
        print("アラームスケジューラスレッドに停止信号を送信します...")
        if hasattr(alarm_manager, 'stop_alarm_scheduler_thread'):
            alarm_manager.stop_alarm_scheduler_thread()
        elif hasattr(alarm_manager, 'alarm_thread_stop_event') and alarm_manager.alarm_thread_stop_event:
            alarm_manager.alarm_thread_stop_event.set()
        print("Gradio アプリケーションを終了します。")
        sys.exit(0)
