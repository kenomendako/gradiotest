# tools/alarm_tools.py の内容を、以下のコードで完全に置き換えてください

import uuid
import datetime
from langchain_core.tools import tool
from dateutil.parser import parse, ParserError
import alarm_manager

def _parse_flexible_date(date_str: str) -> datetime.date:
    """ "tomorrow", "next monday" などの曖昧な日付表現を解釈し、具体的な日付を返す """
    today = datetime.date.today()
    if not date_str or date_str.lower() in ["today", "今日"]:
        return today
    if date_str.lower() in ["tomorrow", "明日"]:
        return today + datetime.timedelta(days=1)

    try:
        # dateutil.parserは非常に強力で、"next monday"なども解釈できる
        future_date = parse(date_str, default=datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0))
        return future_date.date()
    except (ValueError, TypeError, ParserError):
        # パースに失敗した場合は、今日の日付を返す
        return today

@tool
def set_personal_alarm(
    time: str,
    context_memo: str,
    character_name: str,
    date: str = None,
    days: list = None
) -> str:
    """
    ユーザーとの対話の中で、未来の特定の日時に送信するためのアラームを設定する。
    time: "HH:MM"形式の時刻。
    context_memo: アラームの目的や背景を要約した短いメモ。
    character_name: アラームを設定するキャラクター名。
    date: "YYYY-MM-DD"や"tomorrow"など、アラームを設定する単発の日付。
    days: ["Monday", "Friday"]など、アラームを繰り返す曜日のリスト。
    """
    try:
        alarm_dt_obj = parse(time)
        time_str = alarm_dt_obj.strftime("%H:%M")

        new_alarm = {
            "id": str(uuid.uuid4()),
            "time": time_str,
            "character": character_name,
            "context_memo": context_memo,
            "enabled": True
        }

        # 繰り返し設定 (days) が優先される
        if days and isinstance(days, list) and len(days) > 0:
            valid_days = [d.lower()[:3] for d in days] # "Monday" -> "mon"
            new_alarm["days"] = valid_days
            schedule_info = f"every {', '.join(days)}"
        else:
            alarm_date_obj = _parse_flexible_date(date)

            now = datetime.datetime.now()
            # 日付指定がなく、時刻がすでに過ぎている場合は明日扱いにする
            if date is None and alarm_dt_obj.time() < now.time():
                alarm_date_obj += datetime.timedelta(days=1)

            alarm_date_str = alarm_date_obj.strftime("%Y-%m-%d")
            new_alarm["date"] = alarm_date_str
            new_alarm["days"] = [] # 単発なので曜日は空
            schedule_info = f"for {alarm_date_str}"

        if alarm_manager.add_alarm_entry(new_alarm):
            # ★★★ 変更点 ★★★
            # AIに「任務完了」を明確に伝える、完全なメッセージを返す
            return f"Success: The alarm has been reliably set {schedule_info} at {time_str}. The memo is '{context_memo}'. There is no need to set it again."
        else:
            return "Error: Failed to save the alarm entry."

    except Exception as e:
        return f"Error: An unexpected error occurred. Details: {e}"
