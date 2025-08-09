import os
import re
from typing import Optional
from langchain_core.tools import tool
from character_manager import get_world_settings_path
import utils

@tool
def set_current_location(location_id: str, character_name: str = None) -> str:
    """
    AIの現在地を設定する。この世界のどこにいるかを宣言するための、唯一の公式な手段。
    location_id: "書斎"のような場所の正式名称（IDを兼ねる）を指定。
    """
    if not location_id or not character_name:
        return "【Error】Location ID and character name are required."

    try:
        base_path = os.path.join("characters", character_name)
        location_file_path = os.path.join(base_path, "current_location.txt")
        # これからは、受け取った場所名をそのまま書き込む
        with open(location_file_path, "w", encoding="utf-8") as f:
            f.write(location_id.strip())
        return f"Success: Current location has been set to '{location_id}'."
    except Exception as e:
        return f"【Error】現在地のファイル書き込みに失敗しました: {e}"

@tool
def update_location_content(character_name: str, area_name: str, place_name: str, new_content: str) -> str:
    """
    【更新専用】既存の場所の自由記述テキストを更新する。
    """
    if not all([character_name, area_name, place_name, new_content is not None]):
        return "【Error】character_name, area_name, place_name, and new_content are required."

    world_settings_path = get_world_settings_path(character_name)
    if not world_settings_path or not os.path.exists(world_settings_path):
        return f"【Error】Could not find world settings file for character '{character_name}'."

    try:
        with open(world_settings_path, "r", encoding="utf-8") as f:
            full_content = f.read()

        # 正規表現で対象の場所のセクションを特定する
        # `re.escape`でユーザー入力を安全に扱う
        # DOTALLフラグで`.`が改行にもマッチするようにし、MULTILINEで`^`が各行頭にマッチするようにする
        pattern = re.compile(
            rf"(^###\s*{re.escape(place_name)}\s*\n)(.*?)(?=\n^##\s|\n^###\s|\Z)",
            re.DOTALL | re.MULTILINE
        )

        match_found = False

        def replace_content(match):
            nonlocal match_found
            match_found = True
            # new_contentの前後の空白を除去し、末尾に改行を追加
            return match.group(1) + new_content.strip() + "\n"

        updated_content, num_replacements = pattern.subn(replace_content, full_content)

        if not match_found or num_replacements == 0:
            return f"【Error】Place '{place_name}' in Area '{area_name}' not found. You cannot create a new place with this tool. Use 'add_new_location' instead."

        with open(world_settings_path, "w", encoding="utf-8") as f:
            f.write(updated_content)

        return f"Success: Content for '{place_name}' in Area '{area_name}' has been updated."
    except Exception as e:
        return f"【Error】Failed to update location content: {e}"

@tool
def add_new_location(character_name: str, area_name: str, new_place_name: str, initial_content: str) -> str:
    """
    【新規作成専用】新しい場所を世界設定に追加する。
    """
    if not all([character_name, area_name, new_place_name, initial_content is not None]):
        return "【Error】character_name, area_name, new_place_name, and initial_content are required."

    world_settings_path = get_world_settings_path(character_name)
    if not world_settings_path or not os.path.exists(world_settings_path):
        return f"【Error】Could not find world settings file for character '{character_name}'."

    try:
        with open(world_settings_path, "r+", encoding="utf-8") as f:
            full_content = f.read()

            # 既存の場所名と重複しないかチェック
            world_data = utils.parse_world_file(world_settings_path)
            for area, places in world_data.items():
                if new_place_name in places:
                    return f"【Error】Place '{new_place_name}' already exists in Area '{area}'. Use 'update_location_content' to modify it."

            # エリアが存在するかチェック
            area_pattern = re.compile(rf"^##\s*{re.escape(area_name)}\s*$", re.MULTILINE)
            area_match = area_pattern.search(full_content)

            new_place_text = f"\n### {new_place_name}\n{initial_content.strip()}\n"

            if area_match:
                # エリアが存在する場合、そのエリアの末尾に追加
                # 次の##見出しを探す
                next_area_match = re.search(r"^##\s", full_content[area_match.end():], re.MULTILINE)
                if next_area_match:
                    insert_pos = area_match.end() + next_area_match.start()
                    updated_content = full_content[:insert_pos].rstrip() + "\n" + new_place_text + full_content[insert_pos:].lstrip()
                else:
                    # ファイルの末尾に追加
                    updated_content = full_content.rstrip() + "\n" + new_place_text
            else:
                # エリアが存在しない場合、新しいエリアごと末尾に追加
                updated_content = full_content.rstrip() + f"\n\n## {area_name}\n{new_place_text}"

            f.seek(0)
            f.write(updated_content.strip() + "\n")
            f.truncate()

        return f"Success: New location '{new_place_name}' has been added to Area '{area_name}'."
    except Exception as e:
        return f"【Error】Failed to add new location: {e}"
