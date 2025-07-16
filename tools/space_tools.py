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
        return "【エラー】場所名とキャラクター名は必須です。"

    _, _, _, memory_json_path, _ = get_character_files_paths(character_name)
    if not memory_json_path:
        return f"【エラー】キャラクター'{character_name}'の記憶ファイルパスが見つかりません。"

    memory_data = load_memory_data_safe(memory_json_path)
    if "error" in memory_data or "living_space" not in memory_data:
        return "【エラー】living_spaceの記憶が読み込めません。"

    living_space = memory_data.get("living_space", {})
    for location_id, details in living_space.items():
        # location_id自体が一致する場合も考慮
        if location_id.lower() == location_name.lower():
            return location_id
        # detailsが辞書であり、'name'キーが存在する場合にチェック
        if isinstance(details, dict) and details.get("name", "").lower() == location_name.lower():
            return location_id

    return f"【エラー】場所「{location_name}」が見つかりませんでした。typoの可能性、または先にedit_memoryで場所を定義する必要があるかもしれません。"


@tool
def set_current_location(location: str, character_name: str = None) -> str:
    """
    AIの現在地を設定する。この世界のどこにいるかを宣言するための、唯一の公式な手段。
    location: "study"のような場所のID、または"書斎"のような日本語名を指定。日本語名が指定された場合、自動でIDを検索します。
    """
    if not location or not character_name:
        return "【エラー】場所とキャラクター名は必須です。"

    # まず、与えられたlocationが日本語名かもしれないのでIDを検索する
    found_id = find_location_id_by_name.func(location_name=location, character_name=character_name)

    # 検索結果を評価
    if found_id and not found_id.startswith("【エラー】"):
        location_to_set = found_id
        print(f"  - 場所名'{location}'からID'{location_to_set}'を特定しました。")
    else:
        # IDが見つからなかった場合、元のlocationをそのまま使う（英語ID直接指定のケース）
        location_to_set = location
        print(f"  - 場所名'{location}'をIDとして直接使用します。")


    try:
        base_path = os.path.join("characters", character_name)
        location_file_path = os.path.join(base_path, "current_location.txt")

        # ★★★ 最終的にファイルに書き込むのは、特定したID ★★★
        with open(location_file_path, "w", encoding="utf-8") as f:
            f.write(location_to_set.strip())

        return f"成功: 現在地を「{location_to_set}」に設定しました。"
    except Exception as e:
        return f"【エラー】現在地の設定中にエラーが発生しました: {e}"
