import uuid
import datetime
from typing import List, Optional
from langchain_core.tools import tool
from dateutil.parser import parse
import alarm_manager

@tool
def set_personal_alarm(
    time: str,
    context_memo: str,
    character_name: str,
    date: Optional[str] = None,
    days: Optional[List[str]] = None
) -> str:
    """
    ユーザーとの対話の目的や背景に基づき、未来のアラームを設定する。
    time: "HH:MM"形式の時刻。
    context_memo: アラームの目的や背景を要約した短いメモ。
    character_name: アラームを設定するキャラクター名。
    date: "YYYY-MM-DD"形式の特定の日付。単発アラームの場合に指定。
    days: 曜日のリスト(例: ["mon", "fri"])。繰り返しアラームの場合に指定。
    """
    try:
        # 時刻の形式を検証
        try:
            time_obj = datetime.datetime.strptime(time, "%H:%M").time()
        except ValueError:
            return "【エラー】時刻の形式が不正です。HH:MM形式で指定してください。"

        # 日付と曜日の妥当性チェック
        if date and days:
            return "【エラー】`date`と`days`を同時に指定することはできません。単発か繰り返しのどちらか一方を選択してください。"

        # アラームオブジェクトの作成
        new_alarm = {
            "id": str(uuid.uuid4()),
            "time": time,
            "character": character_name,
            "context_memo": context_memo,
            "enabled": True,
            "date": date,
            "days": days if days else [],
        }

        # 保存処理
        if alarm_manager.add_alarm_entry(new_alarm):
            if date:
                return f"Success: A single-shot alarm has been set for {date} at {time} with the memo: '{context_memo}'."
            elif days:
                return f"Success: A recurring alarm has been set for {', '.join(days)} at {time} with the memo: '{context_memo}'."
            else:
                # dateもdaysも指定されない場合は、直近の未来の単発アラームとして扱う
                now = datetime.datetime.now()
                alarm_dt = now.replace(hour=time_obj.hour, minute=time_obj.minute, second=0, microsecond=0)
                if alarm_dt <= now:
                    alarm_dt += datetime.timedelta(days=1)
                new_alarm["date"] = alarm_dt.strftime("%Y-%m-%d")
                # 再度保存処理を呼ぶ必要がある
                # alarms.jsonはload_alarmsが呼ばれるまで更新されないため、一旦削除して追加し直す
                alarm_manager.delete_alarm(new_alarm["id"])
                alarm_manager.add_alarm_entry(new_alarm)
                return f"Success: A single-shot alarm has been set for {new_alarm['date']} at {time} with the memo: '{context_memo}'."
        else:
            return "Error: Failed to save the alarm entry."

    except Exception as e:
        return f"Error: An unexpected error occurred while setting the alarm. Details: {e}"
