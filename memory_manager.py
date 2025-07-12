# -*- coding: utf-8 -*-
import json
import os
import traceback
import datetime
from character_manager import get_character_files_paths
from config_manager import MEMORY_FILENAME

def save_memory_data(character_name: str, json_string_data: str) -> dict:
    """
    記憶データをファイルに保存する。
    成功した場合は、更新後の記憶データを辞書として返す。
    失敗した場合は、例外を発生させる。
    """
    if not character_name:
        raise ValueError("キャラクター名が指定されていません。")

    # ★★★ 5つの値を受け取るように修正 ★★★
    _, _, _, memory_json_path, _ = get_character_files_paths(character_name)
    if not memory_json_path:
        raise FileNotFoundError(f"キャラクター '{character_name}' の記憶ファイルパスが見つかりません。")

    try:
        memory_data_to_save = json.loads(json_string_data)
        if not isinstance(memory_data_to_save, dict):
            raise TypeError("記憶データが不正な形式です（JSONオブジェクトではありません）。")

        now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        memory_data_to_save["last_updated"] = now_str

        with open(memory_json_path, "w", encoding="utf-8") as f:
            json.dump(memory_data_to_save, f, indent=2, ensure_ascii=False)

        return memory_data_to_save

    except json.JSONDecodeError as e:
        raise ValueError(f"記憶データのJSON形式が正しくありません: {e}") from e
    except Exception as e:
        print(f"記憶の保存中に予期せぬエラーが発生しました: {e}")
        traceback.print_exc()
        raise IOError(f"記憶ファイルの書き込み中にエラーが発生しました: {e}") from e


def load_memory_data_safe(memory_json_path: str) -> dict:
    if memory_json_path and os.path.exists(memory_json_path):
        try:
            with open(memory_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {"error": "Invalid Format", "message": "記憶ファイルの形式がJSONオブジェクトではありません。"}
        except json.JSONDecodeError as e:
            return {"error": "JSON Decode Error", "message": f"記憶ファイルのJSON形式が正しくありません: {e}"}
        except Exception as e:
            return {"error": "Read Error", "message": f"記憶ファイルの読み込み中にエラーが発生しました: {e}"}
    return {}