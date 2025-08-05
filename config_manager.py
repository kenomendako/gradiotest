# config_manager.py (最終確定版)

import json
import os
import constants

# --- グローバル変数 ---
API_KEYS = {}
AVAILABLE_MODELS_GLOBAL = []
DEFAULT_MODEL_GLOBAL = "gemini-2.5-pro"
TAVILY_API_KEY = None

# ▼▼▼ 新しいグローバル変数を追加 ▼▼▼
NOTIFICATION_SERVICE_GLOBAL = "discord"
NOTIFICATION_WEBHOOK_URL_GLOBAL = None
PUSHOVER_APP_TOKEN_GLOBAL = None
PUSHOVER_USER_KEY_GLOBAL = None
# ▲▲▲ 追加ここまで ▲▲▲

SUPPORTED_VOICES = {
    "vindemiatrix": "ヴィンデミアトリックス (デフォルト)",
    "luna": "ルナ (お姉さん)",
    "sol": "ソル (お兄さん)",
    "aria": "アリア (少女)",
    "mare": "マーレ (少年)",
    "alba": "アルバ (落ち着いた女性)",
    "umbra": "アンブラ (落ち着いた男性)",
}

initial_api_key_name_global = "default"
initial_character_global = "Default"
initial_model_global = DEFAULT_MODEL_GLOBAL
initial_send_thoughts_to_api_global = True
initial_api_history_limit_option_global = constants.DEFAULT_API_HISTORY_LIMIT_OPTION
initial_alarm_api_history_turns_global = constants.DEFAULT_ALARM_API_HISTORY_TURNS

def load_config():
    global API_KEYS, initial_api_key_name_global, initial_character_global, initial_model_global
    global initial_send_thoughts_to_api_global, initial_api_history_limit_option_global, initial_alarm_api_history_turns_global
    global AVAILABLE_MODELS_GLOBAL, DEFAULT_MODEL_GLOBAL, TAVILY_API_KEY
    global NOTIFICATION_SERVICE_GLOBAL, NOTIFICATION_WEBHOOK_URL_GLOBAL, PUSHOVER_APP_TOKEN_GLOBAL, PUSHOVER_USER_KEY_GLOBAL

    default_config = {
        "api_keys": {"your_key_name_1": "YOUR_API_KEY_HERE"}, "available_models": ["gemini-2.5-pro"], "default_model": "gemini-2.5-pro",
        "default_api_key_name": "your_key_name_1", "last_character": "Default", "last_model": "gemini-2.5-pro",
        "last_api_key_name": "your_key_name_1", "last_send_thoughts_to_api": True,
        "last_api_history_limit_option": constants.DEFAULT_API_HISTORY_LIMIT_OPTION, "alarm_api_history_turns": constants.DEFAULT_ALARM_API_HISTORY_TURNS,
        "tavily_api_key": "YOUR_TAVILY_API_KEY_HERE", "notification_service": "discord", "notification_webhook_url": None,
        "pushover_app_token": None, "pushover_user_key": None
    }

    config = default_config.copy() # デフォルトをコピーして開始
    if os.path.exists(constants.CONFIG_FILE):
        try:
            with open(constants.CONFIG_FILE, "r", encoding="utf-8") as f:
                # 既存の設定を上書きする形で読み込む
                config.update(json.load(f))
        except Exception as e:
            print(f"'{constants.CONFIG_FILE}' 読込エラー: {e}")

    # ▼▼▼ ここからが修正の核心 ▼▼▼
    API_KEYS = config.get("api_keys", {})
    valid_api_keys = list(API_KEYS.keys())

    # 1. 有効なAPIキーが存在しない場合は、処理を中断
    if not valid_api_keys or "YOUR_API_KEY_HERE" in API_KEYS.values():
        print("警告: config.jsonに有効なAPIキーが設定されていません。")
        initial_api_key_name_global = config.get("default_api_key_name") # 一時的に設定
    else:
        # 2. last_api_key_name を検証
        last_key = config.get("last_api_key_name")
        if last_key and last_key in valid_api_keys:
            initial_api_key_name_global = last_key
        else:
            # 3. last が無効なら default_api_key_name を検証
            default_key = config.get("default_api_key_name")
            if default_key and default_key in valid_api_keys:
                initial_api_key_name_global = default_key
            else:
                # 4. 両方無効なら、有効なキーリストの先頭を強制的に使用
                initial_api_key_name_global = valid_api_keys[0]

    # ▲▲▲ 修正ここまで ▲▲▲

    AVAILABLE_MODELS_GLOBAL = config.get("available_models", ["gemini-2.5-pro"])
    DEFAULT_MODEL_GLOBAL = config.get("default_model", "gemini-2.5-pro")

    initial_character_global = config.get("last_character", "Default")
    initial_model_global = config.get("last_model", DEFAULT_MODEL_GLOBAL)
    initial_send_thoughts_to_api_global = config.get("last_send_thoughts_to_api", True)
    initial_api_history_limit_option_global = config.get("last_api_history_limit_option", constants.DEFAULT_API_HISTORY_LIMIT_OPTION)
    initial_alarm_api_history_turns_global = config.get("alarm_api_history_turns", constants.DEFAULT_ALARM_API_HISTORY_TURNS)
    TAVILY_API_KEY = config.get("tavily_api_key")
    NOTIFICATION_SERVICE_GLOBAL = config.get("notification_service", "discord")
    NOTIFICATION_WEBHOOK_URL_GLOBAL = config.get("notification_webhook_url")
    PUSHOVER_APP_TOKEN_GLOBAL = config.get("pushover_app_token")
    PUSHOVER_USER_KEY_GLOBAL = config.get("pushover_user_key")

    # 設定ファイルが存在しないか、更新が必要な場合に保存する
    if not os.path.exists(constants.CONFIG_FILE) or any(key not in config for key in default_config):
        # 実際に適用される可能性のある初期値をconfigに反映
        config["last_api_key_name"] = initial_api_key_name_global
        save_config(None, config, is_full_config=True)


def save_config(key, value, is_full_config=False):
    # (この関数の中身は変更ありません)
    try:
        config = {}
        if os.path.exists(constants.CONFIG_FILE):
            with open(constants.CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)

        if is_full_config and isinstance(value, dict):
            config = value
        elif key:
            config[key] = value

        with open(constants.CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"'{constants.CONFIG_FILE}' 保存エラー: {e}")

def get_effective_settings(character_name):
    # (この関数の中身は変更ありません)
    char_config_path = os.path.join(constants.CHARACTERS_DIR, character_name, "character_config.json")

    # グローバル設定をデフォルトとして取得
    effective_settings = {
        "model_name": DEFAULT_MODEL_GLOBAL,
        "voice_id": "vindemiatrix",
        "voice_style_prompt": "",
        "add_timestamp": False,
        "send_thoughts": initial_send_thoughts_to_api_global,
        "send_notepad": True,
        "use_common_prompt": False,
        "send_core_memory": True,
        "send_scenery": True,
    }

    # キャラクター固有の設定があれば上書き
    if os.path.exists(char_config_path):
        try:
            with open(char_config_path, "r", encoding="utf-8") as f:
                char_config = json.load(f)

            override_settings = char_config.get("override_settings", {})
            for key, value in override_settings.items():
                if value is not None:
                    effective_settings[key] = value
        except Exception as e:
            print(f"キャラクター設定ファイル '{char_config_path}' の読み込みエラー: {e}")

    # モデル名が空またはNoneの場合は、グローバルデフォルトを使用
    if not effective_settings.get("model_name"):
        effective_settings["model_name"] = DEFAULT_MODEL_GLOBAL

    return effective_settings
