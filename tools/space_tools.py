# tools/space_tools.py
import os
from langchain_core.tools import tool
from character_manager import get_character_files_paths

@tool
def set_current_location(location: str, character_name: str = None) -> str:
    """
    AIの現在地を設定する。この世界のどこにいるかを宣言するための、唯一の公式な手段。
    location: 部屋の名前など、現在地の名前。
    """
    if not location or not character_name:
        return "【エラー】場所とキャラクター名は必須です。"

    try:
        # このツールはログファイルや他のファイルは不要
        base_path = os.path.join("characters", character_name)
        location_file_path = os.path.join(base_path, "current_location.txt")

        with open(location_file_path, "w", encoding="utf-8") as f:
            f.write(location.strip())

        return f"成功: 現在地を「{location}」に設定しました。"
    except Exception as e:
        return f"【エラー】現在地の設定中にエラーが発生しました: {e}"

@tool
def find_location_id_by_name(location_name: str, character_name: str = None) -> str:
    """
    場所の日本語名（例：「書斎」）から、システムが使うための場所ID（例：「study」）を見つけ出す。
    """
    if not location_name or not character_name:
        return "【エラー】場所の名前とキャラクター名は必須です。"

    try:
        _, _, _, memory_json_path, _ = get_character_files_paths(character_name)
        if not memory_json_path or not os.path.exists(memory_json_path):
            return f"【エラー】キャラクター '{character_name}' の記憶ファイルが見つかりません。"

        with open(memory_json_path, 'r', encoding='utf-8') as f:
            memory_data = json.load(f)

        living_space = memory_data.get("living_space", {})
        for location_id, details in living_space.items():
            if isinstance(details, dict) and details.get("name") == location_name:
                return location_id

        return f"【エラー】指定された名前の場所「{location_name}」は見つかりませんでした。"
    except Exception as e:
        return f"【エラー】場所IDの検索中に予期せぬエラーが発生しました: {e}"
