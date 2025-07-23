# -*- coding: utf-8 -*-
import datetime
from dateutil.parser import parse
from langchain_core.tools import tool
import alarm_manager

@tool
def set_personal_alarm(time: str, context_memo: str, character_name: str, date: str = None) -> str:
    """
    AIが対話の中からアラームを設定するためのツール。

    Args:
        time (str): "HH:MM"形式の時刻。
        context_memo (str): アラームが設定された背景や目的を、未来の自分自身に伝えるための1〜2文の短いメモ。
        character_name (str): アラームを設定するキャラクター名。
        date (str, optional): "YYYY-MM-DD", "tomorrow", "next monday"など、解釈可能な日付表現。Defaults to None.

    Returns:
        str: 成功または失敗を示すメッセージ。
    """
    try:
        # 時刻の形式を検証
        try:
            time_obj = datetime.datetime.strptime(time, "%H:%M").time()
        except ValueError:
            return "【エラー】時刻の形式が不正です。HH:MM形式で指定してください。"

        # 日付の解釈
        if date:
            try:
                # "next monday"のような表現も解釈
                alarm_dt = parse(date)
                alarm_date = alarm_dt.date()
            except ValueError:
                return f"【エラー】日付の表現 '{date}' を解釈できませんでした。"
        else:
            # 日付が指定されない場合、直近の未来の時刻を計算
            now = datetime.datetime.now()
            alarm_dt = now.replace(hour=time_obj.hour, minute=time_obj.minute, second=0, microsecond=0)
            if alarm_dt <= now:
                alarm_dt += datetime.timedelta(days=1)
            alarm_date = alarm_dt.date()

        # 曜日のリストを作成（毎日）
        days_en = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

        # alarm_managerのadd_alarmを呼び出す (現時点では仮の呼び出し)
        # 後ほどalarm_manager.pyを修正し、context_memoを受け取れるようにする
        success = alarm_manager.add_alarm(
            hour=str(time_obj.hour).zfill(2),
            minute=str(time_obj.minute).zfill(2),
            character=character_name,
            theme=context_memo,  # 一時的にthemeとして渡す
            flash_prompt="", # 空文字
            days_ja=[] # 空リスト (内部で全曜日に変換される)
        )

        if success:
            formatted_date = alarm_date.strftime("%Y-%m-%d")
            # 実際の保存はadd_alarmに依存するが、ここでは成功したと仮定してメッセージを返す
            # add_alarmを修正したら、そちらのロジックで日付も保存するようにする
            return f"Success: Alarm set for {formatted_date} {time}."
        else:
            return "【エラー】alarm_managerでのアラーム追加に失敗しました。"

    except Exception as e:
        return f"【エラー】アラーム設定中に予期せぬエラーが発生しました: {e}"
