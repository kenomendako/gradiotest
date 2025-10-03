# tools/space_tools.py (v20: Final Architecture)

import os
from langchain_core.tools import tool
from room_manager import get_world_settings_path
import utils
import constants
from typing import List, Dict, Any
import traceback

@tool
def set_current_location(location_id: str, room_name: str) -> str:
    """AIの現在地を設定する。"""
    if not location_id or not room_name:
        return "【Error】Internal tool error: Location ID and room name are required for execution."
    try:
        base_path = os.path.join(constants.ROOMS_DIR, room_name)
        location_file_path = os.path.join(base_path, "current_location.txt")
        with open(location_file_path, "w", encoding="utf-8") as f:
            f.write(location_id.strip())
        return f"Success: 現在地は '{location_id}' に設定されました。この移動タスクは完了です。次に、この結果をユーザーに報告してください。"
    except Exception as e:
        return f"【Error】現在地のファイル書き込みに失敗しました: {e}"

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
