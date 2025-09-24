# room_manager.py

import os
import json
import re
import shutil
import traceback
import datetime
from typing import Optional, List, Tuple
import constants
import utils

def generate_safe_folder_name(room_name: str) -> str:
    """
    ユーザーが入力したルーム名から、安全でユニークなフォルダ名を生成する。
    仕様:
    - 空白をアンダースコア `_` に置換
    - OSのファイル名として不正な文字 (`\\/:*?\"<>|`) を除去
    - 重複をチェックし、末尾に `_2`, `_3` ... と連番を付与
    """
    # 1. 空白をアンダースコアに置換
    safe_name = room_name.replace(" ", "_")

    # 2. OSのファイル名として不正な文字を除去
    safe_name = re.sub(r'[\\/:*?"<>|]', '', safe_name)

    # 3. 重複をチェックし、連番を付与
    base_path = constants.ROOMS_DIR
    if not os.path.exists(base_path):
        os.makedirs(base_path)

    final_name = safe_name
    counter = 2
    while os.path.exists(os.path.join(base_path, final_name)):
        final_name = f"{safe_name}_{counter}"
        counter += 1

    return final_name

def ensure_room_files(room_name: str) -> bool:
    """
    指定されたルーム名のディレクトリと、その中に必要なファイル群を生成・保証する。
    """
    if not room_name or not isinstance(room_name, str) or not room_name.strip(): return False
    if ".." in room_name or "/" in room_name or "\\" in room_name: return False
    try:
        base_path = os.path.join(constants.ROOMS_DIR, room_name)
        spaces_dir = os.path.join(base_path, "spaces")
        cache_dir = os.path.join(base_path, "cache")

        # 必須ディレクトリのリスト
        dirs_to_create = [
            base_path,
            os.path.join(base_path, "generated_images"),
            spaces_dir,
            os.path.join(spaces_dir, "images"),
            cache_dir,
            os.path.join(base_path, "log_archives", "processed"),
            os.path.join(base_path, "log_import_source", "processed"),
            os.path.join(base_path, "memory"),
            os.path.join(base_path, "memory", "backups"), # <-- この行を追加
            os.path.join(base_path, "private")
        ]
        for path in dirs_to_create:
            os.makedirs(path, exist_ok=True)

        # テキストベースのファイル
        world_settings_content = "## 共有リビング\n\n### リビング\n広々としたリビングルーム。大きな窓からは柔らかな光が差し込み、快適なソファが置かれている。\n"

        memory_template_content = (
            "## 聖域 (Sanctuary)\n"
            "# このエリアの内容は、コアメモリにそのままコピーされます。\n\n"
            "### 自己同一性 (Self Identity)\n\n\n"
            "## 日記 (Diary)\n"
            "# このエリアの内容は、AIによって要約され、コアメモリに追記されます。\n\n"
            f"### {datetime.datetime.now().strftime('%Y-%m-%d')}\n\n\n"
            "## アーカイブ要約 (Archive Summary)\n"
            "# このセクションには、アーカイブされた古い日記の要約が蓄積されます。\n\n"
        )
        text_files_to_create = {
            os.path.join(base_path, "SystemPrompt.txt"): "",
            os.path.join(base_path, "log.txt"): "",
            os.path.join(base_path, constants.NOTEPAD_FILENAME): "",
            os.path.join(base_path, "current_location.txt"): "リビング",
            os.path.join(spaces_dir, "world_settings.txt"): world_settings_content,
            os.path.join(base_path, "memory", "memory_main.txt"): memory_template_content, # <-- パス変更
            os.path.join(base_path, "private", "secret_diary.txt"): "" # <-- 追加
        }
        for file_path, content in text_files_to_create.items():
            if not os.path.exists(file_path):
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)

        # JSONベースのファイル
        json_files_to_create = {
            os.path.join(cache_dir, "scenery.json"): {},
            os.path.join(cache_dir, "image_prompts.json"): {"prompts": {}},
        }
        for file_path, content in json_files_to_create.items():
            if not os.path.exists(file_path):
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(content, f, indent=2, ensure_ascii=False)

        # room_config.json の設定（後方互換性も考慮）
        config_file_path = os.path.join(base_path, "room_config.json")
        if not os.path.exists(config_file_path) or os.path.getsize(config_file_path) == 0:
            default_config = {
                "room_name": room_name, # デフォルトはフォルダ名
                "user_display_name": "ユーザー",
                "description": "",
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "version": 1
            }
            with open(config_file_path, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=2, ensure_ascii=False)

        return True
    except Exception as e:
        print(f"ルーム '{room_name}' ファイル作成/確認エラー: {e}"); traceback.print_exc()
        return False

