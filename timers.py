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
    def __init__(self, timer_type, room_name, api_key_name, **kwargs):
        self.timer_type = timer_type
        self.room_name = room_name
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

            log_f, _, _, _, _ = room_manager.get_room_files_paths(self.room_name)
            api_key = config_manager.GEMINI_API_KEYS.get(self.api_key_name)

            if not log_f or not api_key:
                print(f"警告: タイマー ({timer_id}) のルームファイルまたはAPIキーが見つからないため、処理をスキップします。")
                return

            from agent.graph import generate_scenery_context
            location_name, _, scenery_text = generate_scenery_context(self.room_name, api_key)

            agent_args_dict = {
                "character_to_respond": self.room_name,
                "api_key_name": self.api_key_name,
                "api_history_limit": str(constants.DEFAULT_ALARM_API_HISTORY_TURNS),
                "debug_mode": False,
                "history_log_path": log_f,
                "user_prompt_parts": [{"type": "text", "text": synthesized_user_message}],
                "soul_vessel_character": self.room_name,
                "active_participants": [],
                "shared_location_name": location_name,
                "shared_scenery_text": scenery_text,
            }

            final_response_text = ""
            for update in gemini_api.invoke_nexus_agent_stream(agent_args_dict):
                if "final_output" in update:
                    final_response_text = update["final_output"].get("response", "")
                    break

            raw_response = final_response_text
            response_text = utils.remove_thoughts_from_text(raw_response)

            if response_text and not response_text.startswith("[エラー"):
                message_for_log = f"（システムタイマー：{theme}）"
                utils.save_message_to_log(log_f, "## システム(タイマー):", message_for_log)
                utils.save_message_to_log(log_f, f"## {self.room_name}:", raw_response)

                alarm_manager.send_notification(self.room_name, response_text, {})

                if PLYER_AVAILABLE:
                    try:
                        display_message = (response_text[:250] + '...') if len(response_text) > 250 else response_text
                        notification.notify(
                            title=f"{self.room_name} タイマー",
                            message=display_message,
                            app_name="Nexus Ark",
                            timeout=20
                        )
                        print("PCデスクトップ通知を送信しました。")
                    except Exception as e:
                        print(f"PCデスクトップ通知の送信中にエラーが発生しました: {e}")

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
