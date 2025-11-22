# signature_manager.py

import os
import json
import constants
from typing import Optional

def _get_signature_file_path(room_name: str) -> str:
    """署名ファイルのパスを取得 (characters/{room}/private/thought_signatures.json)"""
    return os.path.join(constants.ROOMS_DIR, room_name, "private", "thought_signatures.json")

def save_thought_signature(room_name: str, signature: str):
    """最新の思考署名をJSONファイルに保存する"""
    if not room_name or not signature:
        return

    file_path = _get_signature_file_path(room_name)
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    data = {
        "last_signature": signature,
        "updated_at": str(os.path.getmtime(file_path)) if os.path.exists(file_path) else ""
    }

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        # print(f"  - [SignatureManager] 署名を保存しました: {room_name}")
    except Exception as e:
        print(f"  - [SignatureManager] 保存エラー: {e}")

def get_thought_signature(room_name: str) -> Optional[str]:
    """JSONファイルから最新の思考署名を読み込む"""
    file_path = _get_signature_file_path(room_name)
    if not os.path.exists(file_path):
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("last_signature")
    except Exception:
        return None