# --- [ロギング設定の強制上書き] ---
# GradioやMemOSのマルチスレッド/プロセス動作によるログファイルの競合を防ぐため、
# アプリケーション全体のロギング設定を、起動時にスレッドセーフなものに上書きする。
import logging
import logging.config
import os
from pathlib import Path
from sys import stdout

# ログファイル用のディレクトリを定義
LOGS_DIR = Path(os.getenv("MEMOS_BASE_PATH", Path.cwd())) / ".memos" / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE_PATH = LOGS_DIR / "nexus_ark.log" # ログファイル名を nexus_ark.log に変更

# スレッドセーフなロギング設定
LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(funcName)s - %(message)s"
        },
    },
    "handlers": {
        "console": {
            "level": "INFO",
            "class": "logging.StreamHandler",
            "stream": stdout,
            "formatter": "standard",
        },
        "file": {
            "level": "DEBUG",
            "class": "concurrent_log_handler.ConcurrentRotatingFileHandler",
            "filename": LOG_FILE_PATH,
            "maxBytes": 1024 * 1024 * 10,  # 10 MB
            "backupCount": 5,
            "formatter": "standard",
            "use_gzip": True,
        },
    },
    "root": {
        "level": "DEBUG",
        "handlers": ["console", "file"],
    },
    "loggers": {
        "memos": {
            "level": "WARNING", # MemOSライブラリのログレベルをWARNINGに設定し、不要なINFOログを抑制
            "propagate": True,
        },
        "gradio": {
            "level": "WARNING", # GradioライブラリのログレベルをWARNINGに設定
            "propagate": True,
        },
         "httpx": {
            "level": "WARNING", # httpxライブラリのログレベルをWARNINGに設定
            "propagate": True,
        },
    },
}

logging.config.dictConfig(LOGGING_CONFIG)
# --- [ここまでが追加ブロック] ---


# nexus_ark.py (v18: 複数人対話セッションFIX・最終版)

import os
import sys
import utils
import json
import gradio as gr
import traceback
import pandas as pd
import config_manager, character_manager, alarm_manager, ui_handlers, constants

if not utils.acquire_lock():
    print("ロックが取得できなかったため、アプリケーションを終了します。")
    if os.name == "nt": os.system("pause")
    else: input("続行するにはEnterキーを押してください...")
    sys.exit(1)
os.environ["MEM0_TELEMETRY_ENABLED"] = "false"

