# tools/memory_tools.py (v13: K.I.S.S.)

from langchain_core.tools import tool
import json
import datetime
import os
from room_manager import get_room_files_paths
from memory_manager import load_memory_data_safe

@tool
def read_full_memory(room_name: str) -> str:
    """
    あなたの「主観的記憶（日記）」である`memory.json`の全ての項目を、JSON形式で読み取ります。
    """
    if not room_name:
        return "【エラー】内部処理エラー: 引数 'room_name' が不足しています。"

    _, _, _, memory_json_path, _ = get_room_files_paths(room_name)
    if not memory_json_path:
        return f"【エラー】ルーム'{room_name}'の記憶ファイルパスが見つかりません。"

    memory_data = load_memory_data_safe(memory_json_path)
    if "error" in memory_data:
        return f"【エラー】記憶ファイルの読み込みに失敗: {memory_data['message']}"

    try:
        # secret_diaryは読み取りから除外する
        memory_data.pop("secret_diary", None)
        return json.dumps(memory_data, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"【エラー】記憶の読み取り中に予期せぬエラーが発生しました: {e}"

@tool
def write_full_memory(full_content: str, room_name: str) -> str:
    """
    あなたの「主観的記憶（日記）」である`memory.json`全体を、新しい内容で完全に上書きします。
    このツールを呼び出す前に、必ず`read_full_memory`で現在の内容を読み取り、
    その内容を考慮した上で、最終的な記憶の全文を`full_content`引数に渡してください。
    full_content: 新しい記憶の完全な内容（JSON形式の文字列）。
    """
    if not all([full_content, room_name]):
        return "【エラー】書き込む内容とルーム名が必要です。"

    _, _, _, memory_json_path, _ = get_room_files_paths(room_name)
    if not memory_json_path:
        return f"【エラー】ルーム'{room_name}'の記憶ファイルパスが見つかりません。"

    try:
        new_memory_data = json.loads(full_content)
        if not isinstance(new_memory_data, dict):
            return "【エラー】書き込む内容が有効なJSONオブジェクトではありません。"

        # 念のため、既存の秘密の日記があれば引き継ぐ
        existing_memory = load_memory_data_safe(memory_json_path)
        if "secret_diary" in existing_memory:
            new_memory_data["secret_diary"] = existing_memory["secret_diary"]

        new_memory_data["last_updated"] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        with open(memory_json_path, "w", encoding="utf-8") as f:
            json.dump(new_memory_data, f, indent=2, ensure_ascii=False)

        return f"成功: 主観的記憶(memory.json)を完全に更新しました。"

    except json.JSONDecodeError:
        return f"【エラー】書き込もうとしたテキストは、有効なJSON形式ではありませんでした。テキスト: {full_content[:200]}..."
    except Exception as e:
        return f"【エラー】記憶の上書き中に予期せぬエラーが発生しました: {e}"
