# character_manager.py (循環参照解決版)

# 1. ファイル先頭のインポートを修正
import os
import json
import traceback
import datetime
from typing import Optional, List, Tuple, Dict
import constants
# ▼▼▼ 以下のインポートを追加 ▼▼▼
import re
from utils import parse_world_markdown # utilsは下位モジュールなのでインポートOK

def ensure_character_files(character_name):
    if not character_name or not isinstance(character_name, str) or not character_name.strip(): return False
    if ".." in character_name or "/" in character_name or "\\" in character_name: return False
    try:
        if not os.path.exists(constants.CHARACTERS_DIR): os.makedirs(constants.CHARACTERS_DIR)
        elif not os.path.isdir(constants.CHARACTERS_DIR): return False

        base_path = os.path.join(constants.CHARACTERS_DIR, character_name)
        image_gen_dir = os.path.join(base_path, "generated_images")

        # ▼▼▼ spaces_dir と scenery_images_dir の定義を追加・修正 ▼▼▼
        spaces_dir = os.path.join(base_path, "spaces")
        scenery_images_dir = os.path.join(spaces_dir, "images") # 新しいディレクトリパス

        # 修正: 新しいディレクトリも作成対象に含める
        for path in [base_path, image_gen_dir, spaces_dir, scenery_images_dir]:
            if not os.path.exists(path):
                os.makedirs(path)

        files_to_check = {
            os.path.join(base_path, "log.txt"): "",
            os.path.join(base_path, "SystemPrompt.txt"): "# このキャラクターのユニークな設定\n## 口調\n- 一人称は「私」...",
            os.path.join(base_path, constants.NOTEPAD_FILENAME): "",
            os.path.join(base_path, "current_location.txt"): "living_space"
        }
        for file_path, default_content in files_to_check.items():
            if not os.path.exists(file_path):
                with open(file_path, "w", encoding="utf-8") as f: f.write(default_content)

        # ▼▼▼ ここからが追加箇所 ▼▼▼
        # last_scenery.jsonの存在を確認し、なければ空のJSONオブジェクトで作成
        scenery_cache_file = os.path.join(base_path, "last_scenery.json")
        if not os.path.exists(scenery_cache_file):
            with open(scenery_cache_file, "w", encoding="utf-8") as f:
                json.dump({}, f, indent=2, ensure_ascii=False)
        # ▲▲▲ 追加箇所ここまで ▲▲▲

        memory_json_file = os.path.join(base_path, constants.MEMORY_FILENAME)
        if not os.path.exists(memory_json_file):
            default_memory_data = {"last_updated": None, "user_profile": {}, "self_identity": {"name": character_name}}
            with open(memory_json_file, "w", encoding="utf-8") as f:
                json.dump(default_memory_data, f, indent=2, ensure_ascii=False)

        # world_settings.json の作成ロジックを world_settings.md の作成ロジックに置き換える
        world_settings_file = os.path.join(spaces_dir, "world_settings.md") # 新しいファイル名
        if not os.path.exists(world_settings_file):
            # ▼▼▼ デフォルトのデータをMarkdown形式で書き込む ▼▼▼
            default_world_data_md = """
## 共有リビング
- name: 共有リビング
- description: 広々としたリビングルーム。大きな窓からは柔らかな光が差し込み、快適なソファが置かれている。
- objects:
    - ソファ
    - ローテーブル
    - 観葉植物
"""
            with open(world_settings_file, "w", encoding="utf-8") as f:
                f.write(default_world_data_md.strip())
            # ▲▲▲ 修正ここまで ▲▲▲

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
    # ▼▼▼ .json から .md に変更 ▼▼▼
    return os.path.join(constants.CHARACTERS_DIR, character_name, "spaces", "world_settings.md")

def find_space_data_by_id_recursive(data: dict, target_id: str) -> Optional[dict]:
    """
    ネストされた辞書の中から、指定されたID（キー）を持つ空間データを再帰的に探し出す。
    トップレベルのキーも検索対象とするように修正。
    """
    if not isinstance(data, dict):
        return None

    # ▼▼▼ 修正の核心 ▼▼▼
    # 1. まず、渡されたデータ全体の中に、探しているIDがトップレベルのキーとして存在するかチェック
    if target_id in data:
        return data[target_id]

    # 2. トップレベルになければ、各値を辿って再帰的に探索
    for key, value in data.items():
        if isinstance(value, dict):
            # 再帰呼び出しの結果を found に格納
            found = find_space_data_by_id_recursive(value, target_id)
            # もし見つかったら、その結果をすぐに返す
            if found is not None:
                return found

    # すべて探しても見つからなかった場合
    return None
    # ▲▲▲ 修正ここまで ▲▲▲

# ▼▼▼ ここから、utils.pyから移動した関数群を追加 ▼▼▼

