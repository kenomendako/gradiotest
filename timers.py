import time
import threading

class Timer:
    def __init__(self, duration, character_name, theme, api_key_name, webhook_url):
        self.duration = duration * 60  # 分を秒に変換
        self.character_name = character_name
        self.theme = theme
        self.api_key_name = api_key_name
        self.webhook_url = webhook_url
        self._timer_thread = None
        self._stop_event = threading.Event()

        # デフォルトテーマを適用するロジックを追加
        if not self.theme:
            self.theme = "時間になりました"

    def start(self):
        if self._timer_thread and self._timer_thread.is_alive():
            print("タイマーは既に動作中です。")
            return

        self._stop_event.clear()
        self._timer_thread = threading.Thread(target=self._run)
        self._timer_thread.start()

    def _run(self):
        print(f"タイマー開始: {self.duration}秒")
        start_time = time.time()
        while time.time() - start_time < self.duration:
            if self._stop_event.is_set():
                print("タイマーが停止されました。")
                return
            time.sleep(0.1)
        print("タイマー終了。アラーム処理を実行します。")
        from alarm_manager import trigger_alarm
        trigger_alarm({
            "character": self.character_name,
            "theme": self.theme,
            "time": "タイマー終了",
            "id": "タイマー"
        }, self.api_key_name, self.webhook_url)

    def stop(self):
        if self._timer_thread and self._timer_thread.is_alive():
            self._stop_event.set()
            self._timer_thread.join()

class PomodoroTimer:
    def __init__(self, work_duration, break_duration, cycles, work_callback, break_callback, work_theme="作業終了・休憩開始メッセージ", break_theme="休憩終了・作業開始メッセージ", api_key_name=None, webhook_url=None, character_name="Default"):
        self.work_duration = work_duration * 60  # 分を秒に変換
        self.break_duration = break_duration * 60  # 分を秒に変換
        self.cycles = cycles
        self.work_callback = work_callback
        self.break_callback = break_callback
        # デフォルトテーマを設定
        self.work_theme = work_theme if work_theme else "作業終了アラーム"
        self.break_theme = break_theme if break_theme else "休憩終了アラーム"
        self.api_key_name = api_key_name
        self.webhook_url = webhook_url
        self.character_name = character_name or "Default"  # キャラクター名がNoneの場合、デフォルトを設定
        self._pomodoro_thread = None
        self._stop_event = threading.Event()

    def start(self):
        if self._pomodoro_thread and self._pomodoro_thread.is_alive():
            print("ポモドーロタイマーは既に動作中です。")
            return

        self._stop_event.clear()
        self._pomodoro_thread = threading.Thread(target=self._run)
        self._pomodoro_thread.start()

    def _run(self):
        print(f"ポモドーロタイマー開始: 作業{self.work_duration}秒、休憩{self.break_duration}秒、サイクル{self.cycles}回")
        for cycle in range(self.cycles):
            if self._stop_event.is_set():
                print("ポモドーロタイマーが停止されました。")
                return

            print(f"サイクル {cycle + 1}/{self.cycles}: 作業タイマー開始")
            self._run_timer(self.work_duration, self.work_callback, self.work_theme, "作業タイマー")

            if self._stop_event.is_set():
                return

            print(f"サイクル {cycle + 1}/{self.cycles}: 休憩タイマー開始")
            self._run_timer(self.break_duration, self.break_callback, self.break_theme, "休憩タイマー")

        print("ポモドーロタイマー終了。")

    def _run_timer(self, duration, callback, theme, timer_id):
        start_time = time.time()
        while time.time() - start_time < duration:
            if self._stop_event.is_set():
                print(f"{timer_id}が停止されました。")
                return
            time.sleep(0.1)
        print(f"{timer_id}終了。コールバックを実行します。")
        callback()
        self._trigger_alarm(theme, timer_id)

    def _trigger_alarm(self, theme, timer_id):
        if self.api_key_name and self.webhook_url:
            print(f"{timer_id}終了。アラーム処理を実行します。")
            from alarm_manager import trigger_alarm
            from character_manager import log_to_character

            alarm_config = {
                "character": self.character_name,  # 選択されたキャラクター名を使用
                "theme": theme,
                "time": f"{timer_id}終了",
                "id": timer_id
            }
            trigger_alarm(alarm_config, self.api_key_name, self.webhook_url)

            # ログに記録
            log_message = f"## システム(アラーム):\n（システムアラーム：{timer_id} {theme}）"
            log_to_character(self.character_name, log_message)

    def stop(self):
        if self._pomodoro_thread and self._pomodoro_thread.is_alive():
            self._stop_event.set()
            self._pomodoro_thread.join()

# 統一されたアラーム・タイマー処理を追加
class UnifiedTimer:
    def __init__(self, timer_type, duration, work_duration, break_duration, cycles, character_name, work_theme, break_theme, api_key_name, webhook_url, normal_timer_theme=None):
        self.timer_type = timer_type
        self.duration = duration * 60 if duration else None  # 分を秒に変換
        self.work_duration = work_duration * 60 if work_duration else None
        self.break_duration = break_duration * 60 if break_duration else None
        self.cycles = cycles
        self.character_name = character_name
        self.work_theme = work_theme
        self.break_theme = break_theme
        self.api_key_name = api_key_name
        self.webhook_url = webhook_url
        self.normal_timer_theme = normal_timer_theme or "デフォルトの通常タイマーテーマ"
        self._stop_event = threading.Event()

    def start(self):
        if self.timer_type == "通常タイマー":
            self._start_normal_timer()
        elif self.timer_type == "ポモドーロタイマー":
            self._start_pomodoro_timer()

    def _start_normal_timer(self):
        print(f"通常タイマー開始: {self.duration}秒")
        threading.Thread(target=self._run_timer, args=(self.duration, self.normal_timer_theme, "通常タイマー")).start()

    def _start_pomodoro_timer(self):
        print(f"ポモドーロタイマー開始: 作業{self.work_duration}秒、休憩{self.break_duration}秒、サイクル{self.cycles}回")
        threading.Thread(target=self._run_pomodoro).start()

    def _run_timer(self, duration, theme, timer_id):
        start_time = time.time()
        while time.time() - start_time < duration:
            if self._stop_event.is_set():
                print(f"{timer_id}が停止されました。")
                return
            time.sleep(0.1)
        print(f"{timer_id}終了。アラーム処理を実行します。")
        from alarm_manager import trigger_alarm
        trigger_alarm({
            "character": self.character_name,
            "theme": theme,
            "time": f"{timer_id}終了",
            "id": timer_id
        }, self.api_key_name, self.webhook_url)

    def _run_pomodoro(self):
        for cycle in range(self.cycles):
            if self._stop_event.is_set():
                print("ポモドーロタイマーが停止されました。")
                return

            print(f"サイクル {cycle + 1}/{self.cycles}: 作業タイマー開始")
            self._run_timer(self.work_duration, self.work_theme, "作業タイマー")

            if self._stop_event.is_set():
                return

            print(f"サイクル {cycle + 1}/{self.cycles}: 休憩タイマー開始")
            self._run_timer(self.break_duration, self.break_theme, "休憩タイマー")

        print("ポモドーロタイマー終了。")

    def stop(self):
        self._stop_event.set()
