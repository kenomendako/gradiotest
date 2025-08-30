from langchain_core.tools import tool
import memos_manager
import json

@tool
def search_objective_memory(query: str, character_name: str) -> str:
    """
    客観的記憶（歴史書、過去の対話ログなど、事実に基づいた永続的な知識）を検索します。
    ユーザーとの過去の具体的なやり取り、または以前に学習した客観的な事実について確認したい場合に使用します。
    """
    try:
        # ▼▼▼【暫定対応】機能が不安定なため、一旦機能を無効化する▼▼▼
        raise NotImplementedError("【開発者より】現在、MemOSの検索機能は不安定なため、一時的に無効化されています。ご不便をおかけします。")
        # ▲▲▲【暫定対応ここまで】▲▲▲

    except Exception as e:
        print(f"客観的記憶の検索中にエラーが発生しました: {e}")
        return f"【エラー】客観的記憶の検索中に予期せぬエラーが発生しました: {e}"
