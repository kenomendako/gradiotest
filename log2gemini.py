# -*- coding: utf-8 -*-
import gradio as gr
import os
import sys
import json
import traceback
import threading
import time
import google.api_core.exceptions

# --- 分割したモジュールをインポート ---
import config_manager
import character_manager
import memory_manager
import alarm_manager
import gemini_api
import utils
import ui_handlers
from ui_handlers import handle_timer_submission

# --- 定数 (UI関連) ---
HISTORY_LIMIT = config_manager.HISTORY_LIMIT # config_managerから取得

# --- Gradio アプリケーションの構築 ---
custom_css = """
#chat_output_area pre {
    overflow-wrap: break-word !important;
    white-space: pre-wrap !important;
    word-break: break-word !important;
}
#chat_output_area .thoughts {
    background-color: #2f2f32; /* 背景色を変更 */
    color: #E6E6E6; /* 文字色を明るく */
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
    overflow-wrap: break-word !important; /* Ensure this is also present */
}
#chat_output_area .thoughts pre code {
    white-space: pre-wrap !important;
    word-break: break-word !important;
    overflow-wrap: break-word !important;
    display: block !important; /* Explicitly make it a block to fill width */
    width: 100% !important;    /* Ensure it uses the container's width */
}
/* 修正点：#log_editor_code を追加 */
#memory_json_editor_code .cm-editor, #log_editor_code .cm-editor { max-height: 300px !important; overflow-y: auto !important; }
#memory_json_editor_code, #log_editor_code { max-height: 310px; overflow: hidden; border: 1px solid #ccc; border-radius: 5px; }
#alarm_checklist .gr-input-label { margin-bottom: 5px !important; }
#alarm_checklist .gr-check-radio > label { padding: 4px 0 !important; display: block; }
#help_accordion code { background-color: #eee; padding: 2px 4px; border-radius: 3px; font-size: 0.9em; }
.time-dropdown-container label { margin-bottom: 2px !important; font-size: 0.9em; } /* ラベル調整 */
.time-dropdown-container > div { margin-bottom: 5px !important; }
"""

# --- 起動シーケンス ---
print("設定ファイルを読み込んでいます...")
try:
    config_manager.load_config() # config_manager の関数を呼び出し
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
        print(" !!! UIから有効なAPIキーを選択してください。 !!!")
    else:
        print(f"初期APIキー '{config_manager.initial_api_key_name_global}' の設定に成功しました。")
elif not config_manager.API_KEYS:
     print(f"\n !!! 警告: {config_manager.CONFIG_FILE} にAPIキーが設定されていません ('api_keys')。 !!!")
     print(f" !!! アプリケーションは起動しますが、API通信はできません。{config_manager.CONFIG_FILE}を編集してください。 !!!")
else:
    print(f"\n !!! 警告: {config_manager.CONFIG_FILE} 内に有効なデフォルトAPIキー名 ('default_api_key_name' または 'last_api_key_name') が見つかりません。 !!!")
    print(" !!! UIから利用可能なAPIキーを選択してください。 !!!")

print("アラームデータを読み込んでいます...")
# Placed before 'with gr.Blocks() as demo:'
# This global variable will hold the reference to the Gradio UI component for the alarm list.
alarm_list_display_area_static_ref = None

