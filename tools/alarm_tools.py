import uuid
import datetime
from langchain_core.tools import tool
from dateutil.parser import parse
from dateutil.relativedelta import relativedelta
import alarm_manager

def _parse_flexible_date(date_str: str) -> datetime.date:
    """ "tomorrow", "next monday" などの曖昧な日付表現を解釈する """
    today = datetime.date.today()
    if not date_str or date_str.lower() == "today":
        return today
    if date_str.lower() == "tomorrow":
        return today + datetime.timedelta(days=1)

    # "next monday", "next week" などを試す
    try:
        # dateutil.parserは非常に強力
        future_date = parse(date_str, default=datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0))
        return future_date.date()
    except (ValueError, TypeError):
        # パースに失敗した場合は今日を返す
        return today

@tool
def set_personal_alarm(time: str, alarm_message: str, character_name: str, date: str = None) -> str:
    """
    ユーザーとの対話の中で、未来の特定の日時に送信するためのパーソナルなアラームメッセージを設定する。
    time: "HH:MM"形式の時刻。
    alarm_message: 未来のその時間に送信する、AI自身の言葉で考え抜かれたメッセージ。
    character_name: アラームを設定するキャラクター名。
    date: "YYYY-MM-DD"や"tomorrow", "next monday"など、アラームを設定する日付。指定がなければ直近の未来の時刻。
    """
    try:
        alarm_dt_obj = parse(time)
        time_str = alarm_dt_obj.strftime("%H:%M")

        alarm_date_obj = _parse_flexible_date(date)

        # 時刻が過去で日付が今日の場合、日付を明日に設定
        now = datetime.datetime.now()
        if alarm_date_obj == now.date() and alarm_dt_obj.time() < now.time():
            alarm_date_obj += datetime.timedelta(days=1)

        alarm_date_str = alarm_date_obj.strftime("%Y-%m-%d")

        new_alarm = {
            "id": str(uuid.uuid4()),
            "time": time_str,
            "date": alarm_date_str, # 日付を保存
            "character": character_name,
            "alarm_message": alarm_message,
            "enabled": True,
            "days": [] # 日付指定なので曜日は空
        }

        if alarm_manager.add_alarm_entry(new_alarm):
            # ★★★ 変更点 ★★★
            # AIに「任務完了」を明確に伝えるメッセージを返す
            return f"Success: The alarm has been reliably set for {alarm_date_str} at {time_str}. The message to be sent is '{alarm_message}'. There is no need to set it again."
        else:
            return "Error: Failed to save the alarm entry."

    except Exception as e:
        return f"Error: An unexpected error occurred while setting the alarm. Details: {e}"
