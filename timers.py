# timers.py (LangGraph対応版)

import time
import threading
import traceback
import gemini_api
import alarm_manager
import utils
import constants

class UnifiedTimer:
    def __init__(self, timer_type, character_name, api_key_name, **kwargs):
        self.timer_type = timer_type
        self.character_name = character_name
        self.api_key_name = api_key_name

        # タイマー種別に応じて引数を設定
        if self.timer_type == "通常タイマー":
            self.duration = kwargs.get('duration', 10) * 60  # 分を秒に変換
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
        """タイマーをバックグラウンドスレッドで開始する"""
        if self.timer_type == "通常タイマー":
            self.thread = threading.Thread(target=self._run_single_timer, args=(self.duration, self.theme, "通常タイマー"))
        elif self.timer_type == "ポモドーロタイマー":
            self.thread = threading.Thread(target=self._run_pomodoro)

        if self.thread:
            self.thread.daemon = True
            self.thread.start()

    def _run_single_timer(self, duration: float, theme: str, timer_id: str):
        """指定された時間待機し、その後通知処理を起動するワーカー"""
        try:
            print(f"--- [タイマー開始: {timer_id}] Duration: {duration}s, Theme: '{theme}' ---")
            self._stop_event.wait(duration) # sleepの代わりにevent.waitを使う

            if self._stop_event.is_set():
                print(f"--- [タイマー停止: {timer_id}] ユーザーにより停止されました ---")
                return

            print(f"--- [タイマー終了: {timer_id}] AIに応答生成を依頼します ---")

            # AIに渡すための、内部的なユーザーメッセージを合成
            synthesized_user_message = f"（システムタイマー：時間です。テーマ「{theme}」について、メッセージを伝えてください）"

            # invoke_nexus_agent に渡す引数を準備
            agent_args = (
                synthesized_user_message,
                self.character_name,
                self.api_key_name,
                None,  # file_input_list
                str(constants.DEFAULT_ALARM_API_HISTORY_TURNS), # api_history_limit_state
                False  # debug_mode_state
            )

            # AIに応答を生成させる
            response_data = gemini_api.invoke_nexus_agent(*agent_args)
            raw_response = response_data.get('response', '')
            response_text = utils.remove_thoughts_from_text(raw_response)

            if response_text and not response_text.startswith("[エラー"):
                # ログには、思考ログを含まないシステムメッセージと、思考ログを含む完全なAI応答を記録
                log_f, _, _, _, _ = utils.character_manager.get_character_files_paths(self.character_name)
                message_for_log = f"（システムタイマー：{theme}）"
                utils.save_message_to_log(log_f, "## システム(タイマー):", message_for_log)
                utils.save_message_to_log(log_f, f"## {self.character_name}:", raw_response)

                # 各種通知を送信
                alarm_manager.send_notification(self.character_name, response_text, {}) # alarm_configは空でOK
            else:
                print(f"警告: タイマー応答の生成に失敗。AIからの生応答: '{raw_response}'")

        except Exception as e:
            print(f"!! [タイマー実行エラー] {timer_id} の実行中に予期せぬエラー: {e} !!")
            traceback.print_exc()

    def _run_pomodoro(self):
        """ポモドーロサイクルの管理"""
        for i in range(self.cycles):
            if self._stop_event.is_set(): return

            # 作業タイマー
            self._run_single_timer(self.work_duration, self.work_theme, f"ポモドーロ作業 {i+1}/{self.cycles}")
            if self._stop_event.is_set(): return

            # 休憩タイマー（最後のサイクルでは実行しない）
            if i < self.cycles - 1:
                self._run_single_timer(self.break_duration, self.break_theme, f"ポモドーロ休憩 {i+1}/{self.cycles}")
                if self._stop_event.is_set(): return

        print("--- [ポモドーロタイマー] 全サイクル完了 ---")

    def stop(self):
        """タイマーを停止する"""
        self._stop_event.set()
