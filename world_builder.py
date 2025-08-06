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

def save_world_data(character_name: str, yaml_content: str):
    if not character_name:
        gr.Warning("キャラクターが選択されていません。")
        return
    world_settings_path = character_manager.get_world_settings_path(character_name)

    # 見出し構造を維持したまま、新しい内容を書き出す
    try:
        new_data = yaml.safe_load(yaml_content)
        md_content = ""
        for key, value in new_data.items():
            if key in ["name", "description"]:
                 md_content += f"{key}: {value}\n"
            else:
                 md_content += yaml.dump({key: value}, allow_unicode=True, default_flow_style=False, sort_keys=False)

        # 既存のファイルから、選択されたセクションの内容を置き換える (今後の高度な実装)
        # 今回は、ファイル全体をシンプルに上書きする

        # トップレベルの構造を再構築する必要がある
        # この関数は、編集された単一のセクション(エリアor部屋)のYAMLを受け取る
        # そのため、ファイル全体を再構築する必要がある
        # これは ui_handlers.py で行うべき

        # ここでは、渡されたYAMLコンテンツを直接ファイルに書き込む (ui_handlers側で全データを再構築)
        # save_world_data は、完全な world_data (辞書) を受け取るように変更する
        pass # ロジックを ui_handlers に移譲

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
