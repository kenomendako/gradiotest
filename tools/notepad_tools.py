# tools/notepad_tools.py (v14: Final Fix)

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
def write_full_notepad(modification_request: str, room_name: str) -> str:
    """
    短期記憶用のメモ帳の変更を要求します。
    このツールは直接書き込みを行いません。システムがあなたの要求を解釈し、安全にファイルを更新します。
    modification_request: この書き込みがどのような変更意図で行われたかを記述した自然言語の文。（例：「今日のタスクを追加した」）
    """
    # この関数は safe_tool_executor によって仲介されるため、これはスキーマ定義のためのものです。
    return f"システムへのメモ帳更新要求を受け付けました。意図:「{modification_request}」"

def _write_notepad_file(full_content: str, room_name: str) -> str:
    """【内部専用】整形済みの完全な文字列を受け取り、notepad.mdに書き込む。"""
    if not room_name:
        return "【エラー】ルーム名が必要です。"
    _, _, _, _, notepad_path = get_room_files_paths(room_name)
    if not notepad_path:
        return f"【エラー】ルーム'{room_name}'のメモ帳パスが見つかりません。"
    try:
        content_to_write = full_content or ""
        with open(notepad_path, 'w', encoding='utf-8') as f:
            f.write(content_to_write.strip() + "\n")
        return "成功: メモ帳を完全に更新しました。"
    except Exception as e:
        return f"【エラー】メモ帳の上書き中に予期せぬエラーが発生しました: {e}"
