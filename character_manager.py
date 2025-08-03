# character_manager.py (リファクタリング版)

import os
import json
import traceback
import datetime
import constants  # config_managerの代わりにconstantsをインポート

def ensure_character_files(character_name):
    if not character_name or not isinstance(character_name, str) or not character_name.strip(): return False
    if ".." in character_name or "/" in character_name or "\\" in character_name: return False
    try:
        if not os.path.exists(constants.CHARACTERS_DIR): os.makedirs(constants.CHARACTERS_DIR)
        elif not os.path.isdir(constants.CHARACTERS_DIR): return False

        base_path = os.path.join(constants.CHARACTERS_DIR, character_name)
        image_gen_dir = os.path.join(base_path, "generated_images")
        spaces_dir = os.path.join(base_path, "spaces")

        for path in [base_path, image_gen_dir, spaces_dir]:
            if not os.path.exists(path): os.makedirs(path)

        files_to_check = {
            os.path.join(base_path, "log.txt"): "",
            os.path.join(base_path, "SystemPrompt.txt"): "# このキャラクターのユニークな設定\n## 口調\n- 一人称は「私」...",
            os.path.join(base_path, constants.NOTEPAD_FILENAME): "",
            os.path.join(base_path, "current_location.txt"): "living_space"
        }
        for file_path, default_content in files_to_check.items():
            if not os.path.exists(file_path):
                with open(file_path, "w", encoding="utf-8") as f: f.write(default_content)

        memory_json_file = os.path.join(base_path, constants.MEMORY_FILENAME)
        if not os.path.exists(memory_json_file):
            default_memory_data = {"last_updated": None, "user_profile": {}, "self_identity": {"name": character_name}}
            with open(memory_json_file, "w", encoding="utf-8") as f:
                json.dump(default_memory_data, f, indent=2, ensure_ascii=False)

        world_settings_file = os.path.join(spaces_dir, "world_settings.json")
        if not os.path.exists(world_settings_file):
            default_world_data = {
                "living_space": {
                    "name": "共有リビング",
                    "description": "広々としたリビングルーム。大きな窓からは柔らかな光が差し込み、快適なソファが置かれている。",
                    "objects": ["ソファ", "ローテーブル", "観葉植物"]
                }
            }
            with open(world_settings_file, "w", encoding="utf-8") as f:
                json.dump(default_world_data, f, indent=2, ensure_ascii=False)

        config_file = os.path.join(base_path, "character_config.json")
        if not os.path.exists(config_file):
            default_char_config = {
                "version": 1, "last_updated": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "override_settings": {
                    "model_name": None, "voice_id": "vindemiatrix", "voice_style_prompt": "",
                    "add_timestamp": False, "send_thoughts": None, "send_notepad": None,
                    "use_common_prompt": None, "send_core_memory": None, "send_scenery": None
                }
            }
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(default_char_config, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"キャラクター '{character_name}' ファイル作成/確認エラー: {e}"); traceback.print_exc()
        return False

def get_character_list():
    if not os.path.exists(constants.CHARACTERS_DIR):
        try: os.makedirs(constants.CHARACTERS_DIR)
        except Exception as e: print(f"エラー: '{constants.CHARACTERS_DIR}' 作成失敗: {e}"); return []
    valid_characters = []
    try:
        if not os.path.isdir(constants.CHARACTERS_DIR): return []
        character_folders = [d for d in os.listdir(constants.CHARACTERS_DIR) if os.path.isdir(os.path.join(constants.CHARACTERS_DIR, d))]
        if not character_folders:
            if ensure_character_files("Default"): return ["Default"]
            else: return []
        for char in character_folders:
             if ensure_character_files(char): valid_characters.append(char)
        if not valid_characters:
             if ensure_character_files("Default"): return ["Default"]
             else: return []
        return sorted(valid_characters)
    except Exception as e: print(f"キャラリスト取得エラー: {e}"); traceback.print_exc(); return []

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
    return os.path.join(constants.CHARACTERS_DIR, character_name, "spaces", "world_settings.json")
