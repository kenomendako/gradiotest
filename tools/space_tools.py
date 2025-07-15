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