def render_alarm_list_ui_components(current_char_name_state_trigger, event_source="load"):
    """Renders the alarm list UI components. Expects character name for context, and event source for logging."""
    # current_char_name_state_trigger is passed from the UI event that calls this.
    print(f"render_alarm_list_ui_components triggered by: {event_source} for char: {current_char_name_state_trigger}")
    alarms_list = alarm_manager.get_all_alarms()

    if not alarms_list:
        return [gr.Markdown("設定済みのアラームはありません。", elem_id="no_alarms_configured_msg")]

    ui_rows = []
    # Sort alarms by time for consistent display
    for alarm_item in sorted(alarms_list, key=lambda x: x.get("time", "")):
        item_id = alarm_item.get("id")
        # Using time.time_ns() for highly unique elem_id to help Gradio's diffing/re-rendering
        elem_suffix = f"{item_id}_{time.time_ns()}"

        with gr.Row(elem_id=f"alarm_row_{elem_suffix}") as r:
            switch_co = gr.Switch(
                value=alarm_item.get("enabled", False),
                label="有効",
                elem_id=f"alarm_switch_{elem_suffix}",
                scale=1
            )
            details = f"{alarm_item.get('time')} [{', '.join(alarm_item.get('days',[]))}] {alarm_item.get('character')} - \"{alarm_item.get('theme', '')[:30]}\""
            gr.Markdown(details, elem_id=f"alarm_details_{elem_suffix}", scale=3)
            delete_btn_co = gr.Button("削除", variant="stop", elem_id=f"alarm_delete_btn_{elem_suffix}", scale=1)

            # Event wiring for dynamically created components:
            # The crucial part is that 'outputs' for these handlers must be the alarm_list_display_area component.
            # This is assigned to alarm_list_display_area_static_ref when the UI is built.
            # current_character_name (gr.State) must be available in the scope where these components are defined,
            # or passed to the handlers. Here, we assume current_character_name is accessible when this runs.
            # If not, it needs to be an input to render_alarm_list_ui_components and then used.
            # For now, this relies on current_character_name being a global-like gr.State within the demo.
            switch_co.change(
                fn=handle_alarm_toggle_from_list,
                inputs=[gr.State(item_id), current_character_name], # Pass alarm_id by value, and the gr.State for char name
                outputs=[alarm_list_display_area_static_ref]
            )
            delete_btn_co.click(
                fn=handle_alarm_delete_from_list,
                inputs=[gr.State(item_id), current_character_name], # Pass alarm_id by value, and the gr.State for char name
                outputs=[alarm_list_display_area_static_ref]
            )
        ui_rows.append(r)
    return ui_rows

def handle_alarm_toggle_from_list(alarm_id_from_event, char_name_state_from_event):
    """Handles toggle event from a switch in the alarm list."""
    print(f"UI Event: Toggle alarm '{alarm_id_from_event}' from list for char '{char_name_state_from_event}'.")
    alarm_manager.toggle_alarm_enabled(alarm_id_from_event)
    # Return a new list of components to re-render the alarm_list_display_area
    return render_alarm_list_ui_components(char_name_state_from_event, f"toggle_event_{alarm_id_from_event}")

def handle_alarm_delete_from_list(alarm_id_from_event, char_name_state_from_event):
    """Handles delete event from a button in the alarm list."""
    print(f"UI Event: Delete alarm '{alarm_id_from_event}' from list for char '{char_name_state_from_event}'.")
    alarm_manager.delete_alarm(alarm_id_from_event)
    # Return a new list of components to re-render the alarm_list_display_area
    return render_alarm_list_ui_components(char_name_state_from_event, f"delete_event_{alarm_id_from_event}")

def add_alarm_then_refresh_ui(hour, minute, character, theme, flash_prompt, days_ja, current_char_name_state_from_event):
    """Handles adding an alarm and then returns components to refresh the list and clear form."""
    print(f"UI Event: Add alarm for char '{current_char_name_state_from_event}'.")
    add_success = alarm_manager.add_alarm(hour, minute, character, theme, flash_prompt, days_ja)
    if add_success:
        gr.Info("アラームが追加されました。")
    else:
        gr.Error("アラームの追加に失敗しました。詳細はコンソールを確認してください。")

    # Prepare outputs for the .click() event of the add_alarm_button
    # Output 1: Refreshed alarm list
    refreshed_list_components = render_alarm_list_ui_components(current_char_name_state_from_event, "add_alarm_event")
    # Output 2-7: Cleared values for the input form fields
    # (hour, minute, character, theme, prompt, days)
    # Use current_char_name_state_from_event for the character dropdown default after clearing
    cleared_form_values = ("08", "00", current_char_name_state_from_event, "", "", ["月", "火", "水", "木", "金", "土", "日"])

    return refreshed_list_components, *cleared_form_values

