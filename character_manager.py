# character_manager.py (最終確定版)

import os
import json
import traceback
import datetime
from typing import Optional, List, Tuple, Dict
import constants
import re
from utils import parse_world_markdown

def ensure_character_files(character_name):
    if not character_name or not isinstance(character_name, str) or not character_name.strip(): return False
    if ".." in character_name or "/" in character_name or "\\" in character_name: return False
    try:
        base_path = os.path.join(constants.CHARACTERS_DIR, character_name)
        image_gen_dir = os.path.join(base_path, "generated_images")
        spaces_dir = os.path.join(base_path, "spaces")
        scenery_images_dir = os.path.join(spaces_dir, "images")
        for path in [base_path, image_gen_dir, spaces_dir, scenery_images_dir]:
            if not os.path.exists(path): os.makedirs(path)

        files_to_check = {
            os.path.join(base_path, "log.txt"): "",
            os.path.join(base_path, "SystemPrompt.txt"): "# このキャラクターのユニークな設定...",
            os.path.join(base_path, constants.NOTEPAD_FILENAME): "",
            os.path.join(base_path, "current_location.txt"): "living_space"
        }
        for file_path, default_content in files_to_check.items():
            if not os.path.exists(file_path):
                with open(file_path, "w", encoding="utf-8") as f: f.write(default_content)

        scenery_cache_file = os.path.join(base_path, "last_scenery.json")
        if not os.path.exists(scenery_cache_file):
            with open(scenery_cache_file, "w", encoding="utf-8") as f: json.dump({}, f)

        memory_json_file = os.path.join(base_path, constants.MEMORY_FILENAME)
        if not os.path.exists(memory_json_file):
            default_memory = {"last_updated": None, "user_profile": {}, "self_identity": {"name": character_name}}
            with open(memory_json_file, "w", encoding="utf-8") as f: json.dump(default_memory, f, indent=2, ensure_ascii=False)

        world_settings_file = os.path.join(spaces_dir, "world_settings.md")
        if not os.path.exists(world_settings_file):
            default_world_md = "## 共有リビング\n- name: 共有リビング\n- description: 広々としたリビングルーム。"
            with open(world_settings_file, "w", encoding="utf-8") as f: f.write(default_world_md.strip())

        config_file = os.path.join(base_path, "character_config.json")
        if not os.path.exists(config_file):
            default_char_config = {"override_settings": {}}
            with open(config_file, "w", encoding="utf-8") as f: json.dump(default_char_config, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"キャラクター '{character_name}' ファイル作成/確認エラー: {e}")
        return False

def get_character_list():
    if not os.path.exists(constants.CHARACTERS_DIR):
        try: os.makedirs(constants.CHARACTERS_DIR)
        except Exception: return []
    valid_characters = [d for d in os.listdir(constants.CHARACTERS_DIR) if os.path.isdir(os.path.join(constants.CHARACTERS_DIR, d)) and ensure_character_files(d)]
    if not valid_characters:
        if ensure_character_files("Default"): return ["Default"]
        else: return []
    return sorted(valid_characters)

def get_character_files_paths(character_name):
    if not character_name or not ensure_character_files(character_name): return None, None, None, None, None
    base_path = os.path.join(constants.CHARACTERS_DIR, character_name)
    log_file = os.path.join(base_path, "log.txt")
    system_prompt_file = os.path.join(base_path, "SystemPrompt.txt")
    profile_image_path = os.path.join(base_path, constants.PROFILE_IMAGE_FILENAME)
    memory_json_path = os.path.join(base_path, constants.MEMORY_FILENAME)
    notepad_path = os.path.join(base_path, constants.NOTEPAD_FILENAME)
    if not os.path.exists(profile_image_path): profile_image_path = None
    return log_file, system_prompt_file, profile_image_path, memory_json_path, notepad_path

def get_world_settings_path(character_name: str):
    if not character_name or not ensure_character_files(character_name): return None
    return os.path.join(constants.CHARACTERS_DIR, character_name, "spaces", "world_settings.md")

def find_space_data_by_id_recursive(data: dict, target_id: str) -> Optional[dict]:
    if not isinstance(data, dict): return None
    if target_id in data: return data[target_id]
    for key, value in data.items():
        if isinstance(value, dict):
            found = find_space_data_by_id_recursive(value, target_id)
            if found is not None: return found
    return None

