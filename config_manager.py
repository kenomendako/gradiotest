# config_manager.py
import json
import os
import traceback
from google.generativeai import types as genai_types # Assuming this is used or was planned

# --- 設定関連定数 ---
CONFIG_FILE = "config.json"
DEFAULT_API_HISTORY_LIMIT_OPTION = "直近5ターン"
API_HISTORY_LIMIT_OPTIONS = [DEFAULT_API_HISTORY_LIMIT_OPTION, "直近10ターン", "直近15ターン", "直近20ターン", "制限なし"]
DEFAULT_ALARM_MODEL = "gemini-1.0-pro" # Default, will be overridden by config if available
DEFAULT_ALARM_API_HISTORY_TURNS = 5
DEFAULT_NOTIFICATION_WEBHOOK_URL = None
ALARMS_FILE = "alarms.json" # Added as per alarm_manager.py usage

# --- 設定関連グローバル変数 (他モジュールから参照される) ---
API_KEYS = {}
AVAILABLE_MODELS_GLOBAL = []
DEFAULT_MODEL_GLOBAL = None
initial_api_key_name_global = None
initial_character_global = None
initial_model_global = None
initial_add_timestamp_global = False
initial_send_thoughts_to_api_global = True
initial_api_history_limit_option_global = DEFAULT_API_HISTORY_LIMIT_OPTION
initial_alarm_model_global = DEFAULT_ALARM_MODEL
initial_alarm_api_history_turns_global = DEFAULT_ALARM_API_HISTORY_TURNS
initial_notification_webhook_url_global = DEFAULT_NOTIFICATION_WEBHOOK_URL

# --- 設定ファイル読み書き関数 ---

def get_character_list():
    """
    キャラクターリストを取得します.
    循環参照を避けるため、この関数の中で character_manager をインポートします.
    """
    # ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
    # ★★★ これが循環参照を解決する、唯一の正しい修正です ★★★
    # ★★★ インポート文を、それが必要な関数の内部に移動します ★★★
    # ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
    from character_manager import get_character_list as get_char_list_impl
    return get_char_list_impl()

