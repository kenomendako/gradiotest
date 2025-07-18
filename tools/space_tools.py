# tools/space_tools.py
import os
import json # ★ jsonをインポート
from langchain_core.tools import tool
from character_manager import get_character_files_paths
from memory_manager import load_memory_data_safe # ★ 記憶読み込み関数をインポート

@tool
def find_location_id_by_name(location_name: str, character_name: str = None) -> str:
    """
    「書斎」や「屋上テラス」といった日本語の場所名から、システムが使うための正式なID（例: "study", "rooftop_terrace"）を検索して返す。
    location_name: ユーザーが言及した場所の日本語名。
    """
    if not location_name or not character_name:
        return "【Error】Location name and character name are required."

    _, _, _, memory_json_path, _ = get_character_files_paths(character_name)
    if not memory_json_path:
        return f"【Error】Could not find memory file path for character '{character_name}'."

    memory_data = load_memory_data_safe(memory_json_path)
    if "error" in memory_data or "living_space" not in memory_data:
        return "【Error】Could not load living_space memory."

    living_space = memory_data.get("living_space", {})
    for location_id, details in living_space.items():
        if location_id.lower() == location_name.lower():
            return location_id
        if isinstance(details, dict) and details.get("name", "").lower() == location_name.lower():
            return location_id

    return f"【Error】Location '{location_name}' not found. Check for typos or define it first using edit_memory."


@tool
def set_current_location(location: str, character_name: str = None) -> str:
    """
    AIの現在地を設定する。この世界のどこにいるかを宣言するための、唯一の公式な手段。
    location: "study"のような場所のID、または"書斎"のような日本語名を指定。日本語名が指定された場合、自動でIDを検索します。
    """
    if not location or not character_name:
        return "【Error】Location and character name are required."

    found_id_result = find_location_id_by_name.func(location_name=location, character_name=character_name)

    if not found_id_result.startswith("【Error】"):
        location_to_set = found_id_result
        print(f"  - Identified location ID '{location_to_set}' from name '{location}'.")
    else:
        location_to_set = location
        print(f"  - Using '{location}' directly as location ID.")


    try:
        base_path = os.path.join("characters", character_name)
        location_file_path = os.path.join(base_path, "current_location.txt")

        with open(location_file_path, "w", encoding="utf-8") as f:
            f.write(location_to_set.strip())

        return f"Success: Current location has been set to '{location_to_set}'."
    except Exception as e:
        return f"【Error】Failed to set current location: {e}"
