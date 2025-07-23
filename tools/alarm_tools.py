# -*- coding: utf-8 -*-
import datetime
from dateutil.parser import parse
from langchain_core.tools import tool
import alarm_manager

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

        # 時刻の形式を検証
        try:
            time_obj = datetime.datetime.strptime(time, "%H:%M").time()
        except ValueError:
            return "【エラー】時刻の形式が不正です。HH:MM形式で指定してください。"

        # 日付の解釈
        if date:
            try:
                alarm_dt = parse(date)
                alarm_date = alarm_dt.date()
            except (ValueError, TypeError):
                 return f"【エラー】日付の表現 '{date}' を解釈できませんでした。"
        else:
            now = datetime.datetime.now()
            alarm_dt = now.replace(hour=time_obj.hour, minute=time_obj.minute, second=0, microsecond=0)
            if alarm_dt <= now:
                alarm_dt += datetime.timedelta(days=1)
            alarm_date = alarm_dt.date()

        # alarm_managerのadd_alarmを呼び出す
        # この時点では曜日指定は不要とし、毎日鳴るアラームとして登録する
        success = alarm_manager.add_alarm(
            hour=str(time_obj.hour).zfill(2),
            minute=str(time_obj.minute).zfill(2),
            character=character_name,
            days_ja=[], # 空リストを渡すと、alarm_manager側で全曜日に設定される
            message=alarm_message # 新しい引数としてメッセージを渡す
        )

        if success:
            formatted_date = alarm_date.strftime("%Y-%m-%d")
            return f"Success: Alarm with message '{alarm_message}' set for {formatted_date} {time}."
        else:
            return "【エラー】alarm_managerでのアラーム追加に失敗しました。"

    except Exception as e:
        return f"【エラー】アラーム設定中に予期せぬエラーが発生しました: {e}"
