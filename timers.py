import time
import threading

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
