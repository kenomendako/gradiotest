# tools/notepad_tools.py (v13: K.I.S.S.)

from langchain_core.tools import tool
import os
from room_manager import get_room_files_paths

@tool
def read_full_notepad(room_name: str) -> str:
    """短期記憶用のメモ帳の全内容を読み上げる。内容がなければその旨を伝える。"""
    _, _, _, _, notepad_path = get_room_files_paths(room_name)
    if not notepad_path or not os.path.exists(notepad_path):
        return "【メモ帳ファイルが見つかりません】"
    with open(notepad_path, 'r', encoding='utf-8') as f:
        content = f.read().strip()
        return content if content else "【メモ帳は空です】"

@tool
def write_full_notepad(full_content: str, room_name: str) -> str:
    """
    短期記憶用のメモ帳全体を、新しい内容で完全に上書きします。
    このツールを呼び出す前に、必ず`read_full_notepad`で現在の内容を読み取り、
    その内容を考慮した上で、最終的なメモ帳の全文を`full_content`引数に渡してください。
    full_content: 新しいメモ帳の完全な内容（テキスト）。
    """
    if not room_name:
        return "【エラー】ルーム名が必要です。"

    _, _, _, _, notepad_path = get_room_files_paths(room_name)
    if not notepad_path:
        return f"【エラー】ルーム'{room_name}'のメモ帳パスが見つかりません。"

    try:
        # full_contentがNoneの場合も考慮
        content_to_write = full_content or ""
        with open(notepad_path, 'w', encoding='utf-8') as f:
            f.write(content_to_write.strip() + "\n")
        return f"成功: メモ帳を完全に更新しました。"
    except Exception as e:
        return f"【エラー】メモ帳の上書き中に予期せぬエラーが発生しました: {e}"