def get_room_list_for_ui() -> List[Tuple[str, str]]:
    """
    UIのドロップダウン表示用に、有効なルームのリストを `[('表示名', 'フォルダ名'), ...]` の形式で返す。
    room_config.json が存在するフォルダのみを有効なルームとみなす。
    """
    rooms_dir = constants.ROOMS_DIR
    if not os.path.exists(rooms_dir) or not os.path.isdir(rooms_dir):
        return []

    valid_rooms = []
    for folder_name in os.listdir(rooms_dir):
        room_path = os.path.join(rooms_dir, folder_name)
        if os.path.isdir(room_path):
            config_file = os.path.join(room_path, "room_config.json")
            if os.path.exists(config_file):
                try:
                    with open(config_file, "r", encoding="utf-8") as f:
                        config = json.load(f)
                        display_name = config.get("room_name", folder_name)
                        valid_rooms.append((display_name, folder_name))
                except (json.JSONDecodeError, IOError) as e:
                    print(f"警告: ルーム '{folder_name}' の設定ファイルが読めません: {e}")

    # 表示名でソートして返す
    return sorted(valid_rooms, key=lambda x: x[0])


def get_room_config(folder_name: str) -> Optional[dict]:
    """
    指定されたフォルダ名のルーム設定ファイル(room_config.json)を読み込み、辞書として返す。
    見つからない場合はNoneを返す。
    """
    if not folder_name:
        return None

    config_file = os.path.join(constants.ROOMS_DIR, folder_name, "room_config.json")
    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"警告: ルーム '{folder_name}' の設定ファイルが読めません: {e}")
            return None
    return None


def get_room_files_paths(room_name: str) -> Optional[Tuple[str, str, Optional[str], str, str]]:
    if not room_name or not ensure_room_files(room_name): return None, None, None, None, None
    base_path = os.path.join(constants.ROOMS_DIR, room_name)
    log_file = os.path.join(base_path, "log.txt")
    system_prompt_file = os.path.join(base_path, "SystemPrompt.txt")
    profile_image_path = os.path.join(base_path, constants.PROFILE_IMAGE_FILENAME)
    # memory.txt へのパスを memory/memory_main.txt に変更
    memory_main_path = os.path.join(base_path, "memory", "memory_main.txt")
    notepad_path = os.path.join(base_path, constants.NOTEPAD_FILENAME)
    if not os.path.exists(profile_image_path): profile_image_path = None
    return log_file, system_prompt_file, profile_image_path, memory_main_path, notepad_path

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
    full_log = utils.load_chat_log(log_file_path)

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


# ▼▼▼【ここからが新しく追加する関数】▼▼▼
def backup_log_file(room_name: str) -> Optional[str]:
    """
    指定されたルームのlog.txtを、タイムスタンプ付きでバックアップする。
    成功した場合はバックアップ先のパスを、失敗した場合はNoneを返す。
    """
    if not room_name:
        return None

    try:
        log_file_path, _, _, _, _ = get_room_files_paths(room_name)
        if not log_file_path or not os.path.exists(log_file_path):
            print(f"警告: バックアップ対象のログファイルが見つかりません: {log_file_path}")
            return None

        backup_dir = os.path.join(constants.ROOMS_DIR, room_name, "log_archives", "manual_backups")
        os.makedirs(backup_dir, exist_ok=True)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file_name = f"log_{timestamp}.bak.txt"
        backup_file_path = os.path.join(backup_dir, backup_file_name)

        shutil.copy2(log_file_path, backup_file_path)
        print(f"--- ログファイルのバックアップを作成しました: {backup_file_path} ---")
        return backup_file_path

    except Exception as e:
        print(f"!!! エラー: ログファイルのバックアップ中にエラーが発生しました: {e}")
        traceback.print_exc()
        return None
# ▲▲▲【追加はここまで】▲▲▲


def backup_memory_main_file(room_name: str) -> Optional[str]:
    """
    指定されたルームのmemory_main.txtを、タイムスタンプ付きでバックアップする。
    成功した場合はバックアップ先のパスを、失敗した場合はNoneを返す。
    """
    if not room_name:
        return None
    try:
        _, _, _, memory_main_path, _ = get_room_files_paths(room_name)
        if not memory_main_path or not os.path.exists(memory_main_path):
            print(f"警告: バックアップ対象の記憶ファイルが見つかりません: {memory_main_path}")
            return None

        backup_dir = os.path.join(constants.ROOMS_DIR, room_name, "memory", "backups")
        os.makedirs(backup_dir, exist_ok=True)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file_name = f"memory_main_{timestamp}.bak.txt"
        backup_file_path = os.path.join(backup_dir, backup_file_name)

        shutil.copy2(memory_main_path, backup_file_path)
        print(f"--- 記憶ファイルのバックアップを作成しました: {backup_file_path} ---")
        return backup_file_path
    except Exception as e:
        print(f"!!! エラー: 記憶ファイルのバックアップ中にエラーが発生しました: {e}")
        traceback.print_exc()
        return None
