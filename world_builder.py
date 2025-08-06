# world_builder.py (編集機能追加版)

import os
import gradio as gr
from typing import Dict, Any, Optional, Tuple, List
import yaml

import character_manager
import constants
from utils import parse_world_markdown

def get_world_data(character_name: str) -> Dict[str, Any]:
    if not character_name: return {}
    world_settings_path = character_manager.get_world_settings_path(character_name)
    return parse_world_markdown(world_settings_path)

def save_world_data(character_name: str, world_data: Dict[str, Any]):
    """更新された世界設定データを、正しいMarkdown形式でファイルに保存する。"""
    if not character_name:
        gr.Warning("キャラクターが選択されていません。")
        return

    world_settings_path = character_manager.get_world_settings_path(character_name)
    md_content = ""

    for area_id, area_data in world_data.items():
        md_content += f"## {area_id}\n\n"

        rooms = {}
        area_props = {}
        for key, value in area_data.items():
            if isinstance(value, dict) and 'name' in value:
                rooms[key] = value
            else:
                area_props[key] = value

        if area_props:
            md_content += yaml.dump(area_props, allow_unicode=True, default_flow_style=False, sort_keys=False)
            md_content += "\n"

        for room_id, room_data in rooms.items():
            md_content += f"### {room_id}\n\n"
            md_content += yaml.dump(room_data, allow_unicode=True, default_flow_style=False, sort_keys=False)
            md_content += "\n"

    try:
        with open(world_settings_path, "w", encoding="utf-8") as f:
            f.write(md_content.strip())
        gr.Info(f"「{character_name}」の世界設定を保存しました。")
    except Exception as e:
        gr.Error(f"世界設定の保存中にエラーが発生しました: {e}")

def create_editor_ui_from_data(data: Dict[str, Any]) -> Tuple[List[gr.components.Component], List[Any], List[str]]:
    """データ辞書から、編集用のGradioコンポーネントリストを動的に生成する。"""
    components = []
    initial_values = []
    keys_order = []

    # name と description を特別扱いして先頭に
    for key in ['name', 'description']:
        if key in data:
            components.append(gr.Textbox(label=key.capitalize(), value=data[key]))
            initial_values.append(data[key])
            keys_order.append(key)

    # 残りのプロパティを処理
    for key, value in data.items():
        if key in ['name', 'description']: continue

        # 複雑なデータ型はYAMLエディタで、単純な文字列はテキストボックスで編集
        if isinstance(value, (dict, list)):
            yaml_str = yaml.dump(value, allow_unicode=True, default_flow_style=False, sort_keys=False)
            components.append(gr.Code(label=key.capitalize(), value=yaml_str, language='yaml'))
            initial_values.append(yaml_str)
        else:
            components.append(gr.Textbox(label=key.capitalize(), value=str(value)))
            initial_values.append(str(value))
        keys_order.append(key)

    return components, initial_values, keys_order
