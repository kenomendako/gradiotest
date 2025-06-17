# timers.py (修正後)
import time
import threading
import traceback

class UnifiedTimer:
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls):
        with cls._lock:
            if cls._instance is None:
                print("情報: UnifiedTimerのシングルトンインスタンスを初回作成します。")
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        if UnifiedTimer._instance is not None:
            raise Exception("このクラスはシングルトンです！ get_instance() を使用してください。")

        self.timer_thread = None
        self._stop_event = threading.Event()

        # タイマー設定値をインスタンス変数として保持
        self.character_name = None
        self.api_key_name = None
        self.webhook_url = None
        self.timer_type = None

        # 通常タイマー用
        self.duration = None
        self.normal_timer_theme = None

        # ポモドーロタイマー用
        self.work_duration = None
        self.break_duration = None
        self.cycles = None
        self.work_theme = None
        self.break_theme = None

    def set_properties(self, character_name, api_key_name, webhook_url):
        self.character_name = character_name
        self.api_key_name = api_key_name
        self.webhook_url = webhook_url

    def set_normal_timer(self, duration, theme):
        self.timer_type = "通常タイマー"
        self.duration = duration
        self.normal_timer_theme = theme

    def set_pomodoro(self, work_duration, break_duration, cycles, work_theme, break_theme):
        self.timer_type = "ポモドーロタイマー"
        self.work_duration = work_duration
        self.break_duration = break_duration
        self.cycles = cycles
        self.work_theme = work_theme
        self.break_theme = break_theme

    def start(self):
        if self.is_running():
            print("警告: 既にタイマーが実行中です。新しいタイマーは開始されません。")
            return

        self._stop_event.clear()

        if self.timer_type == "通常タイマー":
            self.timer_thread = threading.Thread(target=self._run_timer, args=(self.duration, self.normal_timer_theme, "通常タイマー"), daemon=True)
            self.timer_thread.start()
        elif self.timer_type == "ポモドーロタイマー":
            self.timer_thread = threading.Thread(target=self._run_pomodoro, daemon=True)
            self.timer_thread.start()
        else:
            print("エラー: タイマー種別が設定されていません。")

    def _run_timer(self, duration, theme, timer_id):
        from alarm_manager import trigger_alarm # Late import to avoid circular dependency issues at module load time
        print(f"タイマー「{timer_id}」開始: {duration}秒")

        # stop_event.wait(timeout) は、イベントがセットされるかタイムアウトするまで待機
        # 停止されればTrue、タイムアウトすればFalseを返す
        if self._stop_event.wait(duration):
            print(f"タイマー「{timer_id}」が外部から停止されました。")
            return

        print(f"タイマー「{timer_id}」終了。アラーム処理を実行します。")
        try:
            # アラーム処理を呼び出し
            trigger_alarm({
                "character": self.character_name,
                "theme": theme,
                "time": f"{timer_id}終了",
                "id": timer_id,
                "flash_prompt_template": None
            }, self.api_key_name, self.webhook_url)
        except Exception as e:
            print(f"タイマー「{timer_id}」からのアラームトリガー中にエラーが発生しました: {e}")
            traceback.print_exc()

    def _run_pomodoro(self):
        print(f"ポモドーロタイマー開始: 作業{self.work_duration}秒, 休憩{self.break_duration}秒, {self.cycles}サイクル")
        for cycle in range(self.cycles):
            if self._stop_event.is_set():
                print("ポモドーロタイマーがサイクル開始前に停止されました。")
                return

            print(f"サイクル {cycle + 1}/{self.cycles}: 作業開始")
            self._run_timer(self.work_duration, self.work_theme, "作業タイマー")
            if self._stop_event.is_set(): break

            if cycle < self.cycles - 1: # 最後の作業の後には休憩しない
                print(f"サイクル {cycle + 1}/{self.cycles}: 休憩開始")
                self._run_timer(self.break_duration, self.break_theme, "休憩タイマー")
                if self._stop_event.is_set(): break

        print("ポモドーロタイマーの全サイクルが終了または停止しました。")

    def stop(self):
        if self.is_running():
            print("タイマースレッドに停止信号を送信します。")
            self._stop_event.set()
            self.timer_thread.join(timeout=2) # スレッドの終了を待つ
            if self.timer_thread.is_alive():
                print("警告: タイマースレッドが時間内に正常に停止しませんでした。")
            else:
                print("タイマースレッドが正常に停止しました。")
        self.timer_thread = None # Clear the thread reference

    def is_running(self):
        return self.timer_thread is not None and self.timer_thread.is_alive()
