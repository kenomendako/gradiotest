# config_manager.py の内容を、以下のコードで完全に置き換えてください

import json
import os
import traceback
from google.genai import types

# --- 設定関連定数 ---
CONFIG_FILE = "config.json"
ALARMS_FILE = "alarms.json"
CHARACTERS_DIR = "characters"
PROFILE_IMAGE_FILENAME = "profile.png"
MEMORY_FILENAME = "memory.json"
API_HISTORY_LIMIT_OPTIONS = {"10": "10往復", "20": "20往復", "30": "30往復", "40": "40往復", "50": "50往復", "60": "60往復", "70": "70往復", "80": "80往復", "90": "90往復", "100": "100往復", "all": "全ログ"}
UI_HISTORY_MAX_LIMIT = 200
DEFAULT_API_HISTORY_LIMIT_OPTION = "all"
DEFAULT_ALARM_API_HISTORY_TURNS = 10 # ★ 変更
SAFETY_CONFIG = [
    {"category": types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, "threshold": types.HarmBlockThreshold.BLOCK_NONE},
    {"category": types.HarmCategory.HARM_CATEGORY_HARASSMENT, "threshold": types.HarmBlockThreshold.BLOCK_NONE},
    {"category": types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, "threshold": types.HarmBlockThreshold.BLOCK_NONE},
    {"category": types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, "threshold": types.HarmBlockThreshold.BLOCK_NONE},
]

# --- 設定関連グローバル変数 ---
initial_character_global = None
initial_model_global = None
initial_api_key_name_global = None
initial_add_timestamp_global = False
initial_send_thoughts_to_api_global = True
initial_api_history_limit_option_global = DEFAULT_API_HISTORY_LIMIT_OPTION
initial_alarm_api_history_turns_global = DEFAULT_ALARM_API_HISTORY_TURNS
initial_tavily_api_key_global = None
API_KEYS = {}
TAVILY_API_KEY = ""
AVAILABLE_MODELS_GLOBAL = []
DEFAULT_MODEL_GLOBAL = None
# ★ 通知関連のグローバル変数を追加
NOTIFICATION_SERVICE_GLOBAL = "discord"
NOTIFICATION_WEBHOOK_URL_GLOBAL = None
PUSHOVER_APP_TOKEN_GLOBAL = None
PUSHOVER_USER_KEY_GLOBAL = None

def get_character_list():
    from character_manager import get_character_list as get_char_list_impl
    return get_char_list_impl()

def load_config():
    global API_KEYS, initial_api_key_name_global, initial_character_global, initial_model_global, initial_add_timestamp_global
    global initial_send_thoughts_to_api_global, initial_api_history_limit_option_global, initial_alarm_api_history_turns_global
    global AVAILABLE_MODELS_GLOBAL, DEFAULT_MODEL_GLOBAL, TAVILY_API_KEY
    global NOTIFICATION_SERVICE_GLOBAL, NOTIFICATION_WEBHOOK_URL_GLOBAL, PUSHOVER_APP_TOKEN_GLOBAL, PUSHOVER_USER_KEY_GLOBAL

    default_config = {
        "api_keys": {"your_key_name_1": "YOUR_API_KEY_HERE"},
        "available_models": ["gemini-2.5-pro"],
        "default_model": "gemini-2.5-pro",
        "default_api_key_name": "your_key_name_1",
        "last_character": "Default",
        "last_model": "gemini-2.5-pro",
        "last_api_key_name": "your_key_name_1",
        "add_timestamp": False,
        "last_send_thoughts_to_api": True,
        "last_api_history_limit_option": DEFAULT_API_HISTORY_LIMIT_OPTION,
        "alarm_api_history_turns": DEFAULT_ALARM_API_HISTORY_TURNS,
        "tavily_api_key": "YOUR_TAVILY_API_KEY_HERE",
        # ★ 通知関連のデフォルト値を追加
        "notification_service": "discord",
        "notification_webhook_url": None,
        "pushover_app_token": None,
        "pushover_user_key": None
    }

    config = {}
    if not os.path.exists(CONFIG_FILE):
        print(f"情報: '{CONFIG_FILE}' が見つかりませんでした。デフォルト設定で作成します。")
        config = default_config
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"設定ファイルの作成に失敗しました: {e}")
    else:
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception as e:
            print(f"'{CONFIG_FILE}' の読み込みエラー: {e}。デフォルト設定を使用します。")
            config = default_config

    # 既存の読み込み処理...
    API_KEYS = config.get("api_keys", {})
    AVAILABLE_MODELS_GLOBAL = config.get("available_models", ["gemini-2.5-pro"])
    DEFAULT_MODEL_GLOBAL = config.get("default_model", "gemini-2.5-pro")
    initial_api_key_name_global = config.get("last_api_key_name") or config.get("default_api_key_name") or (list(API_KEYS.keys())[0] if API_KEYS else None)
    character_list = get_character_list()
    initial_character_global = config.get("last_character", "Default")
    if initial_character_global not in character_list:
        initial_character_global = character_list[0] if character_list else "Default"
    initial_model_global = config.get("last_model", DEFAULT_MODEL_GLOBAL)
    initial_add_timestamp_global = config.get("add_timestamp", False)
    initial_send_thoughts_to_api_global = config.get("last_send_thoughts_to_api", True)
    initial_api_history_limit_option_global = config.get("last_api_history_limit_option", DEFAULT_API_HISTORY_LIMIT_OPTION)
    initial_alarm_api_history_turns_global = config.get("alarm_api_history_turns", DEFAULT_ALARM_API_HISTORY_TURNS)
    TAVILY_API_KEY = config.get("tavily_api_key")

    # ★ 通知関連の設定を読み込む
    NOTIFICATION_SERVICE_GLOBAL = config.get("notification_service", "discord")
    NOTIFICATION_WEBHOOK_URL_GLOBAL = config.get("notification_webhook_url")
    PUSHOVER_APP_TOKEN_GLOBAL = config.get("pushover_app_token")
    PUSHOVER_USER_KEY_GLOBAL = config.get("pushover_user_key")

    # 設定ファイルに不足しているキーがあれば追記する
    needs_update = False
    for key, default_value in default_config.items():
        if key not in config:
            config[key] = default_value
            needs_update = True
    if needs_update:
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            print(f"'{CONFIG_FILE}' に不足していたキーを追記しました。")
        except Exception as e:
            print(f"設定ファイルの更新に失敗しました: {e}")

def save_config(key, value):
    try:
        config = {}
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
        config[key] = value
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"設定の保存エラー ({key}): {e}")