def get_location_list(character_name: str) -> List[Tuple[str, str]]:
    if not character_name: return []
    world_settings_path = get_world_settings_path(character_name)
    world_data = parse_world_markdown(world_settings_path)
    if not world_data: return []
    location_list = []
    for area_id, area_data in world_data.items():
        if isinstance(area_data, dict):
            if 'name' in area_data: location_list.append((area_data['name'], area_id))
            for room_id, room_data in area_data.items():
                if isinstance(room_data, dict) and 'name' in room_data:
                    location_list.append((room_data['name'], room_id))
    return sorted(list(set(location_list)), key=lambda x: x[0])

def load_chat_log(character_name: str) -> List[Dict[str, str]]:
    log_file, _, _, _, _ = get_character_files_paths(character_name)
    if not log_file or not os.path.exists(log_file): return []
    messages = []
    try:
        with open(log_file, "r", encoding="utf-8") as f: content = f.read()
        ai_header = f"## {character_name}:"
        parts = re.split(r'^(## .*?:)$', content, flags=re.MULTILINE)
        header = None
        for part in parts:
            part = part.strip()
            if not part: continue
            if part.startswith("## ") and part.endswith(":"): header = part
            elif header:
                role = 'model' if header == ai_header else 'user'
                messages.append({"role": role, "content": part})
                header = None
    except Exception as e:
        print(f"エラー: ログファイル読込エラー: {e}")
    return messages

def _get_user_header_from_log(character_name: str) -> str:
    log_file, _, _, _, _ = get_character_files_paths(character_name)
    default_user_header = "## ユーザー:"
    if not log_file or not os.path.exists(log_file): return default_user_header
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            for line in reversed(list(f)):
                stripped = line.strip()
                if stripped.startswith("## ") and stripped.endswith(":") and not stripped.startswith(f"## {character_name}:") and not stripped.startswith("## システム("):
                    return stripped
    except Exception: pass
    return default_user_header

def delete_message_from_log(character_name: str, message_to_delete: Dict[str, str]) -> bool:
    log_file, _, _, _, _ = get_character_files_paths(character_name)
    if not log_file or not os.path.exists(log_file) or not message_to_delete: return False
    try:
        all_messages = load_chat_log(character_name)
        if message_to_delete not in all_messages: return False
        all_messages.remove(message_to_delete)
        user_header = _get_user_header_from_log(character_name)
        ai_header = f"## {character_name}:"
        new_content = "\n\n".join([f"{ai_header if msg['role'] == 'model' else user_header}\n{msg['content'].strip()}" for msg in all_messages])
        with open(log_file, "w", encoding="utf-8") as f: f.write(new_content)
        return True
    except Exception: return False

def get_current_location(character_name: str) -> Optional[str]:
    try:
        loc_file = os.path.join(constants.CHARACTERS_DIR, character_name, "current_location.txt")
        if os.path.exists(loc_file):
            with open(loc_file, 'r', encoding='utf-8') as f: return f.read().strip()
    except Exception: pass
    return "living_space"

def load_scenery_cache(character_name: str) -> dict:
    if not character_name: return {}
    cache_path = os.path.join(constants.CHARACTERS_DIR, character_name, "last_scenery.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                content = f.read()
                return json.loads(content) if content.strip() else {}
        except (json.JSONDecodeError, IOError): pass
    return {}

def save_scenery_cache(character_name: str, location_name: str, scenery_text: str):
    if not character_name: return
    cache_path = os.path.join(constants.CHARACTERS_DIR, character_name, "last_scenery.json")
    try:
        data = {"location_name": location_name, "scenery_text": scenery_text, "timestamp": datetime.datetime.now().isoformat()}
        with open(cache_path, "w", encoding="utf-8") as f: json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"!! エラー: 情景キャッシュの保存に失敗しました: {e}")

def get_season(month: int) -> str:
    if month in [3, 4, 5]: return "spring"
    if month in [6, 7, 8]: return "summer"
    if month in [9, 10, 11]: return "autumn"
    return "winter"

def get_time_of_day(hour: int) -> str:
    if 5 <= hour < 10: return "morning"
    if 10 <= hour < 17: return "daytime"
    if 17 <= hour < 21: return "evening"
    return "night"

def find_scenery_image(character_name: str) -> Optional[str]:
    location_id = get_current_location(character_name)
    if not character_name or not location_id: return None
    image_dir = os.path.join(constants.CHARACTERS_DIR, character_name, "spaces", "images")
    if not os.path.isdir(image_dir): return None
    now = datetime.datetime.now()
    season, time_of_day = get_season(now.month), get_time_of_day(now.hour)
    filenames = [f"{location_id}_{season}_{time_of_day}.png", f"{location_id}_{season}.png", f"{location_id}.png"]
    for filename in filenames:
        filepath = os.path.join(image_dir, filename)
        if os.path.exists(filepath): return filepath
    return None