alarm_manager.load_alarms() # alarm_manager の関数を呼び出し

# アプリケーションUI定義開始
with gr.Blocks(theme=gr.themes.Soft(primary_hue="blue", secondary_hue="sky"), css=custom_css) as demo:
    character_list_on_startup = character_manager.get_character_list()
    # 起動に必要な設定のチェックを強化 (config_managerのグローバル変数を参照)
    startup_ready = all([
        character_list_on_startup,
        config_manager.initial_character_global and config_manager.initial_character_global in character_list_on_startup,
        config_manager.AVAILABLE_MODELS_GLOBAL,
        config_manager.initial_model_global and config_manager.initial_model_global in config_manager.AVAILABLE_MODELS_GLOBAL,
        config_manager.API_KEYS, # APIキー自体は起動時に必須とする
        config_manager.initial_api_history_limit_option_global and config_manager.initial_api_history_limit_option_global in config_manager.API_HISTORY_LIMIT_OPTIONS,
        config_manager.initial_alarm_model_global, # アラームモデル名は必須
        isinstance(config_manager.initial_alarm_api_history_turns_global, int) # アラーム履歴ターン数も必須
    ])

    if not startup_ready:
        # エラーメッセージを改善
        error_details = []
        if not character_list_on_startup: error_details.append(f"キャラクターが見つかりません。`{config_manager.CHARACTERS_DIR}` フォルダを確認してください。")
        elif not config_manager.initial_character_global or config_manager.initial_character_global not in character_list_on_startup: error_details.append(f"`config.json` の `last_character` ('{config_manager.initial_character_global}') が無効です。")
        if not config_manager.AVAILABLE_MODELS_GLOBAL: error_details.append(f"`config.json` に `available_models` が設定されていません。")
        elif not config_manager.initial_model_global or config_manager.initial_model_global not in config_manager.AVAILABLE_MODELS_GLOBAL: error_details.append(f"`config.json` の `last_model` ('{config_manager.initial_model_global}') が `available_models` に含まれていません。")
        if not config_manager.API_KEYS: error_details.append(f"`config.json` に `api_keys` が設定されていません。")
        if not config_manager.initial_api_history_limit_option_global or config_manager.initial_api_history_limit_option_global not in config_manager.API_HISTORY_LIMIT_OPTIONS: error_details.append(f"`config.json` の `last_api_history_limit_option` ('{config_manager.initial_api_history_limit_option_global}') が無効です。")
        if not config_manager.initial_alarm_model_global: error_details.append(f"`config.json` に `alarm_model` が設定されていません。")
        if not isinstance(config_manager.initial_alarm_api_history_turns_global, int): error_details.append(f"`config.json` の `alarm_api_history_turns` が整数ではありません。")

        print("\n" + "="*40 + "\n !!! 起動に必要な設定が不足しています !!!\n" + "="*40)
        for detail in error_details: print(f"- {detail}")
        print("\n詳細はコンソールログおよび config.json を確認してください。\nGradio UIは表示されません。")
        gr.Markdown(f"## 起動エラー\nアプリケーションの起動に必要な設定が不足しています。\n以下の設定を確認してください:\n\n{chr(10).join(['- ' + item for item in error_details])}\n\n詳細はコンソールログおよび `{config_manager.CONFIG_FILE}` を確認してください。\n設定を修正してからアプリケーションを再起動してください。")
        # startup_ready はこの時点で False のまま

    else: # startup_ready が True の場合のみUIを構築
        # --- Gradio State定義 (config_managerのグローバル変数で初期化) ---
        current_character_name = gr.State(config_manager.initial_character_global)
        current_model_name = gr.State(config_manager.initial_model_global)
        current_api_key_name_state = gr.State(config_manager.initial_api_key_name_global)
        send_thoughts_state = gr.State(config_manager.initial_send_thoughts_to_api_global)
        api_history_limit_state = gr.State(config_manager.initial_api_history_limit_option_global)

        gr.Markdown("# AI Chat with Gradio & Gemini")

        with gr.Row():
            # --- 左カラム ---
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
                    send_thoughts_checkbox = gr.Checkbox(value=config_manager.initial_send_thoughts_to_api_global, label="思考過程をAPIに送信", info="OFFでトークン削減可能 (モデル挙動に影響あり)", interactive=True)

                with gr.Accordion(f"📗 キャラクターの記憶 ({config_manager.MEMORY_FILENAME})", open=False):
                    def get_initial_memory_data_str(char_name: str) -> str: # Type hint added for clarity
                         if not char_name: return "{}"
                         _, _, _, mem_path = character_manager.get_character_files_paths(char_name)
                         mem_data = memory_manager.load_memory_data_safe(mem_path)
                         return json.dumps(mem_data, indent=2, ensure_ascii=False) if isinstance(mem_data, dict) else json.dumps({"error": "Failed to load"}, indent=2)
                    memory_json_editor = gr.Code(value=get_initial_memory_data_str(config_manager.initial_character_global), label="記憶データ (JSON形式で編集)", language="json", interactive=True, elem_id="memory_json_editor_code")
                    save_memory_button = gr.Button(value="想いを綴る", variant="secondary")

                with gr.Accordion("📗 チャットログ編集 (`log.txt`)", open=False):
                    def get_initial_log_data_str(char_name: str) -> str: # Type hint added
                        if not char_name:
                            return "キャラクターを選択してください。"
                        log_f, _, _, _ = character_manager.get_character_files_paths(char_name)
                        if log_f and os.path.exists(log_f):
                            try:
                                with open(log_f, "r", encoding="utf-8") as f:
                                    return f.read()
                            except Exception as e:
                                print(f"Error reading log file {log_f} for initial display: {e}")
                                traceback.print_exc()
                                return f"ログファイルの読み込みに失敗しました: {e}"
                        elif log_f and not os.path.exists(log_f):
                            return "" # Log file doesn't exist, editor starts empty
                        else:
                            return "キャラクターのログファイルパスが見つかりません。"

                    log_editor = gr.Code(
                        label="ログ内容 (直接編集可能)",
                        value=get_initial_log_data_str(config_manager.initial_character_global),
                        interactive=True,
                        elem_id="log_editor_code"
                    )
                    save_log_button = gr.Button(value="ログを保存", variant="secondary")

                with gr.Accordion(" 🐦アラーム設定", open=False) as alarm_accordion: # Named for clarity
                    # Static UI structure for displaying the alarm list
                    alarm_list_display_area = gr.Column(elem_id="alarm_list_display_area_new")
                    # alarm_list_display_area_static_ref is already a global variable defined earlier.
                    # We are assigning the created component to it.
                    alarm_list_display_area_static_ref = alarm_list_display_area

                    # Initial population using a render_alarm_list_ui_components function
                    # This function is assumed to be defined elsewhere in log2gemini.py (e.g., globally)
                    # or will be added in a subsequent step.
                    demo.load(
                        fn=render_alarm_list_ui_components,
                        inputs=[current_character_name, gr.State("initial_load_event")], # Pass state if needed by render function
                        outputs=[alarm_list_display_area]
                    )

                    gr.Markdown("---") # Separator
                    # Alarm adding form (structure remains the same)
                    with gr.Column(visible=True) as alarm_form_area:
                        gr.Markdown("#### 新規アラーム追加")
                        with gr.Row():
                            hours = [f"{h:02}" for h in range(24)]
                            alarm_hour_dropdown = gr.Dropdown(label="時", choices=hours, value="08", interactive=True, scale=1, elem_classes="time-dropdown-container")
                            minutes = [f"{m:02}" for m in range(60)]
                            alarm_minute_dropdown = gr.Dropdown(label="分", choices=minutes, value="00", interactive=True, scale=1, elem_classes="time-dropdown-container")
                        alarm_char_dropdown = gr.Dropdown(label="キャラクター", choices=character_list_on_startup, value=config_manager.initial_character_global, interactive=True)
                        alarm_theme_input = gr.Textbox(label="ひとことテーマ（必須）", placeholder="例: 今日も一日頑張ろう！", lines=2)
                        alarm_days_checkboxgroup = gr.CheckboxGroup(label="曜日設定", choices=["月", "火", "水", "木", "金", "土", "日"], value=["月", "火", "水", "木", "金", "土", "日"], interactive=True)
                        alarm_prompt_input = gr.Textbox(label="応答指示書（上級者向け・任意）", info="空欄の場合は上の『ひとことテーマ』を元にAIが応答を考えます。AIの話し方などを細かく制御したい場合のみ、こちらに指示を書いてください", placeholder="プロンプト内で [キャラクター名] と [テーマ内容] が利用可能です。", lines=3)
                        with gr.Row():
                            alarm_add_button = gr.Button("アラームを追加", variant="primary")
                            alarm_clear_button = gr.Button("入力クリア")

                # タイマーUIの統一とプロンプト設定の追加
                with gr.Accordion("⏰ タイマー設定", open=False):
                    timer_type_dropdown = gr.Dropdown(
                        label="タイマータイプ",
                        choices=["通常タイマー", "ポモドーロタイマー"],
                        value="通常タイマー",
                        interactive=True
                    )

                    # 各入力欄を定義
                    timer_duration_input = gr.Number(label="タイマー時間 (分)", value=1, interactive=True, visible=True)
                    normal_timer_theme_input = gr.Textbox(label="通常タイマーのテーマ", placeholder="例: タイマー終了！", lines=2, interactive=True, visible=True)
                    work_duration_input = gr.Number(label="作業時間 (分)", value=25, interactive=True, visible=False)
                    break_duration_input = gr.Number(label="休憩時間 (分)", value=5, interactive=True, visible=False)
                    cycles_input = gr.Number(label="サイクル数", value=4, interactive=True, visible=False)
                    work_theme_input = gr.Textbox(label="作業テーマ", placeholder="例: 集中して作業しよう！", lines=2, interactive=True, visible=False)
                    break_theme_input = gr.Textbox(label="休憩テーマ", placeholder="例: リラックスして休憩しよう！", lines=2, interactive=True, visible=False)

                    # タイマータイプに応じて入力欄を切り替える関数
                    def update_timer_inputs(timer_type):
                        if timer_type == "通常タイマー":
                            return (
                                gr.update(visible=True), gr.update(visible=True), gr.update(visible=False),
                                gr.update(visible=False), gr.update(visible=False), gr.update(visible=False), gr.update(visible=False)
                            )
                        elif timer_type == "ポモドーロタイマー":
                            return (
                                gr.update(visible=False), gr.update(visible=False), gr.update(visible=True),
                                gr.update(visible=True), gr.update(visible=True), gr.update(visible=True), gr.update(visible=True)
                            )

                    timer_type_dropdown.change(
                        fn=update_timer_inputs,
                        inputs=[timer_type_dropdown],
                        outputs=[
                            timer_duration_input, normal_timer_theme_input, work_duration_input, break_duration_input,
                            cycles_input, work_theme_input, break_theme_input
                        ]
                    )

                    timer_character_dropdown = gr.Dropdown(
                        label="キャラクター",
                        choices=character_list_on_startup,
                        value=config_manager.initial_character_global,
                        interactive=True
                    )

                    timer_status_output = gr.Textbox(
                        label="タイマー設定状況",
                        interactive=False,
                        placeholder="ここに設定内容が表示されます。"
                    )

                    # タイマー開始ボタンの処理
                    timer_submit_button = gr.Button("タイマー開始")
                    timer_submit_button.click(
                        fn=ui_handlers.handle_timer_submission,
                        inputs=[
                            timer_type_dropdown, timer_duration_input, work_duration_input,
                            break_duration_input, cycles_input, timer_character_dropdown,
                            work_theme_input, break_theme_input, api_key_dropdown,
                            gr.State(config_manager.initial_notification_webhook_url_global), normal_timer_theme_input
                        ],
                        outputs=[timer_status_output]
                    )

                with gr.Accordion("ℹ️ ヘルプ", open=False, elem_id="help_accordion"):
                    # ヘルプテキスト内のファイル名などをconfig_managerから参照するように更新
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
- `notification_webhook_url`: **(新規)** アラーム通知を送るWebhook URL (Google Chat, Slack等)。`null` または `""` で無効。**URLは機密情報です。公開しないでください。**

