# -*- coding: utf-8 -*-
import datetime
from dateutil.parser import parse
from langchain_core.tools import tool
import alarm_manager

import uuid

@tool
def set_personal_alarm(time: str, alarm_message: str, character_name: str, date: str = None) -> str:
    """
    AIが対話の中から考えたメッセージを使って、未来のアラームを設定するためのツール。

    Args:
        time (str): "HH:MM"形式の時刻。
        alarm_message (str): AIが考えた、未来の自分に送るための具体的なメッセージ。
        character_name (str): アラームを設定するキャラクター名。
        date (str, optional): "YYYY-MM-DD", "tomorrow", "next monday"など、解釈可能な日付表現。Defaults to None.

    Returns:
        str: 成功または失敗を示すメッセージ。
    """
    try:
        if not alarm_message or not alarm_message.strip():
            return "【エラー】`alarm_message`は空にできません。心のこもったメッセージを考えてください。"

        try:
            time_obj = datetime.datetime.strptime(time, "%H:%M").time()
        except ValueError:
            return "【エラー】時刻の形式が不正です。HH:MM形式で指定してください。"

        alarm_date_str = None
        days = []
        if date:
            try:
                alarm_dt = parse(date)
                alarm_date_str = alarm_dt.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                return f"【エラー】日付の表現 '{date}' を解釈できませんでした。"
        else:
            # 日付指定がない場合は毎日鳴るアラームとして設定
            days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

        new_alarm = {
            "id": str(uuid.uuid4()),
            "time": time,
            "character": character_name,
            "alarm_message": alarm_message,
            "enabled": True,
            "date": alarm_date_str,
            "days": days,
        }

        success = alarm_manager.add_alarm_entry(new_alarm)

        if success:
            display_date = alarm_date_str if alarm_date_str else "every day"
            return f"Success: Alarm with message '{alarm_message}' set for {display_date} at {time}."
        else:
            return "【エラー】alarm_managerでのアラーム追加に失敗しました。"

    except Exception as e:
        return f"【エラー】アラーム設定中に予期せぬエラーが発生しました: {e}"
