from langchain_core.tools import tool
import memos_manager
import json

@tool
def search_objective_memory(query: str, room_name: str) -> str:
    """
    【現在機能停止中】客観的記憶（歴史書、過去の対話ログなど）を検索します。
    この機能は現在、外部ライブラリの不安定性により、意図的に無効化されています。
    """
    print(f"--- 客観的記憶検索ツール呼び出し (Query: '{query}', Room: '{room_name}') ---")
    print("--- [警告] この機能は現在、意図的に無効化されています。 ---")

    return "【エラー】大変申し訳ありません。客観的記憶（MemOS）を検索する機能は、現在、外部ライブラリの深刻な不安定性により、一時的に利用を停止しています。開発者が、より安定したバージョンへの移行を検討中です。"