### キャラクター設定 (`{config_manager.CHARACTERS_DIR}/<キャラ名>/`)
- `SystemPrompt.txt`: キャラクターの性格や応答指示を記述します。思考過程指示 (`【Thoughts】...【/Thoughts】`) もここに含めます。
- `{config_manager.MEMORY_FILENAME}`: キャラクターの記憶データ。UIの「記憶」欄で編集・保存できます。
- `log.txt`: 会話履歴。アラーム通知もここに記録されます。
- `{config_manager.PROFILE_IMAGE_FILENAME}`: キャラクター画像 (任意)。

### アラーム機能
- 左カラム「⏰ アラーム設定」で設定します。
- 時・分、キャラクター、テーマ（またはカスタムプロンプト）を指定して「アラームを追加」します。
- 設定した時刻になると、指定キャラがテーマに基づいたメッセージを生成し、ログに記録、Webhook通知（設定時）を行います。
- 応答生成には軽量モデル (`alarm_model`) と短い履歴 (`alarm_api_history_turns`) が参照され、**記憶も参照されます**。（ヘルプ記述修正）
- チャットUIへの表示はリアルタイムではなく、次のUI更新時に反映されます。
- 削除はリストからチェックを入れて「選択したアラームを削除」ボタンをクリックします。編集や有効/無効のUI切り替えは未対応です (`{config_manager.ALARMS_FILE}` を直接編集)。

