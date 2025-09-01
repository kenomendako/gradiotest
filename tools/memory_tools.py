# tools/memory_tools.py (Phase 1 Temporary Stub)

from langchain_core.tools import tool
# import memos_manager # 存在しないので、この行は必ず削除する
import json
import traceback

@tool
def search_objective_memory(query: str, room_name: str) -> str:
    """
    【現在機能停止中】客観的記憶（歴史書、過去の対話ログなど）を検索します。
    """
    print(f"--- 客観的記憶検索ツール呼び出し (Query: '{query}', Room: '{room_name}') ---")
    # 新しいCogneeシステムが実装されるまで、機能が停止していることを示すエラーメッセージを返す
    return "【エラー】記憶システムの移行作業中のため、客観的記憶（Cognee）検索機能は現在利用できません。フェーズ3で実装予定です。"
