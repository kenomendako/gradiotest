# -*- coding: utf-8 -*-
import json
import os
import traceback
from google.genai import types # SAFETY_CONFIG定義のため

# --- 設定関連定数 ---
CONFIG_FILE = "config.json"
ALARMS_FILE = "alarms.json"
CHARACTERS_DIR = "characters"
PROFILE_IMAGE_FILENAME = "profile.png"
MEMORY_FILENAME = "memory.json"
MEMORY_SUMMARY_LIMIT_FOR_API = 3
API_HISTORY_LIMIT_OPTIONS = {"10": "10往復", "20": "20往復", "30": "30往復", "40": "40往復", "50": "50往復", "60": "60往復", "70": "70往復", "80": "80往復", "90": "90往復", "100": "100往復", "all": "全ログ"}
UI_HISTORY_MAX_LIMIT = 200 # UI表示上限
DEFAULT_API_HISTORY_LIMIT_OPTION = "all"
DEFAULT_ALARM_MODEL = "gemini-1.5-flash-latest"
DEFAULT_ALARM_API_HISTORY_TURNS = 1
DEFAULT_NOTIFICATION_WEBHOOK_URL = None # Webhook URLのデフォルトはNone
DEFAULT_MEMORY_WEAVER_HISTORY_COUNT = 30
# ★★★【最後の真実】safety_settings は、この「辞書のリスト」形式でなければならない ★★★
SAFETY_CONFIG = [
    {
        "category": types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        "threshold": types.HarmBlockThreshold.BLOCK_NONE,
    },
    {
        "category": types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        "threshold": types.HarmBlockThreshold.BLOCK_NONE,
    },
    {
        "category": types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        "threshold": types.HarmBlockThreshold.BLOCK_NONE,
    },
    {
        "category": types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        "threshold": types.HarmBlockThreshold.BLOCK_NONE,
    },
]

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
initial_memory_weaver_history_count_global = DEFAULT_MEMORY_WEAVER_HISTORY_COUNT
API_KEYS = {}
AVAILABLE_MODELS_GLOBAL = []
DEFAULT_MODEL_GLOBAL = None

# --- 設定ファイル読み書き関数 ---

# character_managerの関数が必要なため、ここでは定義のみ
def get_character_list():
    # 実装は character_manager.py に移動
    from character_manager import get_character_list as get_char_list_impl
    return get_char_list_impl()

def load_config():
    global API_KEYS, initial_api_key_name_global, initial_character_global, initial_model_global, initial_add_timestamp_global, initial_send_thoughts_to_api_global, initial_api_history_limit_option_global, initial_alarm_model_global, initial_alarm_api_history_turns_global, AVAILABLE_MODELS_GLOBAL, DEFAULT_MODEL_GLOBAL, initial_notification_webhook_url_global, initial_memory_weaver_history_count_global
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
        "notification_webhook_url": DEFAULT_NOTIFICATION_WEBHOOK_URL, # デフォルト値を追加
        "memory_weaver_history_count": DEFAULT_MEMORY_WEAVER_HISTORY_COUNT
    }
    config = {}
    if not os.path.exists(CONFIG_FILE):
        print(f"情報: '{CONFIG_FILE}' なし。デフォルト作成。APIキーとWebhook URL(任意)の編集要。"); config = default_config
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f: json.dump(config, f, indent=2, ensure_ascii=False); print(f"'{CONFIG_FILE}' 作成完了。")
        except Exception as e: print(f"設定ファイル作成失敗: {e}")
    else:
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)  # JSONデコードエラーが発生する箇所
        except json.JSONDecodeError as e:
            print(f"JSONデコードエラー: {e}")
            print(f"エラー発生位置: {e.pos} (行: {e.lineno}, 列: {e.colno})")
            raise
        except Exception as e: print(f"'{CONFIG_FILE}' 読込エラー: {e}。デフォルト設定使用。"); config = default_config

    # --- 既存のconfig読み込み処理 (省略) ---
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
    character_list = get_character_list() # character_manager.pyの関数を呼び出す
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
    # --- Webhook URL読み込み ---
    initial_notification_webhook_url_global = config.get("notification_webhook_url", default_config["notification_webhook_url"])
    if initial_notification_webhook_url_global and not isinstance(initial_notification_webhook_url_global, str):
        print(f"警告: config.jsonのnotification_webhook_urlが文字列ではありません。無効にします。")
        initial_notification_webhook_url_global = None
    elif initial_notification_webhook_url_global == "": # 空文字列もNone扱い
        initial_notification_webhook_url_global = None

    initial_memory_weaver_history_count_global = config.get("memory_weaver_history_count", DEFAULT_MEMORY_WEAVER_HISTORY_COUNT)
    if not isinstance(initial_memory_weaver_history_count_global, int) or initial_memory_weaver_history_count_global <= 0:
        initial_memory_weaver_history_count_global = DEFAULT_MEMORY_WEAVER_HISTORY_COUNT

    needs_update = False
    for key, default_value in default_config.items():
        if key not in config: config[key] = default_value; needs_update = True
    if needs_update:
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f: json.dump(config, f, indent=2, ensure_ascii=False); print(f"'{CONFIG_FILE}' 不足キー追記完了。")
        except Exception as e: print(f"設定ファイル更新失敗: {e}")

def save_config(key, value):
    try:
        config = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f: config = json.load(f)
            except Exception as e: print(f"設定読込失敗 ({key}): {e}"); return
        else: print("設定ファイルなし、保存不可。"); return
        if config.get(key) == value: return
        config[key] = value
        with open(CONFIG_FILE, "w", encoding="utf-8") as f: json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e: print(f"設定保存エラー ({key}): {e}"); traceback.print.exc()