*注意:* Webhook URLは `{config_manager.CONFIG_FILE}` に直接記述するため、ファイルの取り扱いには十分注意してください。
""") # 記憶参照についてヘルプの記述を修正

            # --- 右カラム：チャットUI ---
            with gr.Column(scale=3):
                gr.Markdown(f"### チャット (UI表示: 最新{HISTORY_LIMIT}往復)")
                def load_initial_history_formatted(char_name):
                    if not char_name: return []
                    log_file, _, _, _ = character_manager.get_character_files_paths(char_name)
                    return utils.format_history_for_gradio(utils.load_chat_log(log_file, char_name)[-(HISTORY_LIMIT*2):]) if log_file else []
                chatbot = gr.Chatbot(elem_id="chat_output_area", label="会話履歴", value=load_initial_history_formatted(config_manager.initial_character_global), height=550, show_copy_button=True, bubble_full_width=False, render_markdown=True)

                with gr.Row():
                    add_timestamp_checkbox = gr.Checkbox(label="タイムスタンプ付加", value=config_manager.initial_add_timestamp_global, interactive=True, container=False, scale=1)

                textbox = gr.Textbox(
                    placeholder="メッセージを入力してください",
                    lines=3,
                    show_label=False,
                    scale=8
                )
                with gr.Column(scale=2, min_width=100):
                    submit_button = gr.Button("送信", variant="primary")
                    reload_button = gr.Button("リロード", variant="secondary")

                with gr.Accordion("ファイルを添付", open=False):
                    file_input = gr.Files(label="最大10個のファイルを添付 (対応形式多数)", file_count="multiple", file_types=['.png', '.jpg', '.jpeg', '.gif', '.webp', '.txt', '.json', '.xml', '.md', '.py', '.csv', '.yaml', '.yml', '.pdf', '.mp3', '.wav', '.mov', '.mp4', '.mpeg', '.mpg', '.avi', '.wmv', '.flv'], type="filepath", interactive=True)

                # --- エラーメッセージ表示用ボックス ---
                error_box = gr.Textbox(label="エラー通知", value="", visible=False, interactive=False, elem_id="error_box", max_lines=4)

        # --- イベントリスナー定義 (ui_handlersの関数を呼び出し) ---
        character_dropdown.change(
            fn=ui_handlers.update_ui_on_character_change,
            inputs=[character_dropdown],
            outputs=[current_character_name, chatbot, textbox, profile_image_display, memory_json_editor, alarm_char_dropdown, log_editor]
        )
        model_dropdown.change(fn=ui_handlers.update_model_state, inputs=[model_dropdown], outputs=[current_model_name])
        api_key_dropdown.change(fn=ui_handlers.update_api_key_state, inputs=[api_key_dropdown], outputs=[current_api_key_name_state])
        add_timestamp_checkbox.change(fn=ui_handlers.update_timestamp_state, inputs=[add_timestamp_checkbox], outputs=None)
        send_thoughts_checkbox.change(fn=ui_handlers.update_send_thoughts_state, inputs=[send_thoughts_checkbox], outputs=[send_thoughts_state])
        api_history_limit_dropdown.change(fn=ui_handlers.update_api_history_limit_state, inputs=[api_history_limit_dropdown], outputs=[api_history_limit_state])

        # 記憶保存 (memory_managerの関数を直接呼び出すか、ui_handlers経由にするか。ここではui_handlers経由の例は無いため直接呼び出す)
        save_memory_button.click(fn=memory_manager.save_memory_data, inputs=[current_character_name, memory_json_editor], outputs=[memory_json_editor])

        # ログ保存ボタンのイベントリスナー
        save_log_button.click(
            fn=ui_handlers.handle_save_log_button_click,
            inputs=[current_character_name, log_editor],
            outputs=None  # handle_save_log_button_click は gr.Info/Error を使用
        ).then(
            fn=ui_handlers.reload_chat_log,
            inputs=[current_character_name],
            outputs=[chatbot]
        )

        # アラーム追加 (new handler that also refreshes UI and clears form)
        alarm_add_button.click(
            fn=add_alarm_then_refresh_ui, # New global handler
            inputs=[
                alarm_hour_dropdown,
                alarm_minute_dropdown,
                alarm_char_dropdown,
                alarm_theme_input,
                alarm_prompt_input,
                alarm_days_checkboxgroup,
                current_character_name # Pass current character state for context and form clearing
            ],
            outputs=[
                alarm_list_display_area_static_ref, # Target for the refreshed list components - USE THE REF
                alarm_hour_dropdown,     # Target for clearing input
                alarm_minute_dropdown,   # Target for clearing input
                alarm_char_dropdown,     # Target for clearing input (reset to current char)
                alarm_theme_input,       # Target for clearing input
                alarm_prompt_input,      # Target for clearing input
                alarm_days_checkboxgroup # Target for clearing input
            ]
        )
        # The old .then() chain for refreshing and clearing is now handled by add_alarm_then_refresh_ui

        alarm_clear_button.click(
             lambda char: ("08", "00", char, "", "", ["月", "火", "水", "木", "金", "土", "日"]), # 曜日設定をデフォルトに戻す
            inputs=[current_character_name], # 現在選択中のキャラ名を渡す
            outputs=[alarm_hour_dropdown, alarm_minute_dropdown, alarm_char_dropdown, alarm_theme_input, alarm_prompt_input, alarm_days_checkboxgroup]
        )
        # delete_selected_alarms_button and its event are fully removed.

        # メッセージ送信 (ui_handlersの関数を使用)
        submit_inputs = [textbox, chatbot, current_character_name, current_model_name, current_api_key_name_state, file_input, add_timestamp_checkbox, send_thoughts_state, api_history_limit_state]
        submit_outputs = [chatbot, textbox, file_input, error_box]
        submit_button.click(fn=ui_handlers.handle_message_submission, inputs=submit_inputs, outputs=submit_outputs)

        # --- error_boxの内容が空でなければ自動的に表示 ---
        def show_error_box(error_message):
            if error_message:
                return gr.update(visible=True, value=error_message)
            else:
                return gr.update(visible=False, value="")
        error_box.change(fn=show_error_box, inputs=[error_box], outputs=[error_box])

        # リロードボタン (ui_handlersの関数を使用)
        reload_button.click(
            fn=ui_handlers.reload_chat_log,
            inputs=[current_character_name],
            outputs=[chatbot, log_editor] # 修正点：log_editorを追加
        )

# --- アプリケーション起動 ---
if __name__ == "__main__":
    # startup_ready のチェックを Block 外で行う
    if 'startup_ready' not in locals() or not startup_ready :
        # UI構築自体がスキップされたか、設定不足の場合
        print("\n !!! Gradio UIの初期化中にエラーが発生したか、設定が不足しています。起動を中止します。 !!!")
        print(" !!! コンソールログおよびUI上のエラーメッセージを確認してください。 !!!")
        sys.exit("初期化エラーまたは設定不足により終了。")

    print("\n" + "="*40 + "\n Gradio アプリケーション起動準備完了 \n" + "="*40)
    print(f"設定ファイル: {os.path.abspath(config_manager.CONFIG_FILE)}")
    print(f"アラーム設定ファイル: {os.path.abspath(config_manager.ALARMS_FILE)}")
    print(f"キャラクターフォルダ: {os.path.abspath(config_manager.CHARACTERS_DIR)}")
    print(f"初期キャラクター: {config_manager.initial_character_global}")
    print(f"初期モデル (通常対話): {config_manager.initial_model_global}")
    print(f"初期APIキー名: {config_manager.initial_api_key_name_global if config_manager.initial_api_key_name_global else '未選択（UIで選択要）'}")
    print(f"タイムスタンプ付加 (初期): {config_manager.initial_add_timestamp_global}")
    print(f"思考過程API送信 (初期): {config_manager.initial_send_thoughts_to_api_global}")
    print(f"API履歴制限 (通常対話): {config_manager.API_HISTORY_LIMIT_OPTIONS.get(config_manager.initial_api_history_limit_option_global, '不明')}")
    print("-" * 20 + " アラーム設定 " + "-" * 20)
    print(f"アラーム機能: 有効")
    print(f"  アラーム用モデル: {config_manager.initial_alarm_model_global}")
    print(f"  アラーム用履歴参照: {config_manager.initial_alarm_api_history_turns_global} 往復")
    print(f"  設定済みアラーム件数: {len(alarm_manager.alarms_data_global)}") # alarm_managerのグローバル変数を参照
    print(f"  Webhook通知URL: {'設定済み' if config_manager.initial_notification_webhook_url_global else '未設定'}")
    print("="*40)

    print("アラームチェック用バックグラウンドスレッドを開始します...")
    # alarm_managerの関数と停止イベントを使用
    alarm_thread = threading.Thread(target=alarm_manager.schedule_thread_function, daemon=True)
    alarm_thread.start()

    print(f"\nGradio アプリケーションを起動します...")
    server_port = 7860
    print(f"ローカルURL: http://127.0.0.1:{server_port}")
    print("他のデバイスからアクセス可能にする場合、 --share オプションや server_name='0.0.0.0' を検討してください。")
    print("(Ctrl+C でアプリケーションを停止します)")
    print("-" * 40)

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
        alarm_manager.alarm_thread_stop_event.set() # alarm_managerの停止イベントを使用
        if alarm_thread.is_alive():
            print("アラームスレッドの終了を待機中 (最大5秒)...")
            alarm_thread.join(timeout=5)
            if alarm_thread.is_alive(): print("警告: アラームスレッドが時間内に終了しませんでした。")
            else: print("アラームスレッドが正常に停止しました。")
        else: print("アラームスレッドは既に停止しています。")
        print("Gradio アプリケーションを終了します。")
        sys.exit(0)