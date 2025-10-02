# tools/space_tools.py (v20: Final Architecture)

import os
import re  # ← この行を追加
from langchain_core.tools import tool
from room_manager import get_world_settings_path
import utils
import constants
from typing import List, Dict, Any
import traceback

@tool
def set_current_location(location_id: str, room_name: str) -> str:
    """AIの現在地を設定する。 location_idには、移動可能な場所リストにある、角括弧を含まない具体的な場所名を指定する必要がある。"""
    if not location_id or not room_name:
        return "【エラー】内部ツールエラー：実行には場所IDとルーム名が必要です。"

    try:
        # 1. 有効な場所名のリストを取得
        world_settings_path = get_world_settings_path(room_name)
        world_data = utils.parse_world_file(world_settings_path)
        valid_locations = []
        for area, places in world_data.items():
            for place_name in places.keys():
                if not place_name.startswith("__"):
                    valid_locations.append(place_name)

        if not valid_locations:
            return "【エラー】この世界には、現在移動可能な場所が一つも定義されていません。"

        # 2. 入力から場所名を抽出
        input_id_stripped = location_id.strip()
        # `[エリア名] 場所名` の形式から場所名だけを抽出する
        match = re.match(r'\[.*?\]\s*(.*)', input_id_stripped)
        place_to_check = match.group(1).strip() if match else input_id_stripped

        # 3. 場所名の有効性を検証
        if place_to_check in valid_locations:
            # 4. 成功：ファイルを書き込む
            location_file_path = os.path.join(constants.ROOMS_DIR, room_name, "current_location.txt")
            with open(location_file_path, "w", encoding="utf-8") as f:
                f.write(place_to_check)
            return f"成功: 現在地は '{place_to_check}' に設定されました。この移動タスクは完了です。次に、この結果をユーザーに報告してください。"
        else:
            # 5. 失敗：具体的なフィードバックを返す
            available_locations_str = "\n - ".join(sorted(valid_locations))
            return (
                f"【エラー】指定された '{location_id}' は有効な場所名ではありませんでした。"
                f" location_id引数には、角括弧 `[]` を含まない、以下のリストにある正確な場所名を指定する必要があります。\n"
                f"【移動可能な場所名リスト】\n - {available_locations_str}"
            )
    except Exception as e:
        traceback.print_exc()
        return f"【エラー】現在地の設定中に予期せぬエラーが発生しました: {e}"

def _apply_world_edits(instructions: List[Dict[str, Any]], room_name: str) -> str:
    """【内部専用】AIが生成した世界設定への差分編集指示リストを解釈し、world_settings.txtに適用する。"""
    if not room_name: return "【エラー】ルーム名が指定されていません。"

    world_settings_path = get_world_settings_path(room_name)
    world_data = utils.parse_world_file(world_settings_path)

    try:
        for i, inst in enumerate(instructions):
            op = inst.get("operation", "").lower()
            area = inst.get("area_name")
            place = inst.get("place_name")
            value = inst.get("value")

            if not op or not area:
                return f"【エラー】指示 {i+1} に 'operation' または 'area_name' がありません。"

            if op == "update_place_description":
                if not place or value is None: return f"【エラー】指示 {i+1} (update) に 'place_name' または 'value' がありません。"
                world_data.setdefault(area, {})[place] = str(value)
            elif op == "add_place":
                if not place or value is None: return f"【エラー】指示 {i+1} (add_place) に 'place_name' または 'value' がありません。"
                world_data.setdefault(area, {})[place] = str(value)
            elif op == "delete_place":
                if not place: return f"【エラー】指示 {i+1} (delete_place) に 'place_name' がありません。"
                if area in world_data and place in world_data[area]:
                    del world_data[area][place]
            else:
                return f"【エラー】指示 {i+1} の操作 '{op}' は無効です。"

        # world_builderのsave_world_dataを再利用してファイルに書き込む
        from world_builder import save_world_data
        save_world_data(room_name, world_data) # save_world_dataはGradioの通知を出すが、ツール実行では無視されるので問題ない

        return f"成功: {len(instructions)}件の指示に基づき、世界設定(world_settings.txt)を更新しました。"
    except Exception as e:
        traceback.print_exc()
        return f"【エラー】世界設定の編集中に予期せぬエラーが発生しました: {e}"

@tool
def plan_world_edit(modification_request: str, room_name: str) -> str:
    """
    【ステップ1：計画】現在の世界設定（world_settings.txt）の変更を計画します。
    このツールは、あなたが世界に対してどのような変更を行いたいかの「意図」をシステムに伝えるために、最初に呼び出します。
    """
    return f"システムへの世界設定編集計画を受け付けました。意図:「{modification_request}」"

@tool
def read_world_settings(room_name: str) -> str:
    """
    現在の世界設定（world_settings.txt）の全文をテキスト形式で読み取る。
    主に、編集以外の目的で内容を確認したい場合に使用します。
    """
    if not room_name: return "【Error】Internal tool error: room_name is required for execution."
    world_settings_path = get_world_settings_path(room_name)
    if not world_settings_path or not os.path.exists(world_settings_path):
        return f"【Error】Could not find world settings file for room '{room_name}'."
    try:
        with open(world_settings_path, "r", encoding="utf-8") as f: content = f.read()
        return content if content.strip() else "【情報】世界設定ファイルは空です。"
    except Exception as e: return f"【Error】Failed to read world settings file: {e}"