def load_chat_log(character_name: str) -> List[Dict[str, str]]:
    log_file, _, _, _, _ = get_character_files_paths(character_name)
    messages: List[Dict[str, str]] = []
    if not log_file or not os.path.exists(log_file):
        return messages

    ai_header = f"## {character_name}:"

    try:
        with open(log_file, "r", encoding="utf-8") as f: content = f.read()
    except Exception as e:
        print(f"エラー: ログファイル '{log_file}' 読込エラー: {e}")
        return messages

    log_parts = re.split(r'^(## .*?:)$', content, flags=re.MULTILINE)
    header = None
    for part in log_parts:
        part = part.strip()
        if not part: continue
        if part.startswith("## ") and part.endswith(":"):
            header = part
        elif header:
            role = 'model' if header == ai_header else 'user'
            messages.append({"role": role, "content": part})
            header = None
    return messages

def _get_user_header_from_log(character_name: str) -> str:
    log_file, _, _, _, _ = get_character_files_paths(character_name)
    default_user_header = "## ユーザー:"
    if not log_file or not os.path.exists(log_file):
        return default_user_header

    last_identified_user_header = default_user_header
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                stripped_line = line.strip()
                if stripped_line.startswith("## ") and stripped_line.endswith(":"):
                    if not stripped_line.startswith(f"## {character_name}:") and not stripped_line.startswith("## システム("):
                        last_identified_user_header = stripped_line
        return last_identified_user_header
    except Exception:
        return default_user_header

def delete_message_from_log(character_name: str, message_to_delete: Dict[str, str]) -> bool:
    log_file, _, _, _, _ = get_character_files_paths(character_name)
    if not log_file or not os.path.exists(log_file) or not message_to_delete:
        return False
    try:
        all_messages = load_chat_log(character_name)
        try:
            all_messages.remove(message_to_delete)
        except ValueError:
            return False

        log_content_parts = []
        user_header = _get_user_header_from_log(character_name)
        ai_header = f"## {character_name}:"
        for msg in all_messages:
            header = ai_header if msg['role'] == 'model' else user_header
            log_content_parts.append(f"{header}\n{msg['content'].strip()}")

        with open(log_file, "w", encoding="utf-8") as f: f.write("\n\n".join(log_content_parts))
        if log_content_parts:
            with open(log_file, "a", encoding="utf-8") as f: f.write("\n\n")
        return True
    except Exception:
        return False

def get_current_location(character_name: str) -> Optional[str]:
    try:
        base_path = os.path.join(constants.CHARACTERS_DIR, character_name)
        location_file_path = os.path.join(base_path, "current_location.txt")
        if os.path.exists(location_file_path):
            with open(location_file_path, 'r', encoding='utf-8') as f:
                return f.read().strip()
    except Exception:
        return None
    return "living_space" # デフォルト値を返すように変更

def load_scenery_cache(character_name: str) -> dict:
    if not character_name: return {}
    cache_path = os.path.join(constants.CHARACTERS_DIR, character_name, "last_scenery.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                content = f.read()
                if not content.strip(): return {}
                data = json.loads(content)
                return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, IOError):
            return {}
    return {}

def save_scenery_cache(character_name: str, location_name: str, scenery_text: str):
    if not character_name: return
    cache_path = os.path.join(constants.CHARACTERS_DIR, character_name, "last_scenery.json")
    try:
        data_to_save = { "location_name": location_name, "scenery_text": scenery_text, "timestamp": datetime.datetime.now().isoformat() }
        with open(cache_path, "w", encoding="utf-8") as f: json.dump(data_to_save, f, indent=2, ensure_ascii=False)
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
    season = get_season(now.month)
    time_of_day = get_time_of_day(now.hour)
    potential_filenames = [ f"{location_id}_{season}_{time_of_day}.png", f"{location_id}_{season}.png", f"{location_id}.png" ]
    for filename in potential_filenames:
        filepath = os.path.join(image_dir, filename)
        if os.path.exists(filepath):
            return filepath
    return None

def get_location_list(character_name: str) -> List[Tuple[str, str]]:
    """
    UIの移動先ドロップダウン用のリストを生成する。
    エリアと部屋の両方をリストに含める。
    """
    if not character_name: return []

    world_settings_path = get_world_settings_path(character_name)
    world_data = parse_world_markdown(world_settings_path)

    if not world_data: return []

    location_list = []
    # 2階層のループで、エリアと部屋をすべて探索する
    for area_id, area_data in world_data.items():
        if not isinstance(area_data, dict): continue

        # まず、エリア自体に 'name' があれば、それをリストに追加
        if 'name' in area_data:
            location_list.append((area_data['name'], area_id))

        # 次に、エリア内の各要素をチェック
        for room_id, room_data in area_data.items():
            # 値が辞書で、かつ 'name' キーを持つなら、それは部屋だと判断
            if isinstance(room_data, dict) and 'name' in room_data:
                location_list.append((room_data['name'], room_id))

    # 重複を除外し、名前でソートして返す
    unique_locations = sorted(list(set(location_list)), key=lambda x: x[0])
    return unique_locations
