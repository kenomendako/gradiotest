# tools/memory_tools.py (v20: Final Architecture)

from langchain_core.tools import tool
import json
import datetime
from room_manager import get_room_files_paths
from memory_manager import load_memory_data_safe
from typing import List, Dict, Any
import traceback
import os

@tool
def read_full_memory(room_name: str) -> str:
    """
    あなたの「主観的記憶（日記）」である`memory.json`の全ての項目を、JSON形式で読み取ります。
    主に、編集以外の目的で内容を確認したい場合に使用します。
    """
    if not room_name:
        return "【エラー】内部処理エラー: 引数 'room_name' が不足しています。"
    _, _, _, memory_json_path, _ = get_room_files_paths(room_name)
    if not memory_json_path:
        return f"【エラー】ルーム'{room_name}'の記憶ファイルパスが見つかりません。"
    memory_data = load_memory_data_safe(memory_json_path)
    if "error" in memory_data:
        return f"【エラー】記憶ファイルの読み込みに失敗: {memory_data['message']}"
    try:
        return json.dumps(memory_data, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"【エラー】記憶の読み取り中に予期せぬエラーが発生しました: {e}"

@tool
def plan_memory_edit(modification_request: str, room_name: str) -> str:
    """
    【ステップ1：計画】あなたの「主観的記憶（日記）」である`memory.json`の変更を計画します。
    このツールは、あなたが記憶に対してどのような変更を行いたいかの「意図」をシステムに伝えるために、最初に呼び出します。
    """
    return f"システムへの記憶編集計画を受け付けました。意図:「{modification_request}」"

def _apply_memory_edits(instructions: List[Dict[str, Any]], room_name: str) -> str:
    """【内部専用】AIが生成した差分編集指示リストを解釈し、memory.jsonに適用する。"""
    if not room_name: return "【エラー】ルーム名が指定されていません。"
    _, _, _, memory_json_path, _ = get_room_files_paths(room_name)
    if not memory_json_path:
        return f"【エラー】ルーム'{room_name}'の記憶ファイルパスが見つかりません。"

    memory_data = load_memory_data_safe(memory_json_path)
    if "error" in memory_data:
        return f"【エラー】記憶ファイルの読み込みに失敗: {memory_data['message']}"

    try:
        for i, inst in enumerate(instructions):
            op = inst.get("operation", "").lower()
            path = inst.get("path")
            value = inst.get("value")

            if not op or path is None:
                return f"【エラー】指示 {i+1} に 'operation' または 'path' がありません。"

            keys = path.split('.')
            target_obj = memory_data

            for key in keys[:-1]:
                if key not in target_obj or not isinstance(target_obj.get(key), dict):
                    if op in ['set', 'append']:
                         target_obj[key] = {}
                    else:
                        return f"【エラー】指示 {i+1} のパス '{path}' の中間キー '{key}' が存在しません。"
                target_obj = target_obj[key]

            last_key = keys[-1]

            if op == 'set':
                if value is None: return f"【エラー】指示 {i+1} (set) に 'value' がありません。"
                target_obj[last_key] = value
            elif op == 'append':
                if value is None: return f"【エラー】指示 {i+1} (append) に 'value' がありません。"
                if last_key not in target_obj:
                    target_obj[last_key] = []
                if not isinstance(target_obj[last_key], list):
                    return f"【エラー】指示 {i+1} (append) のパス '{path}' はリストではありません。"
                target_obj[last_key].append(value)
            elif op == 'delete':
                if last_key in target_obj:
                    del target_obj[last_key]
                else:
                    pass
            else:
                return f"【エラー】指示 {i+1} の操作 '{op}' は無効です。"

        memory_data["last_updated"] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(memory_json_path, "w", encoding="utf-8") as f:
            json.dump(memory_data, f, indent=2, ensure_ascii=False)

        return f"成功: {len(instructions)}件の指示に基づき、主観的記憶(memory.json)を更新しました。"
    except Exception as e:
        traceback.print_exc()
        return f"【エラー】記憶の編集中に予期せぬエラーが発生しました: {e}"
