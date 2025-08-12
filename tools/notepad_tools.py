# tools/notepad_tools.py
import os
import datetime
import re
from langchain_core.tools import tool
from character_manager import get_character_files_paths

def _read_notepad(character_name: str) -> list[str]:
    """メモ帳を読み込んで行のリストを返す内部関数"""
    _, _, _, _, notepad_path = get_character_files_paths(character_name)
    if not notepad_path or not os.path.exists(notepad_path):
        return []
    with open(notepad_path, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f.readlines() if line.strip()]

def _write_notepad(character_name: str, lines: list[str]):
    """行のリストをメモ帳に書き込む内部関数"""
    _, _, _, _, notepad_path = get_character_files_paths(character_name)
    if not notepad_path:
        print(f"エラー: キャラクター '{character_name}' のメモ帳パスが見つかりませんでした。")
        return
    content_to_write = '\n'.join(lines)
    if content_to_write:
        content_to_write += '\n'
    with open(notepad_path, 'w', encoding='utf-8') as f:
        f.write(content_to_write)

@tool
def add_to_notepad(entry: str, character_name: str = None) -> str:
    """メモ帳にタイムスタンプ付きで一行追記する。"""
    if not entry or not isinstance(entry, str) or not entry.strip():
        return "【エラー】メモに追加する内容が空です。"
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    cleaned_entry = re.sub(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\]\s*", "", entry.strip())
    full_entry = f"[{timestamp}] {cleaned_entry}"
    lines = _read_notepad(character_name)
    lines.append(full_entry)
    _write_notepad(character_name, lines)
    return f'Success: The entry "{cleaned_entry}" was added to the notepad.'

@tool
def update_notepad(old_entry: str, new_entry: str, character_name: str = None) -> str:
    """メモ帳の項目を更新または削除する。old_entryで最新の項目を検索し、new_entryで置換。new_entryが空なら削除。"""
    if not old_entry or not isinstance(old_entry, str) or not old_entry.strip():
        return "【エラー】更新/削除対象のキーワードが空です。"

    lines = _read_notepad(character_name)
    keyword = old_entry.strip()

    target_index = -1
    original_line = ""
    for i in range(len(lines) - 1, -1, -1):
        if keyword in lines[i]:
            target_index = i
            original_line = lines[i]
            break

    if target_index == -1:
        return f'Error: No entry containing the keyword "{keyword}" was found.'

    lines.pop(target_index)

    if new_entry and isinstance(new_entry, str) and new_entry.strip():
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
        cleaned_new_entry = re.sub(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\]\s*", "", new_entry.strip())
        full_new_entry = f"[{timestamp}] {cleaned_new_entry}"
        lines.append(full_new_entry)
        _write_notepad(character_name, lines)
        return f'Success: The entry "{original_line}" was updated to "{cleaned_new_entry}".'
    else:
        _write_notepad(character_name, lines)
        return f'Success: The entry "{original_line}" was deleted from the notepad.'

@tool
def delete_from_notepad(entry_to_delete: str, character_name: str = None) -> str:
    """メモ帳から項目を削除する。entry_to_deleteで最新の項目を検索し、削除。"""
    # ★★★ この関数自身のロジックで削除を行うように変更 ★★★
    if not entry_to_delete or not isinstance(entry_to_delete, str) or not entry_to_delete.strip():
        return "【エラー】削除対象のキーワードが空です。"

    lines = _read_notepad(character_name)
    keyword = entry_to_delete.strip()

    target_index = -1
    original_line = ""
    for i in range(len(lines) - 1, -1, -1):
        if keyword in lines[i]:
            target_index = i
            original_line = lines[i]
            break

    if target_index != -1:
        lines.pop(target_index)
        _write_notepad(character_name, lines)
        return f'Success: The entry "{original_line}" was deleted from the notepad.'
    else:
        return f'Error: No entry containing the keyword "{keyword}" was found to delete.'

@tool
def read_full_notepad(character_name: str = None) -> str:
    """メモ帳の全内容を読む。"""
    lines = _read_notepad(character_name)
    if not lines:
        return "【メモ帳は空です】"
    notepad_text = "\n".join(lines)
    return f"【現在のメモ帳の内容】\n{notepad_text}"
