# world_builder.py (最終確定版)

import os
import gradio as gr
from typing import Dict, Any
import yaml
import character_manager
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

        rooms = {k: v for k, v in area_data.items() if isinstance(v, dict) and 'name' in v}
        area_props = {k: v for k, v in area_data.items() if k not in rooms}

        if area_props:
            md_content += yaml.dump(area_props, allow_unicode=True, default_flow_style=False, sort_keys=False)
            md_content += "\n"

        for room_id, room_data in rooms.items():
            md_content += f"### {room_id}\n"
            md_content += yaml.dump(room_data, allow_unicode=True, default_flow_style=False, sort_keys=False)
            md_content += "\n"

    try:
        with open(world_settings_path, "w", encoding="utf-8") as f:
            f.write(md_content.strip())
        gr.Info(f"「{character_name}」の世界設定を保存しました。")
    except Exception as e:
        gr.Error(f"世界設定の保存中にエラーが発生しました: {e}")

def generate_details_markdown(data: Dict[str, Any]) -> str:
    """データから、表示用のMarkdownを生成する。"""
    if not data: return "← 左のパネルからエリアや部屋を選択してください。"

    parts = []
    if 'name' in data: parts.append(f"### {data['name']}")
    if 'description' in data: parts.append(f"{data['description']}\n---")

    for key, value in data.items():
        if key in ['name', 'description']: continue
        display_key = key.replace('_', ' ').capitalize()
        if isinstance(value, list):
            items = "\n".join([f"- `{k}`: {v}" for item in value if isinstance(item, dict) for k, v in item.items()])
            parts.append(f"**{display_key}:**\n{items}")
        elif isinstance(value, dict):
            items = "\n".join([f"- `{k}`: {v}" for k, v in value.items()])
            parts.append(f"**{display_key}:**\n{items}")
        else:
            parts.append(f"**{display_key}**: {value}")

    return "\n\n".join(parts)

def convert_data_to_yaml_str(data: Dict[str, Any]) -> str:
    """データ辞書を、編集用のYAML文字列に変換する。"""
    if not data: return ""
    return yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False, indent=2)
