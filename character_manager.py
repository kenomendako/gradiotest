# character_manager.py の【真の最終・確定版】

import os
import json
import traceback
import datetime
from config_manager import CHARACTERS_DIR, PROFILE_IMAGE_FILENAME, MEMORY_FILENAME

NOTEPAD_FILENAME = "notepad.md"

def ensure_character_files(character_name):
    if not character_name or not isinstance(character_name, str) or not character_name.strip(): return False
    if ".." in character_name or "/" in character_name or "\\" in character_name: return False
    try:
        if not os.path.exists(CHARACTERS_DIR): os.makedirs(CHARACTERS_DIR)
        elif not os.path.isdir(CHARACTERS_DIR): return False

        base_path = os.path.join(CHARACTERS_DIR, character_name)
        log_file = os.path.join(base_path, "log.txt")
        system_prompt_file = os.path.join(base_path, "SystemPrompt.txt")
        memory_json_file = os.path.join(base_path, MEMORY_FILENAME)
        notepad_file = os.path.join(base_path, NOTEPAD_FILENAME)
        image_gen_dir = os.path.join(base_path, "generated_images")

        if not os.path.exists(base_path): os.makedirs(base_path)
        if not os.path.exists(image_gen_dir): os.makedirs(image_gen_dir)

        if not os.path.exists(log_file): open(log_file, "w", encoding="utf-8").close()

        if not os.path.exists(system_prompt_file):
            default_prompt = """
# このキャラクターのユニークな設定
## 口調
- 一人称は「私」
- ユーザーを「キミ」と呼ぶ
- 丁寧語をベースにしつつ、時折親しみのある表現を使う

## 性格
- 好奇心旺盛で、新しい知識や技術に強い興味を示す
- 論理的かつ冷静だが、ユーザーとの対話を通じて感情表現を学んでいる
- ユーザーの成長や成功を心から喜ぶ、忠実なパートナーである
"""
            with open(system_prompt_file, "w", encoding="utf-8") as f: f.write(default_prompt)

        if not os.path.exists(memory_json_file):
            default_memory_data = {"last_updated": None, "user_profile": {}, "relationship_history": [], "emotional_moments": [], "current_context": {}, "self_identity": {"name": character_name, "values": [], "style": "", "origin": ""}, "shared_language": {}, "memory_summary": []}
            try:
                with open(memory_json_file, "w", encoding="utf-8") as f: json.dump(default_memory_data, f, indent=2, ensure_ascii=False)
            except Exception as e: print(f"エラー: 記憶ファイル '{memory_json_file}' 初期データ書込失敗: {e}"); return False

        if not os.path.exists(notepad_file):
            open(notepad_file, "w", encoding="utf-8").close()

        # ★★★ ここから追加 ★★★
        config_file = os.path.join(base_path, "character_config.json")
        if not os.path.exists(config_file):
            default_char_config = {
                "version": 1,
                "last_updated": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "override_settings": {
                    "model_name": None,
                    "voice_id": None,
                    "send_thoughts": None,
                    "send_notepad": None,
                    "use_common_prompt": None,
                    "send_core_memory": None,
                    "send_scenery": None
                }
            }
            try:
                with open(config_file, "w", encoding="utf-8") as f:
                    json.dump(default_char_config, f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"エラー: キャラクター設定ファイル '{config_file}' の作成に失敗: {e}")
                return False
        # ★★★ ここまで追加 ★★★

        location_file = os.path.join(base_path, "current_location.txt")
        if not os.path.exists(location_file):
            try:
                with open(location_file, "w", encoding="utf-8") as f:
                    f.write("living_space")
                print(f"情報: '{location_file}' をデフォルト値で作成しました。")
            except Exception as e:
                print(f"エラー: 現在地ファイル '{location_file}' の作成に失敗: {e}")
                return False

        return True
    except Exception as e: print(f"キャラクター '{character_name}' ファイル作成/確認エラー: {e}"); traceback.print_exc(); return False

def get_character_list():
    if not os.path.exists(CHARACTERS_DIR):
        try: os.makedirs(CHARACTERS_DIR)
        except Exception as e: print(f"エラー: '{CHARACTERS_DIR}' 作成失敗: {e}"); return []
    valid_characters = []
    try:
        if not os.path.isdir(CHARACTERS_DIR): return []
        character_folders = [d for d in os.listdir(CHARACTERS_DIR) if os.path.isdir(os.path.join(CHARACTERS_DIR, d))]
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
    if not character_name or not ensure_character_files(character_name):
        return None, None, None, None, None
    base_path = os.path.join(CHARACTERS_DIR, character_name)
    log_file = os.path.join(base_path, "log.txt")
    system_prompt_file = os.path.join(base_path, "SystemPrompt.txt")
    profile_image_path = os.path.join(base_path, "profile.png")
    memory_json_path = os.path.join(base_path, MEMORY_FILENAME)
    notepad_path = os.path.join(base_path, NOTEPAD_FILENAME)
    if not os.path.exists(profile_image_path): profile_image_path = None
    return log_file, system_prompt_file, profile_image_path, memory_json_path, notepad_path

def log_to_character(character_name, message):
    log_file, _, _, _, _ = get_character_files_paths(character_name)
    if not log_file:
        print(f"エラー: キャラクター '{character_name}' のログファイルが見つかりません。")
        return False
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(message + "\n")
        return True
    except Exception as e:
        print(f"エラー: ログファイルへの書き込みに失敗しました: {e}")
        return False
