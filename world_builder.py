# world_builder.py

import os
import gradio as gr
from typing import Dict, Any, Optional, Tuple, List

import character_manager
import constants
from utils import parse_world_markdown

def get_world_data(character_name: str) -> Dict[str, Any]:
    """指定されたキャラクターの世界設定データを読み込んで返す。"""
    if not character_name:
        return {}
    world_settings_path = character_manager.get_world_settings_path(character_name)
    return parse_world_markdown(world_settings_path)

def format_property_for_display(key: str, value: Any) -> str:
    """プロパティのキーと値を、UI表示用のMarkdown文字列に変換する。"""
    display_key = key.replace('_', ' ').capitalize()

    if isinstance(value, list):
        if not value:
            return f"**{display_key}**: (なし)"

        list_items = ""
        for item in value:
            if isinstance(item, dict):
                # 辞書のリストの場合 (例: furniture)
                item_str = ", ".join([f"{k}: {v}" for k, v in item.items()])
                list_items += f"- {{{item_str}}}\n"
            else:
                # 単純なリストの場合 (例: color_palette)
                list_items += f"- {item}\n"
        return f"**{display_key}**:\n{list_items}"

    elif isinstance(value, dict):
        # 辞書の場合 (例: ambiance)
        dict_items = "\n".join([f"- **{k.capitalize()}**: {v}" for k, v in value.items()])
        return f"**{display_key}**:\n{dict_items}"

    else:
        # 単純な値の場合
        return f"**{display_key}**: {value}"

def generate_details_markdown(data: Dict[str, Any]) -> str:
    """指定された辞書データから、詳細表示用のMarkdown文字列を生成する。"""
    if not data:
        return "詳細を表示する項目を選択してください。"

    parts = []
    # 'name' と 'description' を特別扱いして先頭に持ってくる
    if 'name' in data:
        parts.append(f"### {data['name']}")
    if 'description' in data:
        parts.append(f"{data['description']}\n---")

    # 残りのプロパティを整形して追加
    for key, value in data.items():
        if key not in ['name', 'description']:
            parts.append(format_property_for_display(key, value))

    return "\n\n".join(parts)
