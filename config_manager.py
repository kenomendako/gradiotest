# config_manager.py (最終・完全・確定版)
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
HISTORY_LIMIT = 20
MEMORY_SUMMARY_LIMIT_FOR_API = 3
API_HISTORY_LIMIT_OPTIONS = {"10": "10往復", "20": "20往復", "30": "30往復", "40": "40往復", "50": "50往復", "60": "60往復", "all": "全ログ"}
DEFAULT_API_HISTORY_LIMIT_OPTION = "all"
DEFAULT_ALARM_MODEL = "gemini-1.5-flash-latest"
DEFAULT_ALARM_API_HISTORY_TURNS = 1
DEFAULT_NOTIFICATION_WEBHOOK_URL = None
SAFETY_CONFIG = {types.HarmCategory.HARM_CATEGORY_HATE_SPEECH: types.HarmBlockThreshold.BLOCK_NONE, types.HarmCategory.HARM_CATEGORY_HARASSMENT: types.HarmBlockThreshold.BLOCK_NONE, types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: types.HarmBlockThreshold.BLOCK_NONE, types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: types.HarmBlockThreshold.BLOCK_NONE}

# --- 設定関連グローバル変数 (他モジュールから参照される) ---
initial_character_global = None
initial_model_global = None
initial_api_key_name_global = None
initial_add_timestamp_global = False
initial_send_thoughts_to_api_global = True
initial_api_history_limit_option_global = DEFAULT_API_HISTORY_LIMIT_OPTION
initial_alarm_model_global = DEFAULT_ALARM_MODEL
initial_alarm_api_history_turns_global = DEFAULT_ALARM_API_HISTORY_TURNS
initial_notification_webhook_url_global = DEFAULT_NOTIFICATION_WEBHOOK_URL
API_KEYS = {}
AVAILABLE_MODELS_GLOBAL = []
DEFAULT_MODEL_GLOBAL = None

# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
# ★★★ config_managerは、他のプロジェクトモジュールを一切インポートしません ★★★
# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★

def load_config():
    """設定ファイルを読み込み、グローバル変数を設定する。他のモジュールへの依存を一切持たない。"""
    global API_KEYS, initial_api_key_name_global, initial_character_global, initial_model_global, initial_add_timestamp_global, initial_send_thoughts_to_api_global, initial_api_history_limit_option_global, initial_alarm_model_global, initial_alarm_api_history_turns_global, AVAILABLE_MODELS_GLOBAL, DEFAULT_MODEL_GLOBAL, initial_notification_webhook_url_global
    default_config = {
        "api_keys": {"your_key_name_1": "YOUR_API_KEY_HERE"}, "available_models": ["gemini-1.5-pro-latest"],
        "default_model": "gemini-1.5-pro-latest", "default_api_key_name": "your_key_name_1",
        "last_character": "Default", "last_model": "gemini-1.5-pro-latest", "last_api_key_name": "your_key_name_1",
        "add_timestamp": False, "last_send_thoughts_to_api": True, "last_api_history_limit_option": DEFAULT_API_HISTORY_LIMIT_OPTION,
        "alarm_model": DEFAULT_ALARM_MODEL, "alarm_api_history_turns": DEFAULT_ALARM_API_HISTORY_TURNS,
        "notification_webhook_url": DEFAULT_NOTIFICATION_WEBHOOK_URL
    }
    config = {}
    if not os.path.exists(CONFIG_FILE):
        print(f"情報: '{CONFIG_FILE}' なし。デフォルト作成。"); config = default_config
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f: json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e: print(f"設定ファイル作成失敗: {e}")
    else:
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f: config = json.load(f)
        except Exception as e: print(f"'{CONFIG_FILE}' 読込エラー: {e}。デフォルト設定使用。"); config = default_config

    API_KEYS = config.get("api_keys", {})
    AVAILABLE_MODELS_GLOBAL = config.get("available_models", default_config["available_models"])
    DEFAULT_MODEL_GLOBAL = config.get("default_model")
    if not DEFAULT_MODEL_GLOBAL or DEFAULT_MODEL_GLOBAL not in AVAILABLE_MODELS_GLOBAL:
        DEFAULT_MODEL_GLOBAL = AVAILABLE_MODELS_GLOBAL[0] if AVAILABLE_MODELS_GLOBAL else None

    initial_character_global = config.get("last_character", "Default") # Just read, no validation here

    last_key = config.get("last_api_key_name")
    config_default_key = config.get("default_api_key_name")
    if last_key and last_key in API_KEYS: initial_api_key_name_global = last_key
    elif config_default_key and config_default_key in API_KEYS: initial_api_key_name_global = config_default_key
    elif API_KEYS: initial_api_key_name_global = list(API_KEYS.keys())[0]
    else: initial_api_key_name_global = None

    initial_model_global = config.get("last_model", DEFAULT_MODEL_GLOBAL)
    initial_add_timestamp_global = config.get("add_timestamp", default_config["add_timestamp"])
    initial_send_thoughts_to_api_global = config.get("last_send_thoughts_to_api", default_config["last_send_thoughts_to_api"])
    initial_api_history_limit_option_global = config.get("last_api_history_limit_option", default_config["last_api_history_limit_option"])
    initial_alarm_model_global = config.get("alarm_model", default_config["alarm_model"])
    initial_alarm_api_history_turns_global = config.get("alarm_api_history_turns", default_config["alarm_api_history_turns"])
    initial_notification_webhook_url_global = config.get("notification_webhook_url", default_config["notification_webhook_url"])

    needs_update_flag = False # Renamed to avoid conflict if 'needs_update' is a key in default_config
    for key, default_value in default_config.items():
        if key not in config:
            config[key] = default_value
            needs_update_flag = True
    if needs_update_flag: # Check the renamed flag
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f: json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e: print(f"設定ファイル更新失敗: {e}")

def save_config(key, value):
    try:
        config = {}
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f: config = json.load(f)
        config[key] = value
        with open(CONFIG_FILE, "w", encoding="utf-8") as f: json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e: print(f"設定保存エラー ({key}): {e}"); traceback.print_exc()
