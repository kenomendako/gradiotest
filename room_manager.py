# room_manager.py

import os
import json
import traceback
import datetime
from typing import Optional
import constants
import utils

def ensure_room_files(room_name):
    if not room_name or not isinstance(room_name, str) or not room_name.strip(): return False
    if ".." in room_name or "/" in room_name or "\\" in room_name: return False
    try:
        if not os.path.exists(constants.ROOMS_DIR): os.makedirs(constants.ROOMS_DIR)
        elif not os.path.isdir(constants.ROOMS_DIR): return False

        base_path = os.path.join(constants.ROOMS_DIR, room_name)
        image_gen_dir = os.path.join(base_path, "generated_images")
        spaces_dir = os.path.join(base_path, "spaces")
        scenery_images_dir = os.path.join(spaces_dir, "images")
        cache_dir = os.path.join(base_path, "cache")

        for path in [base_path, image_gen_dir, spaces_dir, scenery_images_dir, cache_dir]:
            if not os.path.exists(path):
                os.makedirs(path)

        files_to_check = {
            os.path.join(base_path, "log.txt"): "",
            os.path.join(base_path, "SystemPrompt.txt"): "# このルームのユニークな設定...",
            os.path.join(base_path, constants.NOTEPAD_FILENAME): "",
            os.path.join(base_path, "current_location.txt"): "living_space"
        }
        for file_path, default_content in files_to_check.items():
            if not os.path.exists(file_path):
                with open(file_path, "w", encoding="utf-8") as f: f.write(default_content)

        scenery_cache_file = os.path.join(cache_dir, "scenery.json")
        image_prompt_cache_file = os.path.join(cache_dir, "image_prompts.json")

        if not os.path.exists(scenery_cache_file):
            with open(scenery_cache_file, "w", encoding="utf-8") as f:
                json.dump({}, f, indent=2, ensure_ascii=False)

        if not os.path.exists(image_prompt_cache_file):
            with open(image_prompt_cache_file, "w", encoding="utf-8") as f:
                json.dump({"prompts": {}}, f, indent=2, ensure_ascii=False)

        memory_json_file = os.path.join(base_path, constants.MEMORY_FILENAME)
        if not os.path.exists(memory_json_file):
            default_memory_data = {"last_updated": None, "user_profile": {}, "self_identity": {"name": room_name}}
            with open(memory_json_file, "w", encoding="utf-8") as f:
                json.dump(default_memory_data, f, indent=2, ensure_ascii=False)

        world_settings_file = os.path.join(spaces_dir, "world_settings.txt")
        if not os.path.exists(world_settings_file):
            default_world_data_txt = """## 共有リビング

### リビング
広々としたリビングルーム。大きな窓からは柔らかな光が差し込み、快適なソファが置かれている。
"""
            with open(world_settings_file, "w", encoding="utf-8") as f:
                f.write(default_world_data_txt)

        # 旧 character_config.json を room_config.json に改名（存在すれば）
        old_config_file = os.path.join(base_path, "character_config.json")
        new_config_file = os.path.join(base_path, "room_config.json")
        if os.path.exists(old_config_file) and not os.path.exists(new_config_file):
            os.rename(old_config_file, new_config_file)

        # room_config.json がなければ作成
        if not os.path.exists(new_config_file):
            # 後方互換性ロジック：フォルダ名を room_name に設定
            default_room_config = {
                "version": 1,
                "room_name": room_name,
                "user_display_name": "ユーザー",
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "description": "自動生成された設定ファイルです"
            }
            with open(new_config_file, "w", encoding="utf-8") as f:
                json.dump(default_room_config, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"ルーム '{room_name}' ファイル作成/確認エラー: {e}"); traceback.print_exc()
        return False

def get_room_list():
    if not os.path.exists(constants.ROOMS_DIR):
        try: os.makedirs(constants.ROOMS_DIR)
        except Exception as e: print(f"エラー: '{constants.ROOMS_DIR}' 作成失敗: {e}"); return []

    valid_rooms = []
    try:
        if not os.path.isdir(constants.ROOMS_DIR): return []

        # room_config.json が存在するフォルダのみを有効なルームとみなす
        for folder_name in os.listdir(constants.ROOMS_DIR):
            room_path = os.path.join(constants.ROOMS_DIR, folder_name)
            if os.path.isdir(room_path):
                # まず、基本的なファイル構造を保証する
                if ensure_room_files(folder_name):
                    # その上で、room_config.jsonの存在を確認する
                    if os.path.exists(os.path.join(room_path, "room_config.json")):
                        valid_rooms.append(folder_name)

        # もし有効なルームが一つもなければ、Defaultルームを作成試行
        if not valid_rooms:
            if ensure_room_files("Default"):
                # Defaultルームが作成されたはずなので、再度リストに追加
                default_room_path = os.path.join(constants.ROOMS_DIR, "Default")
                if os.path.exists(os.path.join(default_room_path, "room_config.json")):
                    return ["Default"]
            return [] # Defaultルームの作成に失敗した場合は空を返す

        return sorted(valid_rooms)
    except Exception as e:
        print(f"ルームリスト取得エラー: {e}"); traceback.print_exc()
        return []


def get_room_files_paths(room_name):
    if not room_name or not ensure_room_files(room_name): return None, None, None, None, None
    base_path = os.path.join(constants.ROOMS_DIR, room_name)
    log_file = os.path.join(base_path, "log.txt")
    system_prompt_file = os.path.join(base_path, "SystemPrompt.txt")
    profile_image_path = os.path.join(base_path, constants.PROFILE_IMAGE_FILENAME)
    memory_json_path = os.path.join(base_path, constants.MEMORY_FILENAME)
    notepad_path = os.path.join(base_path, constants.NOTEPAD_FILENAME)
    if not os.path.exists(profile_image_path): profile_image_path = None
    return log_file, system_prompt_file, profile_image_path, memory_json_path, notepad_path

def get_world_settings_path(room_name: str):
    if not room_name or not ensure_room_files(room_name): return None
    return os.path.join(constants.ROOMS_DIR, room_name, "spaces", "world_settings.txt")

def get_all_personas_in_log(main_room_name: str, api_history_limit_key: str) -> list[str]:
    """
    指定されたルームのログを解析し、指定された履歴範囲内に登場するすべての
    ペルソナ名（ユーザー含む）のユニークなリストを返す。
    """
    if not main_room_name:
        return []

    log_file_path, _, _, _, _ = get_room_files_paths(main_room_name)
    if not log_file_path or not os.path.exists(log_file_path):
        # ログファイルがない場合、ルーム名自体をペルソナと見なす
        # これは、room_config.json の main_persona_name を参照する将来の実装への布石
        return [main_room_name]

    # utils.load_chat_log を呼び出す
    full_log = utils.load_chat_log(log_file_path, main_room_name)

    # 履歴制限を適用
    limit = constants.API_HISTORY_LIMIT_OPTIONS.get(api_history_limit_key)
    if limit is not None and limit.isdigit():
        display_turns = int(limit)
        limited_log = full_log[-(display_turns * 2):]
    else: # "全ログ" or other cases
        limited_log = full_log

    # 登場ペルソナを収集
    personas = set()
    for message in limited_log:
        responder = message.get("responder")
        if responder:
            personas.add(responder)

    # メインのペルソナがリストに含まれていることを保証する
    # ここも将来的には room_config.json から取得する
    personas.add(main_room_name)

    # "ユーザー"はペルソナではないので除外
    return sorted([p for p in list(personas) if p != "ユーザー"])