def load_config():
    global API_KEYS, initial_api_key_name_global, initial_character_global, initial_model_global, initial_add_timestamp_global, initial_send_thoughts_to_api_global, initial_api_history_limit_option_global, initial_alarm_model_global, initial_alarm_api_history_turns_global, AVAILABLE_MODELS_GLOBAL, DEFAULT_MODEL_GLOBAL, initial_notification_webhook_url_global
    default_config = {
        "api_keys": {"your_key_name_1": "YOUR_API_KEY_HERE"},
        "available_models": ["gemini-1.5-pro-latest"],
        "default_model": "gemini-1.5-pro-latest",
        "default_api_key_name": "your_key_name_1",
        "last_character": "Default",
        "last_model": "gemini-1.5-pro-latest",
        "last_api_key_name": "your_key_name_1",
        "add_timestamp": False,
        "last_send_thoughts_to_api": True,
        "last_api_history_limit_option": DEFAULT_API_HISTORY_LIMIT_OPTION,
        "alarm_model": DEFAULT_ALARM_MODEL,
        "alarm_api_history_turns": DEFAULT_ALARM_API_HISTORY_TURNS,
        "notification_webhook_url": DEFAULT_NOTIFICATION_WEBHOOK_URL
    }
    config = {}
    if not os.path.exists(CONFIG_FILE):
        print(f"情報: '{CONFIG_FILE}' なし.デフォルト作成.APIキーとWebhook URL(任意)の編集要."); config = default_config # Corrected period
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f: json.dump(config, f, indent=2, ensure_ascii=False); print(f"'{CONFIG_FILE}' 作成完了.") # Corrected period
        except Exception as e: print(f"設定ファイル作成失敗: {e}")
    else:
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
        except json.JSONDecodeError as e:
            print(f"JSONデコードエラー: {e}")
            print(f"エラー発生位置: {e.pos} (行: {e.lineno}, 列: {e.colno})")
            raise
        except Exception as e: print(f"'{CONFIG_FILE}' 読込エラー: {e}.デフォルト設定使用."); config = default_config # Corrected period

    API_KEYS = config.get("api_keys", {})
    if not isinstance(API_KEYS, dict): API_KEYS = {}
    AVAILABLE_MODELS_GLOBAL = config.get("available_models", default_config["available_models"])
    if not isinstance(AVAILABLE_MODELS_GLOBAL, list) or not AVAILABLE_MODELS_GLOBAL: AVAILABLE_MODELS_GLOBAL = default_config["available_models"]
    AVAILABLE_MODELS_GLOBAL = [m for m in AVAILABLE_MODELS_GLOBAL if isinstance(m, str) and m.strip()]
    if not AVAILABLE_MODELS_GLOBAL: AVAILABLE_MODELS_GLOBAL = default_config["available_models"]
    DEFAULT_MODEL_GLOBAL = config.get("default_model")
    if not DEFAULT_MODEL_GLOBAL or DEFAULT_MODEL_GLOBAL not in AVAILABLE_MODELS_GLOBAL: DEFAULT_MODEL_GLOBAL = AVAILABLE_MODELS_GLOBAL[0] if AVAILABLE_MODELS_GLOBAL else None

    config_default_key = config.get("default_api_key_name"); last_key = config.get("last_api_key_name")
    if last_key and isinstance(last_key, str) and last_key in API_KEYS: initial_api_key_name_global = last_key
    elif config_default_key and isinstance(config_default_key, str) and config_default_key in API_KEYS: initial_api_key_name_global = config_default_key
    elif API_KEYS: initial_api_key_name_global = list(API_KEYS.keys())[0]
    else: initial_api_key_name_global = None

    character_list = get_character_list()

    initial_character_global = config.get("last_character", "Default")
    if not character_list or initial_character_global not in character_list: initial_character_global = character_list[0] if character_list else None
    initial_model_global = config.get("last_model", DEFAULT_MODEL_GLOBAL)
    if initial_model_global not in AVAILABLE_MODELS_GLOBAL: initial_model_global = DEFAULT_MODEL_GLOBAL
    initial_add_timestamp_global = config.get("add_timestamp", default_config["add_timestamp"])
    initial_send_thoughts_to_api_global = config.get("last_send_thoughts_to_api", default_config["last_send_thoughts_to_api"])
    initial_api_history_limit_option_global = config.get("last_api_history_limit_option", default_config["last_api_history_limit_option"])
    if initial_api_history_limit_option_global not in API_HISTORY_LIMIT_OPTIONS: initial_api_history_limit_option_global = default_config["last_api_history_limit_option"]
    initial_alarm_model_global = config.get("alarm_model", default_config["alarm_model"])
    initial_alarm_api_history_turns_global = config.get("alarm_api_history_turns", default_config["alarm_api_history_turns"])
    if not isinstance(initial_alarm_api_history_turns_global, int) or initial_alarm_api_history_turns_global < 0: initial_alarm_api_history_turns_global = default_config["alarm_api_history_turns"]
    initial_notification_webhook_url_global = config.get("notification_webhook_url", default_config["notification_webhook_url"])
    if initial_notification_webhook_url_global and not isinstance(initial_notification_webhook_url_global, str):
        initial_notification_webhook_url_global = None
    elif initial_notification_webhook_url_global == "":
        initial_notification_webhook_url_global = None

    needs_update = False
    for key, default_value in default_config.items():
        if key not in config: config[key] = default_value; needs_update = True
    if needs_update:
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f: json.dump(config, f, indent=2, ensure_ascii=False); print(f"'{CONFIG_FILE}' 不足キー追記完了.") # Corrected period
        except Exception as e: print(f"設定ファイル更新失敗: {e}")

def save_config(key, value):
    try:
        config = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f: config = json.load(f)
            except Exception as e: print(f"設定読込失敗 ({key}): {e}"); return
        else: print("設定ファイルなし、保存不可."); return # Corrected period
        if config.get(key) == value: return
        config[key] = value
        with open(CONFIG_FILE, "w", encoding="utf-8") as f: json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"設定保存エラー ({key}): {e}"); traceback.print_exc()