# tools/timer_tools.py

import threading
from langchain_core.tools import tool
from timers import UnifiedTimer # 新しいタイマー管理クラスをインポート
import config_manager # api_key_nameなどを取得するためにインポート
from typing import Optional

@tool
def set_timer(duration_minutes: int, theme: str, character_name: str) -> str:
    """指定分数後に通知するタイマーを設定する。"""
    if not character_name:
        return "エラー: 通知するキャラクターが指定されていません。"
    try:
        # 現在のAPIキー名などをconfig_managerから取得
        api_key_name = config_manager.initial_api_key_name_global

        timer = UnifiedTimer(
            timer_type="通常タイマー",
            duration=float(duration_minutes),
            character_name=character_name,
            api_key_name=api_key_name,
            normal_timer_theme=theme
        )
        # バックグラウンドでタイマーを開始
        timer.start()
        return f"Success: A timer has been set for {duration_minutes} minutes with the theme '{theme}'. You will be notified by {character_name}."
    except Exception as e:
        return f"Error: Failed to set the timer. Details: {e}"

@tool
def set_pomodoro_timer(work_minutes: int, break_minutes: int, cycles: int, work_theme: str, break_theme: str, character_name: str) -> str:
    """作業と休憩を繰り返すポモドーロタイマーを設定する。"""
    if not character_name:
        return "エラー: 通知するキャラクターが指定されていません。"
    try:
        api_key_name = config_manager.initial_api_key_name_global

        timer = UnifiedTimer(
            timer_type="ポモドーロタイマー",
            work_duration=float(work_minutes),
            break_duration=float(break_minutes),
            cycles=int(cycles),
            character_name=character_name,
            work_theme=work_theme,
            break_theme=break_theme,
            api_key_name=api_key_name
        )
        timer.start()
        return f"Success: A Pomodoro timer has been set for {cycles} cycles ({work_minutes} min work, {break_minutes} min break). You will be notified by {character_name}."
    except Exception as e:
        return f"Error: Failed to set the Pomodoro timer. Details: {e}"
