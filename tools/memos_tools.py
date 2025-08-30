from langchain_core.tools import tool
import memos_manager
import json

@tool
def search_objective_memory(query: str, room_name: str) -> str:
    """
    客観的記憶（歴史書、過去の対話ログなど、事実に基づいた永続的な知識）を検索します。
    ユーザーとの過去の具体的なやり取り、または以前に学習した客観的な事実について確認したい場合に使用します。
    """
    print(f"--- 客観的記憶検索ツール呼び出し (Query: '{query}', Room: '{room_name}') ---")
    if not room_name:
        return "【エラー】引数 'room_name' は必須です。"
    try:
        mos = memos_manager.get_mos_instance(room_name)

        search_results = mos.search(query=query)

        if not search_results:
            return "[]" # 結果がない場合は空のJSON配列を返す

        # 結果をJSON文字列に変換して返す
        return json.dumps(search_results, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"客観的記憶の検索中にエラーが発生しました: {e}")
        # traceback.print_exc() # デバッグ用にトレースバックを追加すると便利
        return f"【エラー】客観的記憶の検索中に予期せぬエラーが発生しました: {e}"
