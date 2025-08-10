# timers.py (デスクトップ通知対応版)

import time
import threading
import traceback
import gemini_api
import alarm_manager
import utils
import constants

# --- plyerのインポートと存在チェック ---
try:
    from plyer import notification
    PLYER_AVAILABLE = True
except ImportError:
    print("情報: 'plyer'ライブラリが見つかりません。PCデスクトップ通知機能は無効になります。")
    PLYER_AVAILABLE = False
# --- ここまで ---

class UnifiedTimer:
    def __init__(self, timer_type, character_name, api_key_name, **kwargs):
        self.timer_type = timer_type
        self.character_name = character_name
        self.api_key_name = api_key_name

        if self.timer_type == "通常タイマー":
            self.duration = kwargs.get('duration', 10) * 60
            self.theme = kwargs.get('normal_timer_theme', '時間になりました')
        elif self.timer_type == "ポモドーロタイマー":
            self.work_duration = kwargs.get('work_duration', 25) * 60
            self.break_duration = kwargs.get('break_duration', 5) * 60
            self.cycles = kwargs.get('cycles', 4)
            self.work_theme = kwargs.get('work_theme', '作業終了の時間です')
            self.break_theme = kwargs.get('break_theme', '休憩終了の時間です')

        self._stop_event = threading.Event()
        self.thread = None

    def start(self):
        if self.timer_type == "通常タイマー":
            self.thread = threading.Thread(target=self._run_single_timer, args=(self.duration, self.theme, "通常タイマー"))
        elif self.timer_type == "ポモドーロタイマー":
            self.thread = threading.Thread(target=self._run_pomodoro)

        if self.thread:
            self.thread.daemon = True
            self.thread.start()

    def _run_single_timer(self, duration: float, theme: str, timer_id: str):
        try:
            print(f"--- [タイマー開始: {timer_id}] Duration: {duration}s, Theme: '{theme}' ---")
            self._stop_event.wait(duration)

            if self._stop_event.is_set():
                print(f"--- [タイマー停止: {timer_id}] ユーザーにより停止されました ---")
                return

            print(f"--- [タイマー終了: {timer_id}] AIに応答生成を依頼します ---")

            synthesized_user_message = f"（システムタイマー：時間です。テーマ「{theme}」について、メッセージを伝えてください）"

            agent_args = (
                synthesized_user_message, self.character_name, self.api_key_name,
                None, str(constants.DEFAULT_ALARM_API_HISTORY_TURNS), False
            )

            response_data = gemini_api.invoke_nexus_agent(*agent_args)
            raw_response = response_data.get('response', '')
            response_text = utils.remove_thoughts_from_text(raw_response)

            if response_text and not response_text.startswith("[エラー"):
                log_f, _, _, _, _ = utils.character_manager.get_character_files_paths(self.character_name)
                message_for_log = f"（システムタイマー：{theme}）"
                utils.save_message_to_log(log_f, "## システム(タイマー):", message_for_log)
                utils.save_message_to_log(log_f, f"## {self.character_name}:", raw_response)

                alarm_manager.send_notification(self.character_name, response_text, {})

                # --- ▼▼▼ デスクトップ通知ロジックを追加 ▼▼▼ ---
                if PLYER_AVAILABLE:
                    try:
                        display_message = (response_text[:250] + '...') if len(response_text) > 250 else response_text
                        notification.notify(
                            title=f"{self.character_name} タイマー",
                            message=display_message,
                            app_name="Nexus Ark",
                            timeout=20
                        )
                        print("PCデスクトップ通知を送信しました。")
                    except Exception as e:
                        print(f"PCデスクトップ通知の送信中にエラーが発生しました: {e}")
                # --- ▲▲▲ ここまで ▲▲▲

            else:
                print(f"警告: タイマー応答の生成に失敗。AIからの生応答: '{raw_response}'")

        except Exception as e:
            print(f"!! [タイマー実行エラー] {timer_id} の実行中に予期せぬエラー: {e} !!")
            traceback.print_exc()

    def _run_pomodoro(self):
        for i in range(self.cycles):
            if self._stop_event.is_set():
                print("--- [ポモドーロタイマー] ユーザーにより停止されました ---")
                return

            print(f"--- [ポモドーロ開始: 作業 {i+1}/{self.cycles}] ---")
            self._run_single_timer(self.work_duration, self.work_theme, f"ポモドーロ作業 {i+1}/{self.cycles}")
            if self._stop_event.is_set():
                print("--- [ポモドーロタイマー] ユーザーにより停止されました ---")
                return

            print(f"--- [ポモドーロ開始: 休憩 {i+1}/{self.cycles}] ---")
            self._run_single_timer(self.break_duration, self.break_theme, f"ポモドーロ休憩 {i+1}/{self.cycles}")

        print("--- [ポモドーロタイマー] 全サイクル完了 ---")

    def stop(self):
        self._stop_event.set()
