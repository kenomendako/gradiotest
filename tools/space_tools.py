# tools/space_tools.py (タスク簡素化対応版)

import os
import re
from typing import Optional
from langchain_core.tools import tool
from character_manager import get_world_settings_path
import utils

@tool
def set_current_location(location_id: str, character_name: str = None) -> str:
    """AIの現在地を設定する。世界のどこにいるかを宣言する。"""
    if not location_id or not character_name:
        return "【Error】Location ID and character name are required."
    try:
        base_path = os.path.join("characters", character_name)
        location_file_path = os.path.join(base_path, "current_location.txt")
        with open(location_file_path, "w", encoding="utf-8") as f:
            f.write(location_id.strip())
        return f"Success: Current location has been set to '{location_id}'."
    except Exception as e:
        return f"【Error】現在地のファイル書き込みに失敗しました: {e}"

@tool
def update_location_content(character_name: str, area_name: str, place_name: str, new_description: str) -> str:
    """【更新専用】既存の場所の説明文を更新する。"""
    if not all([character_name, area_name, place_name, new_description is not None]):
        return "【Error】character_name, area_name, place_name, and new_description are required."

    world_settings_path = get_world_settings_path(character_name)
    if not world_settings_path or not os.path.exists(world_settings_path):
        return f"【Error】Could not find world settings file for character '{character_name}'."

    try:
        with open(world_settings_path, "r", encoding="utf-8") as f:
            full_content = f.read()

        pattern = re.compile(
            rf"(^###\s*{re.escape(place_name)}\s*\n)(.*?)(?=\n^##\s|\n^###\s|\Z)",
            re.DOTALL | re.MULTILINE
        )

        match = pattern.search(full_content)
        if not match:
            return f"【Error】Place '{place_name}' in Area '{area_name}' not found."

        # ▼▼▼ 修正の核心 ▼▼▼
        # new_description を使って、セクション全体を再構築する
        updated_section = match.group(1) + new_description.strip()
        updated_content = full_content[:match.start()] + updated_section + full_content[match.end():]

        with open(world_settings_path, "w", encoding="utf-8") as f:
            f.write(updated_content)

        return f"Success: Description for '{place_name}' in Area '{area_name}' has been updated."
    except Exception as e:
        return f"【Error】Failed to update location content: {e}"

@tool
def add_new_location(character_name: str, area_name: str, new_place_name: str, description: str) -> str:
    """【新規作成専用】新しい場所を世界設定に追加する。"""
    if not all([character_name, area_name, new_place_name, description is not None]):
        return "【Error】character_name, area_name, new_place_name, and description are required."

    world_settings_path = get_world_settings_path(character_name)
    if not world_settings_path or not os.path.exists(world_settings_path):
        return f"【Error】Could not find world settings file for character '{character_name}'."

    try:
        with open(world_settings_path, "r+", encoding="utf-8") as f:
            full_content = f.read()

            world_data = utils.parse_world_file(world_settings_path)
            for area, places in world_data.items():
                if new_place_name in places:
                    return f"【Error】Place '{new_place_name}' already exists. Use 'update_location_content' to modify it."

            area_pattern = re.compile(rf"^##\s*{re.escape(area_name)}\s*$", re.MULTILINE)
            area_match = area_pattern.search(full_content)

            # ▼▼▼ 修正の核心 ▼▼▼
            new_place_text = f"\n### {new_place_name}\n{description.strip()}\n"

            if area_match:
                next_area_match = re.search(r"^##\s", full_content[area_match.end():], re.MULTILINE)
                if next_area_match:
                    insert_pos = area_match.end() + next_area_match.start()
                    updated_content = full_content[:insert_pos].rstrip() + "\n" + new_place_text + "\n" + full_content[insert_pos:]
                else:
                    updated_content = full_content.rstrip() + "\n" + new_place_text
            else:
                updated_content = full_content.rstrip() + f"\n\n## {area_name}\n{new_place_text}"

            f.seek(0); f.write(updated_content.strip() + "\n"); f.truncate()

        return f"Success: New location '{new_place_name}' has been added to Area '{area_name}'."
    except Exception as e:
        return f"【Error】Failed to add new location: {e}"

@tool
def read_world_settings(character_name: str) -> str:
    """世界設定(world_settings.txt)の全体を読む。編集前の確認用。"""
    if not character_name:
        return "【Error】character_name is required."

    world_settings_path = get_world_settings_path(character_name)
    if not world_settings_path or not os.path.exists(world_settings_path):
        return f"【Error】Could not find world settings file for character '{character_name}'."

    try:
        with open(world_settings_path, "r", encoding="utf-8") as f:
            content = f.read()
        return content if content.strip() else "【情報】世界設定ファイルは空です。"
    except Exception as e:
        return f"【Error】Failed to read world settings file: {e}"
