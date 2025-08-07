# tools/space_tools.py
import os
import json
import re
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
    location: "study"のような場所のID、または"書斎"のような日本語名を指定。
    """
    if not location or not character_name:
        return "【Error】Location and character name are required."

    # --- 世界設定を読み込む ---
    world_settings_path = get_world_settings_path(character_name)
    if not world_settings_path or not os.path.exists(world_settings_path):
        return f"【Error】Could not find world settings file for character '{character_name}'."
    from utils import parse_world_markdown
    world_data = parse_world_markdown(world_settings_path)
    if not world_data:
        return f"【Error】Could not load or parse world settings for '{character_name}'."

    final_id_to_set = None

    # --- 1. まず、渡された文字列が有効な「ID」として存在するかチェック ---
    from character_manager import find_space_data_by_id_recursive
    if find_space_data_by_id_recursive(world_data, location) is not None:
        final_id_to_set = location
        print(f"  - 入力 '{location}' は有効な場所IDとして直接認識されました。")
    else:
        # --- 2. IDとして見つからなければ、「名前」として検索を試みる ---
        print(f"  - 入力 '{location}' は直接的なIDではないため、名前として検索します...")
        id_from_name = find_location_id_by_name.func(location_name=location, character_name=character_name)
        if not id_from_name.startswith("【Error】"):
            final_id_to_set = id_from_name
            print(f"  - 名前 '{location}' から場所ID '{final_id_to_set}' を特定しました。")

    # --- 3. IDが確定したらファイルに書き込み、さもなければエラーを返す ---
    if final_id_to_set:
        try:
            base_path = os.path.join("characters", character_name)
            location_file_path = os.path.join(base_path, "current_location.txt")
            with open(location_file_path, "w", encoding="utf-8") as f:
                f.write(final_id_to_set.strip())
            return f"Success: Current location has been set to '{final_id_to_set}'."
        except Exception as e:
            return f"【Error】現在地のファイル書き込みに失敗しました: {e}"
    else:
        return f"【Error】場所 '{location}' は有効なIDまたは名前として見つかりませんでした。"

#
# tools/space_tools.py の一番下に、このコードブロックをそのまま追加してください
#
def _get_location_section(full_content: str, location_id: str) -> Optional[str]:
    """Markdownコンテンツから特定のIDのセクション（## または ###）を抽出する"""
    pattern = re.compile(
        rf"(^(?:##|###) {re.escape(location_id)}\s*\n.*?)(\n^(?:##|###) |\Z)",
        re.MULTILINE | re.DOTALL
    )
    match = pattern.search(full_content)
    return match.group(1).strip() if match else None

@tool
def read_world_settings(character_name: str = None) -> str:
    """
    世界設定ファイル（world_settings.md）の全ての情報をテキスト形式で読み取る。
    新しい場所を追加したり、既存の場所を編集する前に、まず全体の構造を把握するために使用する。
    """
    if not character_name:
        return "【Error】Character name is required."
    world_settings_path = get_world_settings_path(character_name)
    if not world_settings_path or not os.path.exists(world_settings_path):
        return f"【Error】Could not find world settings file for character '{character_name}'."
    try:
        with open(world_settings_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"【Error】Failed to read world settings file: {e}"

@tool
def read_specific_location_settings(location_id: str, character_name: str = None) -> str:
    """
    世界設定ファイルから、指定されたIDの場所（エリアまたは部屋）の定義だけを抽出して読み取る。
    """
    if not location_id or not character_name:
        return "【Error】Location ID and character name are required."

    full_content = read_world_settings.func(character_name=character_name)
    if full_content.startswith("【Error】"):
        return full_content

    section = _get_location_section(full_content, location_id)
    if section:
        return section
    else:
        return f"【Error】Location ID '{location_id}' not found in the world settings."

@tool
def update_location_settings(location_id: str, new_content: str, character_name: str = None) -> str:
    """
    世界設定ファイル内の指定されたIDの場所（エリアまたは部屋）の定義を、新しい内容で完全に上書きする。
    注意：このツールはセクション全体を置き換えるため、既存の内容に追記したい場合は、まずread_specific_location_settingsで読み取り、編集してからこのツールを使用すること。
    """
    if not all([location_id, new_content, character_name]):
        return "【Error】location_id, new_content, and character_name are required."

    world_settings_path = get_world_settings_path(character_name)
    if not world_settings_path or not os.path.exists(world_settings_path):
        return f"【Error】Could not find world settings file for character '{character_name}'."

    try:
        with open(world_settings_path, "r", encoding="utf-8") as f:
            full_content = f.read()

        section_to_replace = _get_location_section(full_content, location_id)

        if section_to_replace:
            # 既存のセクションを新しい内容で置換
            updated_content = full_content.replace(section_to_replace, new_content.strip())
        else:
            # 既存のセクションがない場合、ファイルの末尾に追記
            updated_content = full_content.strip() + "\n\n" + new_content.strip()

        with open(world_settings_path, "w", encoding="utf-8") as f:
            f.write(updated_content.strip() + "\n")

        return f"Success: World settings for '{location_id}' have been updated."
    except Exception as e:
        return f"【Error】Failed to update world settings: {e}"
