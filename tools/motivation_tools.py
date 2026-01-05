# tools/motivation_tools.py
from langchain_core.tools import tool
from motivation_manager import MotivationManager
from typing import List

@tool
def resolve_question(topic: str, room_name: str) -> str:
    """
    指定された「問い」が解決された（答えが得られた、または納得した）ことをシステムに報告します。
    topic: 解決された問いのトピック名（通知されたリストから正確に指定してください）。
    room_name: 現在のルーム名。
    """
    try:
        mm = MotivationManager(room_name)
        mm.resolve_questions([topic])
        return f"成功: 「{topic}」を解決済みとしてマークしました。あなたの好奇心が少し満たされました。"
    except Exception as e:
        return f"エラー: 問いの解決に失敗しました。 {e}"

@tool
def delete_question(topic: str, room_name: str) -> str:
    """
    指定された「問い」がもはや不要である、または興味がなくなった場合にリストから削除します。
    topic: 削除する問いのトピック名。
    room_name: 現在のルーム名。
    """
    try:
        mm = MotivationManager(room_name)
        mm.delete_questions([topic])
        return f"成功: 「{topic}」をリストから削除しました。"
    except Exception as e:
        return f"エラー: 問いの削除に失敗しました。 {e}"
