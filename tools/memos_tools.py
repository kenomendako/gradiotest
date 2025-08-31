# tools/memos_tools.py
from langchain_core.tools import tool
import memos_manager
import json
import traceback

@tool
def search_objective_memory(query: str, room_name: str) -> str:
    """
    客観的記憶（歴史書、過去の対話ログなど）を検索します。
    """
    print(f"--- 客観的記憶検索ツール呼び出し (Query: '{query}', Room: '{room_name}') ---")
    if not room_name:
        return "【エラー】引数 'room_name' は必須です。"
    try:
        mos = memos_manager.get_mos_instance(room_name)
        search_results = mos.search(query=query) # これが正しい呼び出し方
        return json.dumps(search_results, ensure_ascii=False, indent=2) if search_results else "[]"
    except Exception as e:
        print(f"客観的記憶の検索中にエラーが発生しました: {e}")
        traceback.print_exc()
        return f"【エラー】客観的記憶の検索中に予期せぬエラーが発生しました: {e}"
