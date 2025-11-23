# signature_manager.py

import os
import json
import constants
from typing import Optional, Dict, Any

def _get_signature_file_path(room_name: str) -> str:
    """署名ファイルのパスを取得 (characters/{room}/private/thought_signatures.json)"""
    return os.path.join(constants.ROOMS_DIR, room_name, "private", "thought_signatures.json")

def save_turn_context(room_name: str, signature: str, tool_calls: list):
    """
    最新のターンコンテキスト（思考署名とツール呼び出し情報）をJSONファイルに保存する。
    Thinkingモデルの整合性を保つために必須。
    """
    if not room_name:
        return

    file_path = _get_signature_file_path(room_name)
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    data = {
        "last_signature": signature,
        "last_tool_calls": tool_calls, # ツール呼び出しのリスト（辞書形式）を保存
        "updated_at": str(os.path.getmtime(file_path)) if os.path.exists(file_path) else ""
    }

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        # print(f"  - [SignatureManager] ターンコンテキストを保存しました: {room_name}")
    except Exception as e:
        print(f"  - [SignatureManager] 保存エラー: {e}")

def get_turn_context(room_name: str) -> Dict[str, Any]:
    """JSONファイルから最新のターンコンテキストを読み込む"""
    file_path = _get_signature_file_path(room_name)
    if not os.path.exists(file_path):
        return {}

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data
    except Exception:
        return {}

# 後方互換性のために残すが、基本は get_turn_context を使う推奨
def get_thought_signature(room_name: str) -> Optional[str]:
    data = get_turn_context(room_name)
    return data.get("last_signature")

def save_thought_signature(room_name: str, signature: str):
    # ツールコールなしで署名だけ保存する場合（稀なケース）
    save_turn_context(room_name, signature, [])