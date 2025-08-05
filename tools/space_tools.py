# tools/space_tools.py
import os
import json
from typing import Optional
from langchain_core.tools import tool
from character_manager import get_world_settings_path
from memory_manager import load_memory_data_safe

@tool
def find_location_id_by_name(location_name: str, character_name: str = None) -> str:
    """
    「書斎」や「屋上テラス」といった日本語の場所名から、システムが使うための正式なID（例: "study", "Rooftop Terrace"）を検索して返す。
    """
    if not location_name or not character_name:
        return "【Error】Location name and character name are required."

    world_settings_path = get_world_settings_path(character_name)
    if not world_settings_path or not os.path.exists(world_settings_path):
        return f"【Error】Could not find world settings file for character '{character_name}'."

    from utils import parse_world_markdown
    world_data = parse_world_markdown(world_settings_path)
    if not world_data:
        return f"【Error】Could not load or parse world settings for '{character_name}'."

    # ▼▼▼ 新しい、堅牢な再帰検索ロジック ▼▼▼
    def find_id_recursive(data: dict) -> Optional[str]:
        # data自体が辞書でない場合は探索終了
        if not isinstance(data, dict):
            return None

        for key, value in data.items():
            # 値が辞書であり、'name'キーが探している名前と一致する場合
            if isinstance(value, dict) and value.get("name", "").lower() == location_name.lower():
                return key # IDであるキーを返す

            # さらに深い階層を探索
            found_id = find_id_recursive(value)
            if found_id:
                return found_id

        return None

    # トップレベルから探索を開始
    found_location_id = find_id_recursive(world_data)
    # ▲▲▲ 修正ここまで ▲▲▲

    if found_location_id:
        return found_location_id
    else:
        return f"【Error】Location '{location_name}' not found. Check for typos or define it first."


@tool
def set_current_location(location: str, character_name: str = None) -> str:
    """
    AIの現在地を設定する。この世界のどこにいるかを宣言するための、唯一の公式な手段。
    location: "study"のような場所のID、または"書斎"のような日本語名を指定。日本語名が指定された場合、自動でIDを検索します。
    """
    if not location or not character_name:
        return "【Error】Location and character name are required."

    # ▼▼▼ ここからが修正箇所 ▼▼▼
    world_settings_path = get_world_settings_path(character_name)
    if not world_settings_path or not os.path.exists(world_settings_path):
        return f"【Error】Could not find world settings file for character '{character_name}'."
    world_data = load_memory_data_safe(world_settings_path)
    if "error" in world_data:
        return f"【Error】Could not load world settings for '{character_name}'."

    location_to_set = None

    # 1. 渡された文字列がIDとして有効か、まずチェックする
    from character_manager import find_space_data_by_id_recursive
    if find_space_data_by_id_recursive(world_data, location):
        location_to_set = location
        print(f"  - '{location}' は有効な場所IDとして認識されました。")

    # 2. IDとして見つからなければ、名前として検索を試みる
    if not location_to_set:
        print(f"  - '{location}' は直接的なIDではないため、名前として検索します...")
        found_id_result = find_location_id_by_name.func(location_name=location, character_name=character_name)
        if not found_id_result.startswith("【Error】"):
            location_to_set = found_id_result
            print(f"  - 名前 '{location}' から場所ID '{location_to_set}' を特定しました。")

    # 3. それでも見つからなければ、明確なエラーを返す
    if not location_to_set:
        return f"【Error】場所 '{location}' は有効なIDまたは名前として見つかりませんでした。"

    try:
        base_path = os.path.join("characters", character_name)
        location_file_path = os.path.join(base_path, "current_location.txt")

        with open(location_file_path, "w", encoding="utf-8") as f:
            f.write(location_to_set.strip())

        return f"Success: Current location has been set to '{location_to_set}'."
    except Exception as e:
        return f"【Error】現在地のファイル書き込みに失敗しました: {e}"
    # ▲▲▲ 修正箇所ここまで ▲▲▲