try:
    config_manager.load_config()
    alarm_manager.load_alarms()
    alarm_manager.start_alarm_scheduler_thread()

    custom_css = """
    #chat_output_area pre { overflow-wrap: break-word !important; white-space: pre-wrap !important; word-break: break-word !important; }
    #chat_output_area .thoughts { background-color: #2f2f32; color: #E6E6E6; padding: 5px; border-radius: 5px; font-family: "Menlo", "Monaco", "Consolas", "Courier New", monospace; font-size: 0.8em; white-space: pre-wrap; word-break: break-word; overflow-wrap: break-word !important; }
    #memory_json_editor_code .cm-editor { max-height: 400px !important; overflow-y: auto !important; overflow-x: hidden !important; white-space: pre-wrap !important; word-break: break-word !important; overflow-wrap: break-word !important; }
    #notepad_editor_code textarea, #system_prompt_editor textarea { max-height: 400px !important; overflow-y: auto !important; white-space: pre-wrap !important; word-break: break-word !important; overflow-wrap: break-word !important; box-sizing: border-box; }
    #memory_json_editor_code, #notepad_editor_code, #system_prompt_editor { max-height: 410px; border: 1px solid #ccc; border-radius: 5px; padding: 0; }
    #alarm_dataframe_display { border-radius: 8px !important; } #alarm_dataframe_display table { width: 100% !important; }
    #alarm_dataframe_display th, #alarm_dataframe_display td { text-align: left !important; padding: 4px 8px !important; white-space: normal !important; font-size: 0.95em; }
    #alarm_dataframe_display th:nth-child(1), #alarm_dataframe_display td:nth-child(1) { width: 50px !important; text-align: center !important; }
    #selection_feedback { font-size: 0.9em; color: #555; margin-top: 0px; margin-bottom: 5px; padding-left: 5px; }
    #token_count_display { text-align: right; font-size: 0.85em; color: #555; padding-right: 10px; margin-bottom: 5px; }
    #tpm_note_display { text-align: right; font-size: 0.75em; color: #777; padding-right: 10px; margin-bottom: -5px; margin-top: 0px; }
    #chat_container { position: relative; }
    """
    js_stop_nav_link_propagation = """
    function() {
        document.body.addEventListener('click', function(e) {
            let target = e.target;
            while (target && target !== document.body) {
                if (target.matches('.message-nav-link')) {
                    e.stopPropagation();
                    return;
                }
                target = target.parentElement;
            }
        }, true);
    }
    """

    with gr.Blocks(theme=gr.themes.Soft(primary_hue="blue", secondary_hue="sky"), css=custom_css, js=js_stop_nav_link_propagation) as demo:
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

        # --- Stateの定義 ---
        world_data_state = gr.State({})
        current_character_name = gr.State(effective_initial_character)
        current_model_name = gr.State(config_manager.initial_model_global)
        current_api_key_name_state = gr.State(config_manager.initial_api_key_name_global)
        api_history_limit_state = gr.State(config_manager.initial_api_history_limit_option_global)
        alarm_dataframe_original_data = gr.State(pd.DataFrame())
        selected_alarm_ids_state = gr.State([])
        editing_alarm_id_state = gr.State(None)
        selected_message_state = gr.State(None)
        current_log_map_state = gr.State([])
        active_participants_state = gr.State([]) # 現在アクティブな複数人対話の参加者リスト
        debug_console_state = gr.State("")
        importer_process_state = gr.State(None) # インポーターのサブプロセスを管理

        with gr.Tabs():
            with gr.TabItem("チャット"):
                with gr.Row():
                    with gr.Column(scale=1, min_width=300):
                        profile_image_display = gr.Image(height=150, width=150, interactive=False, show_label=False, container=False)
                        character_dropdown = gr.Dropdown(choices=character_list_on_startup, value=effective_initial_character, label="キャラクターを選択", interactive=True)

                        with gr.Accordion("🌄 情景描写・移動", open=False):
                            scenery_image_display = gr.Image(label="現在の情景ビジュアル", interactive=False, height=200, show_label=False)
                            generate_scenery_image_button = gr.Button("情景画像を生成 / 更新", variant="secondary")
                            scenery_style_radio = gr.Dropdown(choices=["写真風 (デフォルト)", "イラスト風", "アニメ風", "水彩画風"], label="画風を選択", value="写真風 (デフォルト)", interactive=True)
                            current_location_display = gr.Textbox(label="現在地", interactive=False)
                            current_scenery_display = gr.Textbox(label="現在の情景", interactive=False, lines=4, max_lines=10)
                            refresh_scenery_button = gr.Button("情景を更新", variant="secondary")
                            location_dropdown = gr.Dropdown(label="移動先を選択", interactive=True)
                        with gr.Accordion("⏰ 時間管理", open=False):
                            with gr.Tabs():
                                with gr.TabItem("アラーム"):
                                    gr.Markdown("ℹ️ **操作方法**: リストから操作したいアラームの行を選択し、下のボタンで操作します。")
                                    alarm_dataframe = gr.Dataframe(headers=["状態", "時刻", "予定", "キャラ", "内容"], datatype=["bool", "str", "str", "str", "str"], interactive=True, row_count=(5, "dynamic"), col_count=5, wrap=True, elem_id="alarm_dataframe_display")
                                    selection_feedback_markdown = gr.Markdown("アラームを選択してください", elem_id="selection_feedback")
                                    with gr.Row():
                                        enable_button = gr.Button("✔️ 選択を有効化"); disable_button = gr.Button("❌ 選択を無効化"); delete_alarm_button = gr.Button("🗑️ 選択したアラームを削除", variant="stop")
                                    gr.Markdown("---"); gr.Markdown("#### 新規 / 更新")
                                    alarm_hour_dropdown = gr.Dropdown(choices=[str(i).zfill(2) for i in range(24)], label="時", value="08")
                                    alarm_minute_dropdown = gr.Dropdown(choices=[str(i).zfill(2) for i in range(60)], label="分", value="00")
                                    alarm_char_dropdown = gr.Dropdown(choices=character_list_on_startup, value=effective_initial_character, label="キャラ")
                                    alarm_context_input = gr.Textbox(label="内容", placeholder="AIに伝える内容や目的を簡潔に記述します。\n例：朝の目覚まし、今日も一日頑張ろう！", lines=3)
                                    alarm_emergency_checkbox = gr.Checkbox(label="緊急通知として送信 (マナーモードを貫通)", value=False, interactive=True)
                                    alarm_days_checkboxgroup = gr.CheckboxGroup(choices=["月", "火", "水", "木", "金", "土", "日"], label="曜日", value=[])
                                    with gr.Row():
                                        alarm_add_button = gr.Button("アラーム追加")
                                        cancel_edit_button = gr.Button("編集をキャンセル", visible=False)
                                with gr.TabItem("タイマー"):
                                    timer_type_radio = gr.Radio(["通常タイマー", "ポモドーロタイマー"], label="タイマー種別", value="通常タイマー")
                                    with gr.Column(visible=True) as normal_timer_ui:
                                        timer_duration_number = gr.Number(label="タイマー時間 (分)", value=10, minimum=1, step=1); normal_timer_theme_input = gr.Textbox(label="通常タイマーのテーマ", placeholder="例: タイマー終了！")
                                    with gr.Column(visible=False) as pomo_timer_ui:
                                        pomo_work_number = gr.Number(label="作業時間 (分)", value=25, minimum=1, step=1); pomo_break_number = gr.Number(label="休憩時間 (分)", value=5, minimum=1, step=1); pomo_cycles_number = gr.Number(label="サイクル数", value=4, minimum=1, step=1); timer_work_theme_input = gr.Textbox(label="作業終了時テーマ", placeholder="作業終了！"); timer_break_theme_input = gr.Textbox(label="休憩終了時テーマ", placeholder="休憩終了！")
                                    timer_char_dropdown = gr.Dropdown(choices=character_list_on_startup, value=effective_initial_character, label="通知キャラ", interactive=True); timer_status_output = gr.Textbox(label="タイマー設定状況", interactive=False, placeholder="ここに設定内容が表示されます。"); timer_submit_button = gr.Button("タイマー開始", variant="primary")
                        with gr.Accordion("⚙️ 設定", open=False):
                            with gr.Tabs():
                                with gr.TabItem("共通設定"):
                                    gr.Markdown("#### ⚙️ 一般設定")
                                    model_dropdown = gr.Dropdown(choices=config_manager.AVAILABLE_MODELS_GLOBAL, value=config_manager.initial_model_global, label="デフォルトAIモデル", interactive=True)
                                    api_key_dropdown = gr.Dropdown(choices=list(config_manager.GEMINI_API_KEYS.keys()), value=config_manager.initial_api_key_name_global, label="使用するGemini APIキー", interactive=True)
                                    api_history_limit_dropdown = gr.Dropdown(choices=list(constants.API_HISTORY_LIMIT_OPTIONS.values()), value=constants.API_HISTORY_LIMIT_OPTIONS.get(config_manager.initial_api_history_limit_option_global, "全ログ"), label="APIへの履歴送信", interactive=True)
                                    debug_mode_checkbox = gr.Checkbox(label="デバッグモードを有効化 (ターミナルにシステムプロンプトを出力)", value=False, interactive=True)
                                    auto_memory_checkbox = gr.Checkbox(label="対話の自動記憶を有効にする", value=lambda: config_manager.CONFIG_GLOBAL.get("memos_config", {}).get("auto_memory_enabled", False), interactive=True)
                                    api_test_button = gr.Button("API接続をテスト", variant="secondary")
                                    gr.Markdown("---")
                                    gr.Markdown("#### 📢 通知サービス設定")
                                    notification_service_radio = gr.Radio(choices=["Discord", "Pushover"], label="アラーム通知に使用するサービス", value=config_manager.NOTIFICATION_SERVICE_GLOBAL.capitalize(), interactive=True)
                                    gr.Markdown("---")
                                    with gr.Accordion("🔑 APIキー / Webhook管理", open=False):
                                        with gr.Accordion("Gemini APIキー", open=True):
                                            gemini_key_name_input = gr.Textbox(label="キーの名前（管理用の半角英数字）", placeholder="例: my_personal_key")
                                            gemini_key_value_input = gr.Textbox(label="APIキーの値", type="password")
                                            with gr.Row():
                                                save_gemini_key_button = gr.Button("Geminiキーを保存", variant="primary")
                                                delete_gemini_key_button = gr.Button("削除")
                                        with gr.Accordion("Pushover", open=False):
                                            pushover_user_key_input = gr.Textbox(label="Pushover User Key", type="password", value=lambda: config_manager.PUSHOVER_CONFIG.get("user_key"))
                                            pushover_app_token_input = gr.Textbox(label="Pushover App Token/Key", type="password", value=lambda: config_manager.PUSHOVER_CONFIG.get("app_token"))
                                            save_pushover_config_button = gr.Button("Pushover設定を保存", variant="primary")
                                        with gr.Accordion("Discord", open=False):
                                            discord_webhook_input = gr.Textbox(label="Discord Webhook URL", type="password", value=lambda: config_manager.NOTIFICATION_WEBHOOK_URL_GLOBAL or "")
                                            save_discord_webhook_button = gr.Button("Discord Webhookを保存", variant="primary")
                                        with gr.Accordion("Tavily (Web検索)", open=False):
                                            tavily_key_input = gr.Textbox(label="Tavily API Key", type="password", value=lambda: config_manager.TAVILY_API_KEY)
                                            save_tavily_key_button = gr.Button("Tavilyキーを保存", variant="primary")
                                        gr.Warning("APIキーやWebhook URLはPC上の `config.json` ファイルに平文で保存されます。取り扱いには十分ご注意ください。")
                                with gr.TabItem("個別設定"):
                                    char_settings_info = gr.Markdown("ℹ️ *現在選択中のキャラクター「...」にのみ適用される設定です。*")
                                    char_model_dropdown = gr.Dropdown(label="使用するAIモデル（個別）", interactive=True)
                                    with gr.Accordion("🎤 音声設定", open=False):
                                        char_voice_dropdown = gr.Dropdown(label="声を選択（個別）", choices=list(config_manager.SUPPORTED_VOICES.values()), interactive=True)
                                        char_voice_style_prompt_textbox = gr.Textbox(label="音声スタイルプロンプト", placeholder="例：囁くように、楽しそうに、落ち着いたトーンで", interactive=True)
                                        with gr.Row():
                                            char_preview_text_textbox = gr.Textbox(value="こんにちは、Nexus Arkです。これは音声のテストです。", show_label=False, scale=3)
                                            char_preview_voice_button = gr.Button("試聴", scale=1)
                                    with gr.Accordion("🔬 AI生成パラメータ調整", open=False):
                                        gr.Markdown("このキャラクターの応答の「創造性」と「安全性」を調整します。")
                                        char_temperature_slider = gr.Slider(minimum=0.0, maximum=2.0, step=0.05, label="Temperature", info="値が高いほど、AIの応答がより創造的で多様になります。(推奨: 0.7 ~ 0.9)")
                                        char_top_p_slider = gr.Slider(minimum=0.0, maximum=1.0, step=0.01, label="Top-P", info="値が低いほど、ありふれた単語が選ばれやすくなります。(推奨: 0.95)")
                                        safety_choices = ["ブロックしない", "低リスク以上をブロック", "中リスク以上をブロック", "高リスクのみブロック"]
                                        with gr.Row():
                                            char_safety_harassment_dropdown = gr.Dropdown(choices=safety_choices, label="嫌がらせコンテンツ", interactive=True)
                                            char_safety_hate_speech_dropdown = gr.Dropdown(choices=safety_choices, label="ヘイトスピーチ", interactive=True)
                                        with gr.Row():
                                            char_safety_sexually_explicit_dropdown = gr.Dropdown(choices=safety_choices, label="性的コンテンツ", interactive=True)
                                            char_safety_dangerous_content_dropdown = gr.Dropdown(choices=safety_choices, label="危険なコンテンツ", interactive=True)
                                    gr.Markdown("#### APIコンテキスト設定")
                                    char_add_timestamp_checkbox = gr.Checkbox(label="メッセージにタイムスタンプを追加", interactive=True)
                                    char_send_thoughts_checkbox = gr.Checkbox(label="思考過程をAPIに送信", interactive=True)
                                    char_send_notepad_checkbox = gr.Checkbox(label="メモ帳の内容をAPIに送信", interactive=True)
                                    char_use_common_prompt_checkbox = gr.Checkbox(label="共通ツールプロンプトを注入", interactive=True)
                                    char_send_core_memory_checkbox = gr.Checkbox(label="コアメモリをAPIに送信", interactive=True)
                                    char_send_scenery_checkbox = gr.Checkbox(label="空間描写・設定をAPIに送信", interactive=True)
                                    gr.Markdown("---")
                                    save_char_settings_button = gr.Button("このキャラクターの設定を保存", variant="primary")

                        with gr.Accordion("🧑‍🤝‍🧑 グループ会話", open=False):
                            session_status_display = gr.Markdown("現在、1対1の会話モードです。")
                            participant_checkbox_group = gr.CheckboxGroup(
                                label="会話に招待するキャラクター",
                                choices=sorted([c for c in character_list_on_startup if c != effective_initial_character]),
                                interactive=True
                            )
                            with gr.Row():
                                start_session_button = gr.Button("このメンバーで会話を開始 / 更新", variant="primary")
                                end_session_button = gr.Button("会話を終了 (1対1に戻る)", variant="secondary")

                        with gr.Accordion("🗨️ 新しいルームを作成する", open=False):
                            with gr.Row():
                                new_character_name_textbox = gr.Textbox(placeholder="新しいルーム名", show_label=False, scale=3); add_character_button = gr.Button("作成", variant="secondary", scale=1)

                    with gr.Column(scale=3):
                        chatbot_display = gr.Chatbot(height=600, elem_id="chat_output_area", show_copy_button=True, show_label=False)
                        with gr.Row():
                            audio_player = gr.Audio(label="音声プレーヤー", visible=False, autoplay=True, interactive=True, elem_id="main_audio_player")
                        with gr.Row(visible=False) as action_button_group:
                            rerun_button = gr.Button("🔄 再生成")
                            play_audio_button = gr.Button("🔊 選択した発言を再生")
                            delete_selection_button = gr.Button("🗑️ 選択した発言を削除", variant="stop")
                            cancel_selection_button = gr.Button("✖️ 選択をキャンセル")
                        token_count_display = gr.Markdown("入力トークン数", elem_id="token_count_display")
                        tpm_note_display = gr.Markdown("(参考: Gemini 2.5 シリーズ無料枠TPM: 250,000)", elem_id="tpm_note_display")
                        chat_input_textbox = gr.Textbox(show_label=False, placeholder="メッセージを入力...", lines=3)
                        with gr.Row():
                            submit_button = gr.Button("送信", variant="primary")
                            chat_reload_button = gr.Button("🔄 履歴を更新")
                        allowed_file_types = ['.png', '.jpg', '.jpeg', '.webp', '.heic', '.heif', '.mp3', '.wav', '.flac', '.aac', '.mp4', '.mov', '.avi', '.webm', '.txt', '.md', '.py', '.js', '.html', '.css', '.pdf', '.xml', '.json']
                        file_upload_button = gr.Files(label="ファイル添付", type="filepath", file_count="multiple", file_types=allowed_file_types)
                        gr.Markdown(f"ℹ️ *複数のファイルを添付できます。対応形式: {', '.join(allowed_file_types)}*")

            with gr.TabItem(" 記憶・メモ・指示"):
                gr.Markdown("##  記憶・メモ・指示\nキャラクターの根幹をなす設定ファイルを、ここで直接編集できます。")
                with gr.Tabs():
                    with gr.TabItem("システムプロンプト"):
                        system_prompt_editor = gr.Textbox(label="システムプロンプト (System Prompt)", interactive=True, elem_id="system_prompt_editor", lines=20, autoscroll=True)
                        with gr.Row():
                            save_prompt_button = gr.Button("プロンプトを保存", variant="secondary")
                            reload_prompt_button = gr.Button("再読込", variant="secondary")
                    with gr.TabItem("記憶 (JSON)"):
                        memory_json_editor = gr.Code(label="主観的記憶（日記） - memory.json", language="json", interactive=True, elem_id="memory_json_editor_code", lines=20)
                        with gr.Row():
                            save_memory_button = gr.Button("主観的記憶を保存", variant="secondary")
                            reload_memory_button = gr.Button("再読込", variant="secondary")
                            core_memory_update_button = gr.Button("コアメモリを更新", variant="primary")
                    with gr.TabItem("客観的記憶 (MemOS)"):
                        gr.Markdown("## 客観的記憶 (MemOS) の管理")
                        gr.Markdown("過去の対話ログなどをMemOSに取り込み、AIの永続的な記憶を構築します。")
                        # ▼▼▼ 以下の <gr.Row> を追加 ▼▼▼
                        with gr.Row():
                            memos_import_button = gr.Button("過去ログを客観記憶(MemOS)に取り込む", variant="primary", scale=3)
                            importer_stop_button = gr.Button("処理を中断", variant="stop", visible=False, scale=1)
                        # ▲▲▲ ここまで ▲▲▲
                        gr.Markdown("---")
                        gr.Markdown("### 索引管理（旧機能）")
                        rag_update_button = gr.Button("手帳の索引を更新", variant="secondary", visible=False) # 機能は削除されたが、UIハンドラに残っているので一旦非表示
                    with gr.TabItem("メモ帳 (Markdown)"):
                        notepad_editor = gr.Textbox(label="メモ帳の内容", interactive=True, elem_id="notepad_editor_code", lines=20, autoscroll=True)
                        with gr.Row():
                            save_notepad_button = gr.Button("メモ帳を保存", variant="secondary")
                            reload_notepad_button = gr.Button("再読込", variant="secondary")
                            clear_notepad_button = gr.Button("メモ帳を全削除", variant="stop")

            with gr.TabItem("ワールド・ビルダー") as world_builder_tab:
                gr.Markdown("## ワールド・ビルダー\n`world_settings.txt` の内容を、直感的に、または直接的に編集・確認できます。")

                with gr.Tabs():
                    with gr.TabItem("構造化エディタ"):
                        gr.Markdown("エリアと場所を選択して、その内容をピンポイントで編集します。")
                        with gr.Row(equal_height=False):
                            with gr.Column(scale=1, min_width=250):
                                gr.Markdown("### 1. 編集対象を選択")
                                area_selector = gr.Dropdown(label="エリア (`##`)", interactive=True)
                                place_selector = gr.Dropdown(label="場所 (`###`)", interactive=True)
                                gr.Markdown("---")
                                add_area_button = gr.Button("エリアを新規作成")
                                add_place_button = gr.Button("場所を新規作成")
                                with gr.Column(visible=False) as new_item_form:
                                    new_item_form_title = gr.Markdown("#### 新規作成")
                                    new_item_type = gr.Textbox(visible=False)
                                    new_item_name = gr.Textbox(label="エリア名 / 場所名 (必須)", placeholder="例: メインエントランス")
                                    with gr.Row():
                                        confirm_add_button = gr.Button("決定", variant="primary")
                                        cancel_add_button = gr.Button("キャンセル")
                            with gr.Column(scale=3):
                                gr.Markdown("### 2. 内容を編集")
                                content_editor = gr.Textbox(label="世界設定を記述", lines=20, interactive=True, visible=False)
                                with gr.Row(visible=False) as save_button_row:
                                    save_button = gr.Button("この場所の設定を保存", variant="primary")
                                    delete_place_button = gr.Button("この場所を削除", variant="stop")

                    with gr.TabItem("RAWテキストエディタ"):
                        gr.Markdown("世界設定ファイル (`world_settings.txt`) の全体像を直接編集します。**書式（`##`や`###`）を崩さないようご注意ください。**")
                        world_settings_raw_editor = gr.Code( # 変数名を _raw_display から _raw_editor に変更
                            label="world_settings.txt",
                            language="markdown",
                            interactive=True, # 編集可能に
                            lines=25
                        )
                        with gr.Row():
                            save_raw_button = gr.Button("RAWテキスト全体を保存", variant="primary")
                            reload_raw_button = gr.Button("最後に保存した内容を読み込む", variant="secondary")

            with gr.TabItem("デバッグコンソール"):
                gr.Markdown("## デバッグコンソール\nアプリケーションの内部的な動作ログ（ターミナルに出力される内容）をここに表示します。")
                debug_console_output = gr.Textbox(
                    label="コンソール出力",
                    lines=30,
                    interactive=False,
                    autoscroll=True
                )
                clear_debug_console_button = gr.Button("コンソールをクリア", variant="secondary")

        # --- イベントハンドラ定義 ---
        context_checkboxes = [char_add_timestamp_checkbox, char_send_thoughts_checkbox, char_send_notepad_checkbox, char_use_common_prompt_checkbox, char_send_core_memory_checkbox, char_send_scenery_checkbox]
        context_token_calc_inputs = [current_character_name, current_api_key_name_state, api_history_limit_state] + context_checkboxes
        initial_load_chat_outputs = [
            current_character_name, chatbot_display, current_log_map_state, chat_input_textbox, profile_image_display,
            memory_json_editor, notepad_editor, system_prompt_editor,
            alarm_char_dropdown, timer_char_dropdown, location_dropdown,
            current_location_display, current_scenery_display, char_model_dropdown, char_voice_dropdown,
            char_voice_style_prompt_textbox,
            char_temperature_slider, char_top_p_slider,
            char_safety_harassment_dropdown, char_safety_hate_speech_dropdown,
            char_safety_sexually_explicit_dropdown, char_safety_dangerous_content_dropdown
        ] + context_checkboxes + [char_settings_info, scenery_image_display]
        initial_load_outputs = [alarm_dataframe, alarm_dataframe_original_data, selection_feedback_markdown] + initial_load_chat_outputs

        demo.load(fn=ui_handlers.handle_initial_load, inputs=None, outputs=initial_load_outputs).then(
            fn=ui_handlers.handle_context_settings_change, inputs=context_token_calc_inputs, outputs=token_count_display
        )

        char_change_world_builder_outputs = [world_data_state, area_selector, world_settings_raw_editor]

        start_session_button.click(
            fn=ui_handlers.handle_start_session,
            inputs=[current_character_name, participant_checkbox_group],
            outputs=[active_participants_state, session_status_display]
        )
        end_session_button.click(
            fn=ui_handlers.handle_end_session,
            inputs=[current_character_name, active_participants_state],
            outputs=[active_participants_state, session_status_display, participant_checkbox_group]
        )

        chat_inputs = [
            chat_input_textbox, current_character_name, current_api_key_name_state,
            file_upload_button, api_history_limit_state, debug_mode_checkbox,
            auto_memory_checkbox, # ★★★ 自動記憶チェックボックスを追加
            debug_console_state,
            active_participants_state
        ]

        rerun_button.click(
            fn=ui_handlers.handle_rerun_button_click,
            inputs=[
                selected_message_state, current_character_name, current_api_key_name_state,
                file_upload_button, api_history_limit_state, debug_mode_checkbox,
                auto_memory_checkbox, # ★★★ この行を新しく追加 ★★★
                debug_console_state,
                active_participants_state # ★★★ 'active_participants' から '_state' を付けた正しい変数名に変更 ★★★
            ],
            # outputsの最後に selected_message_state と action_button_group を追加
            outputs=[
                chatbot_display, current_log_map_state, chat_input_textbox, file_upload_button,
                token_count_display, current_location_display, current_scenery_display,
                alarm_dataframe_original_data, alarm_dataframe, scenery_image_display,
                debug_console_state, debug_console_output,
                selected_message_state, action_button_group  # ★ この2つを追加
            ]
            # ▲▲▲【修正ここまで】▲▲▲
        )

        all_char_change_outputs = initial_load_chat_outputs + char_change_world_builder_outputs + [
            active_participants_state, session_status_display, participant_checkbox_group
        ]

        character_dropdown.change(
            fn=ui_handlers.handle_character_change_for_all_tabs,
            inputs=[character_dropdown, api_key_dropdown],
            outputs=all_char_change_outputs
        ).then(
            fn=ui_handlers.handle_context_settings_change, inputs=context_token_calc_inputs, outputs=token_count_display
        )

        chat_reload_button.click(fn=ui_handlers.reload_chat_log, inputs=[current_character_name, api_history_limit_state], outputs=[chatbot_display, current_log_map_state])
        chatbot_display.select(
            fn=ui_handlers.handle_chatbot_selection,
            inputs=[current_character_name, api_history_limit_state, current_log_map_state],
            outputs=[selected_message_state, action_button_group, play_audio_button],
            show_progress=False
        )
        delete_selection_button.click(fn=ui_handlers.handle_delete_button_click, inputs=[selected_message_state, current_character_name, api_history_limit_state], outputs=[chatbot_display, current_log_map_state, selected_message_state, action_button_group])
        api_history_limit_dropdown.change(fn=ui_handlers.update_api_history_limit_state_and_reload_chat, inputs=[api_history_limit_dropdown, current_character_name], outputs=[api_history_limit_state, chatbot_display, current_log_map_state]).then(fn=ui_handlers.handle_context_settings_change, inputs=context_token_calc_inputs, outputs=token_count_display)

        chat_submit_outputs = [
            chatbot_display, current_log_map_state, chat_input_textbox, file_upload_button,
            token_count_display, current_location_display, current_scenery_display,
            alarm_dataframe_original_data, alarm_dataframe, scenery_image_display,
            debug_console_state, debug_console_output
        ]

        gen_settings_inputs = [
            char_temperature_slider, char_top_p_slider,
            char_safety_harassment_dropdown, char_safety_hate_speech_dropdown,
            char_safety_sexually_explicit_dropdown, char_safety_dangerous_content_dropdown
        ]
        save_char_settings_button.click(
            fn=ui_handlers.handle_save_char_settings,
            inputs=[current_character_name, char_model_dropdown, char_voice_dropdown, char_voice_style_prompt_textbox] + gen_settings_inputs + context_checkboxes,
            outputs=None
        )
        char_preview_voice_button.click(fn=ui_handlers.handle_voice_preview, inputs=[char_voice_dropdown, char_voice_style_prompt_textbox, char_preview_text_textbox, api_key_dropdown], outputs=[audio_player, play_audio_button, char_preview_voice_button])
        for checkbox in context_checkboxes: checkbox.change(fn=ui_handlers.handle_context_settings_change, inputs=context_token_calc_inputs, outputs=token_count_display)
        model_dropdown.change(fn=ui_handlers.update_model_state, inputs=[model_dropdown], outputs=[current_model_name]).then(fn=ui_handlers.handle_context_settings_change, inputs=context_token_calc_inputs, outputs=token_count_display)
        api_key_dropdown.change(fn=ui_handlers.update_api_key_state, inputs=[api_key_dropdown], outputs=[current_api_key_name_state]).then(fn=ui_handlers.handle_context_settings_change, inputs=context_token_calc_inputs, outputs=token_count_display)
        api_test_button.click(fn=ui_handlers.handle_api_connection_test, inputs=[api_key_dropdown], outputs=None)
        chat_input_textbox.submit(fn=ui_handlers.handle_message_submission, inputs=chat_inputs, outputs=chat_submit_outputs)
        submit_button.click(fn=ui_handlers.handle_message_submission, inputs=chat_inputs, outputs=chat_submit_outputs)
        token_calc_on_input_inputs = [current_character_name, current_api_key_name_state, api_history_limit_state, chat_input_textbox, file_upload_button] + context_checkboxes
        file_upload_button.upload(fn=ui_handlers.update_token_count_on_input, inputs=token_calc_on_input_inputs, outputs=token_count_display, show_progress=False)
        file_upload_button.clear(fn=ui_handlers.update_token_count_on_input, inputs=token_calc_on_input_inputs, outputs=token_count_display, show_progress=False)
        add_character_button.click(fn=ui_handlers.handle_add_new_character, inputs=[new_character_name_textbox], outputs=[character_dropdown, alarm_char_dropdown, timer_char_dropdown, new_character_name_textbox])
        refresh_scenery_button.click(fn=ui_handlers.handle_scenery_refresh, inputs=[current_character_name, api_key_dropdown], outputs=[current_location_display, current_scenery_display, scenery_image_display])
        location_dropdown.change(fn=ui_handlers.handle_location_change, inputs=[current_character_name, location_dropdown, api_key_dropdown], outputs=[current_location_display, current_scenery_display, scenery_image_display])
        play_audio_button.click(fn=ui_handlers.handle_play_audio_button_click, inputs=[selected_message_state, current_character_name, current_api_key_name_state], outputs=[audio_player, play_audio_button, char_preview_voice_button])
        cancel_selection_button.click(fn=lambda: (None, gr.update(visible=False)), inputs=None, outputs=[selected_message_state, action_button_group])

        save_prompt_button.click(fn=ui_handlers.handle_save_system_prompt, inputs=[current_character_name, system_prompt_editor], outputs=None)
        reload_prompt_button.click(fn=ui_handlers.handle_reload_system_prompt, inputs=[current_character_name], outputs=[system_prompt_editor])
        save_memory_button.click(fn=ui_handlers.handle_save_memory_click, inputs=[current_character_name, memory_json_editor], outputs=[memory_json_editor])
        reload_memory_button.click(fn=ui_handlers.handle_reload_memory, inputs=[current_character_name], outputs=[memory_json_editor])
        save_notepad_button.click(fn=ui_handlers.handle_save_notepad_click, inputs=[current_character_name, notepad_editor], outputs=[notepad_editor])
        reload_notepad_button.click(fn=ui_handlers.handle_reload_notepad, inputs=[current_character_name], outputs=[notepad_editor])
        clear_notepad_button.click(fn=ui_handlers.handle_clear_notepad_click, inputs=[current_character_name], outputs=[notepad_editor])
        alarm_dataframe.select(
            fn=ui_handlers.handle_alarm_selection_for_all_updates,
            inputs=[alarm_dataframe_original_data],
            outputs=[
                selected_alarm_ids_state, selection_feedback_markdown,
                alarm_add_button, alarm_context_input, alarm_char_dropdown,
                alarm_days_checkboxgroup, alarm_emergency_checkbox,
                alarm_hour_dropdown, alarm_minute_dropdown,
                editing_alarm_id_state, cancel_edit_button
            ],
            show_progress=False
        )
        enable_button.click(fn=lambda ids: ui_handlers.toggle_selected_alarms_status(ids, True), inputs=[selected_alarm_ids_state], outputs=[alarm_dataframe_original_data, alarm_dataframe])
        disable_button.click(fn=lambda ids: ui_handlers.toggle_selected_alarms_status(ids, False), inputs=[selected_alarm_ids_state], outputs=[alarm_dataframe_original_data, alarm_dataframe])
        delete_alarm_button.click(
            fn=ui_handlers.handle_delete_alarms_and_update_ui,
            inputs=[selected_alarm_ids_state],
            outputs=[
                alarm_dataframe_original_data, alarm_dataframe,
                selected_alarm_ids_state, selection_feedback_markdown
            ]
        )
        alarm_add_button.click(
            fn=ui_handlers.handle_add_or_update_alarm,
            inputs=[
                editing_alarm_id_state, alarm_hour_dropdown, alarm_minute_dropdown,
                alarm_char_dropdown, alarm_context_input, alarm_days_checkboxgroup,
                alarm_emergency_checkbox
            ],
            outputs=[
                alarm_dataframe_original_data, alarm_dataframe,
                alarm_add_button, alarm_context_input, alarm_char_dropdown,
                alarm_days_checkboxgroup, alarm_emergency_checkbox,
                alarm_hour_dropdown, alarm_minute_dropdown,
                editing_alarm_id_state, selected_alarm_ids_state,
                selection_feedback_markdown, cancel_edit_button
            ]
        )
        cancel_edit_button.click(
            fn=ui_handlers.handle_cancel_alarm_edit,
            inputs=None,
            outputs=[
                alarm_add_button, alarm_context_input, alarm_char_dropdown,
                alarm_days_checkboxgroup, alarm_emergency_checkbox,
                alarm_hour_dropdown, alarm_minute_dropdown,
                editing_alarm_id_state, selected_alarm_ids_state,
                selection_feedback_markdown, cancel_edit_button
            ]
        )
        timer_type_radio.change(fn=lambda t: (gr.update(visible=t=="通常タイマー"), gr.update(visible=t=="ポモドーロタイマー"), ""), inputs=[timer_type_radio], outputs=[normal_timer_ui, pomo_timer_ui, timer_status_output])
        timer_submit_button.click(fn=ui_handlers.handle_timer_submission, inputs=[timer_type_radio, timer_duration_number, pomo_work_number, pomo_break_number, pomo_cycles_number, timer_char_dropdown, timer_work_theme_input, timer_break_theme_input, api_key_dropdown, normal_timer_theme_input], outputs=[timer_status_output])

        notification_service_radio.change(fn=ui_handlers.handle_notification_service_change, inputs=[notification_service_radio], outputs=[])
        save_gemini_key_button.click(fn=ui_handlers.handle_save_gemini_key, inputs=[gemini_key_name_input, gemini_key_value_input], outputs=[api_key_dropdown])
        delete_gemini_key_button.click(fn=ui_handlers.handle_delete_gemini_key, inputs=[gemini_key_name_input], outputs=[api_key_dropdown])
        save_pushover_config_button.click(fn=ui_handlers.handle_save_pushover_config, inputs=[pushover_user_key_input, pushover_app_token_input], outputs=[])
        save_discord_webhook_button.click(fn=ui_handlers.handle_save_discord_webhook, inputs=[discord_webhook_input], outputs=[])
        save_tavily_key_button.click(fn=ui_handlers.handle_save_tavily_key, inputs=[tavily_key_input], outputs=[])
        auto_memory_checkbox.change(fn=ui_handlers.handle_auto_memory_change, inputs=[auto_memory_checkbox], outputs=None)
        # ▼▼▼ ここからが修正の核心 ▼▼▼

        # 1. memos_import_buttonのクリックイベントを 'import_event' という変数に格納する
        import_event = memos_import_button.click(
            fn=ui_handlers.handle_memos_batch_import,
            inputs=[current_character_name, debug_console_state],
            outputs=[
                memos_import_button,
                importer_stop_button,
                importer_process_state,
                debug_console_state,
                debug_console_output,
                chat_input_textbox,
                submit_button
            ]
        )

        # 2. importer_stop_buttonの 'cancels' 引数に、UI部品ではなく、上で作成したイベント変数を渡す
        importer_stop_button.click(
            fn=ui_handlers.handle_importer_stop,
            inputs=[importer_process_state],
            outputs=[
                memos_import_button,
                importer_stop_button,
                importer_process_state,
                chat_input_textbox,
                submit_button
            ],
            cancels=[import_event] # ★★★ memos_import_button から import_event に変更 ★★★
        )

        # ▲▲▲ ここまで ▲▲▲
        core_memory_update_button.click(fn=ui_handlers.handle_core_memory_update_click, inputs=[current_character_name, current_api_key_name_state], outputs=None)
        generate_scenery_image_button.click(fn=ui_handlers.handle_generate_or_regenerate_scenery_image, inputs=[current_character_name, api_key_dropdown, scenery_style_radio], outputs=[scenery_image_display])
        audio_player.stop(fn=lambda: gr.update(visible=False), inputs=None, outputs=[audio_player])

        world_builder_tab.select(
            fn=ui_handlers.handle_world_builder_load,
            inputs=[current_character_name],
            outputs=[world_data_state, area_selector, world_settings_raw_editor]
        )
        area_selector.change(
            fn=ui_handlers.handle_wb_area_select,
            inputs=[world_data_state, area_selector],
            outputs=[place_selector]
        )
        place_selector.change(
            fn=ui_handlers.handle_wb_place_select,
            inputs=[world_data_state, area_selector, place_selector],
            outputs=[content_editor, save_button_row, delete_place_button]
        )
        save_button.click(
            fn=ui_handlers.handle_wb_save,
            inputs=[current_character_name, world_data_state, area_selector, place_selector, content_editor],
            outputs=[world_data_state, world_settings_raw_editor]
        )
        delete_place_button.click(
            fn=ui_handlers.handle_wb_delete_place,
            inputs=[current_character_name, world_data_state, area_selector, place_selector],
            outputs=[world_data_state, area_selector, place_selector, content_editor, save_button_row, delete_place_button, world_settings_raw_editor]
        )
        add_area_button.click(
            fn=lambda: ("area", gr.update(visible=True), "#### 新しいエリアの作成"),
            outputs=[new_item_type, new_item_form, new_item_form_title]
        )
        add_place_button.click(
            fn=ui_handlers.handle_wb_add_place_button_click,
            inputs=[area_selector],
            outputs=[new_item_type, new_item_form, new_item_form_title]
        )
        confirm_add_button.click(
            fn=ui_handlers.handle_wb_confirm_add,
            inputs=[current_character_name, world_data_state, area_selector, new_item_type, new_item_name],
            outputs=[world_data_state, area_selector, place_selector, new_item_form, new_item_name, world_settings_raw_editor]
        )
        cancel_add_button.click(
            fn=lambda: (gr.update(visible=False), ""),
            outputs=[new_item_form, new_item_name]
        )
        save_raw_button.click(
            fn=ui_handlers.handle_save_world_settings_raw,
            inputs=[current_character_name, world_settings_raw_editor],
            outputs=[world_data_state, area_selector, place_selector]
        )
        reload_raw_button.click(
            fn=ui_handlers.handle_reload_world_settings_raw,
            inputs=[current_character_name],
            outputs=[world_settings_raw_editor]
        )

        clear_debug_console_button.click(
            fn=lambda: ("", ""),
            outputs=[debug_console_state, debug_console_output]
        )

        print("\n" + "="*60); print("アプリケーションを起動します..."); print(f"起動後、以下のURLでアクセスしてください。"); print(f"\n  【PCからアクセスする場合】"); print(f"  http://127.0.0.1:7860"); print(f"\n  【スマホからアクセスする場合（PCと同じWi-Fiに接続してください）】"); print(f"  http://<お使いのPCのIPアドレス>:7860"); print("  (IPアドレスが分からない場合は、PCのコマンドプロモートやターミナルで"); print("   `ipconfig` (Windows) または `ifconfig` (Mac/Linux) と入力して確認できます)"); print("="*60 + "\n")
        demo.queue().launch(server_name="0.0.0.0", server_port=7860, share=False, allowed_paths=["."])

except Exception as e:
    print("\n" + "X"*60); print("!!! [致命的エラー] アプリケーションの起動中に、予期せぬ例外が発生しました。"); print("X"*60); traceback.print_exc()
finally:
    utils.release_lock()
    if os.name == "nt": os.system("pause")
    else: input("続行するにはEnterキーを押してください...")
