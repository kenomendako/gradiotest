# tools/notepad_tools.py
import os
import datetime # ★★★ datetime をインポート
from langchain_core.tools import tool
from character_manager import get_character_files_paths # character_manager から関数をインポート

def _read_notepad(character_name: str) -> list[str]:
    """メモ帳を読み込んで行のリストを返す内部関数"""
    _, _, _, _, notepad_path = get_character_files_paths(character_name)
    if not notepad_path or not os.path.exists(notepad_path): # notepad_path が None の場合も考慮
        return []
    with open(notepad_path, 'r', encoding='utf-8') as f:
        # 空行や前後の空白を除いた行のみをリストに追加
        return [line.strip() for line in f.readlines() if line.strip()]

def _write_notepad(character_name: str, lines: list[str]):
    """行のリストをメモ帳に書き込む内部関数"""
    _, _, _, _, notepad_path = get_character_files_paths(character_name)
    if not notepad_path: # notepad_path が None の場合は書き込みを行わない
        print(f"エラー: キャラクター '{character_name}' のメモ帳パスが見つかりませんでした。書き込みをスキップします。")
        return
    with open(notepad_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n') # 各行の後に改行を入れ、最後に余分な改行があっても良いようにする

@tool
def add_to_notepad(entry: str, character_name: str) -> str:
    """短期記憶用のメモ帳に、現在時刻のタイムスタンプを付けて新しい項目を一行追記する。"""
    if not entry or not isinstance(entry, str) or not entry.strip():
        return "【エラー】メモに追加する内容が空です。"

    # ★★★ ここからが修正箇所 ★★★
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    full_entry = f"[{timestamp}] {entry.strip()}" # entryもstripする

    lines = _read_notepad(character_name)
    lines.append(full_entry) # full_entryは既にstripされたentryを含んでいる
    _write_notepad(character_name, lines)
    # ★★★ 修正ここまで ★★★
    return f'Success: The entry "{entry.strip()}" was added to the notepad.'

@tool
def update_notepad(old_entry: str, new_entry: str, character_name: str) -> str:
    """短期記憶用のメモ帳の既存の項目を更新する。完全に一致する項目を見つけて書き換える。"""
    if not old_entry or not isinstance(old_entry, str) or not old_entry.strip():
        return "【エラー】更新対象の古い項目が空です。"
    if not new_entry or not isinstance(new_entry, str) or not new_entry.strip():
        return "【エラー】更新後の新しい項目が空です。"

    lines = _read_notepad(character_name)
    old_entry_stripped = old_entry.strip()
    new_entry_stripped = new_entry.strip()

    if old_entry_stripped in lines:
        try:
            index = lines.index(old_entry_stripped)
            lines[index] = new_entry_stripped
            _write_notepad(character_name, lines)
            return f'Success: The entry "{old_entry_stripped}" was updated.'
        except ValueError:
            # 基本的には old_entry_stripped in lines でチェックされるが、念のため
            return f"Error: An issue occurred while processing the entry to be updated."
    else:
        return f'Error: The entry to be updated "{old_entry_stripped}" was not found.'

@tool
def delete_from_notepad(entry_to_delete: str, character_name: str) -> str:
    """短期記憶用のメモ帳から既存の項目を削除する。完全に一致する項目を見つけて削除する。"""
    if not entry_to_delete or not isinstance(entry_to_delete, str) or not entry_to_delete.strip():
        return "【エラー】削除対象の項目が空です。"

    lines = _read_notepad(character_name)
    entry_to_delete_stripped = entry_to_delete.strip()

    if entry_to_delete_stripped in lines:
        lines.remove(entry_to_delete_stripped)
        _write_notepad(character_name, lines)
        return f'Success: The entry "{entry_to_delete_stripped}" was deleted.'
    else:
        return f'Error: The entry to be deleted "{entry_to_delete_stripped}" was not found.'

@tool
def read_full_notepad(character_name: str) -> str:
    """短期記憶用のメモ帳の全内容を読み上げる。内容がなければその旨を伝える。"""
    lines = _read_notepad(character_name)
    if not lines:
        return "【メモ帳は空です】"

    # 読み上げ用に、各行を番号付きリスト形式の文字列として結合
    # numbered_lines = [f"{i+1}. {line}" for i, line in enumerate(lines)]
    # return "【現在のメモ帳の内容】:\n" + "\n".join(numbered_lines)
    # AI Studioの方針では、直接 gemini_api.py でシステムプロンプトに埋め込むため、
    # このツールは純粋に内容を返すだけで良いかもしれない。
    # ただし、エージェントが「メモを見せて」と言った時に使えるように、整形して返すのもあり。
    # ここでは、AI Studioの方針（ステップ4）と整合性を取るため、整形せずに結合した文字列を返す。
    # あるいは、エージェントが直接内容を参照できるので、このツール自体不要かもしれない。
    # AI Studioの方針ではこのツールは定義されていないが、あると便利なので追加しておく。
    # (ステップ4でシステムプロンプトにメモが埋め込まれるなら、このツールは不要になる可能性が高い)
    # → ステップ4の実装を踏まえ、このツールは「現在のメモ帳の内容」を返すシンプルなものとする。
    #    エージェントが明示的に「メモを見せて」と指示した際に、整形された形でユーザーに提示するのに役立つ。
    notepad_text = "\n".join(lines)
    return f"【現在のメモ帳の内容】\n{notepad_text}"
