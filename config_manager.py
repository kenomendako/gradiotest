# config_manager.py の内容を、以下のコードで完全に置き換えてください

import json
import os
import traceback
from google.genai import types

# ★★★ ここから追加 ★★★
SUPPORTED_VOICES = {
    # 女性的な声
    "achird": "Achird (女性)",
    "alcyone": "Alcyone (女性)",
    "callirrhoe": "Callirrhoe (女性)",
    "despina": "Despina (女性)",
    "erinome": "Erinome (女性)",
    "kore": "Kore (女性)",
    "laomedeia": "Laomedeia (女性)",
    "leda": "Leda (女性)",
    "pulcherrima": "Pulcherrima (女性)",
    "sadachbia": "Sadachbia (女性)",
    "schedar": "Schedar (女性)",
    "sulafat": "Sulafat (女性)",
    "umbriel": "Umbriel (女性)",
    "vindemiatrix": "Vindemiatrix (女性)",
    "zephyr": "Zephyr (女性)",
    # 男性的な声
    "achernar": "Achernar (男性)",
    "algenib": "Algenib (男性)",
    "algieba": "Algieba (男性)",
    "alnilam": "Alnilam (男性)",
    "aoede": "Aoede (男性)",
    "autonoe": "Autonoe (男性)",
    "charon": "Charon (男性)",
    "enceladus": "Enceladus (男性)",
    "fenrir": "Fenrir (男性)",
    "gacrux": "Gacrux (男性)",
    "iapetus": "Iapetus (男性)",
    "orus": "Orus (男性)",
    "puck": "Puck (男性)",
    "rasalgethi": "Rasalgethi (男性)",
    "sadaltager": "Sadaltager (男性)",
    "zubenelgenubi": "Zubenelgenubi (男性)",
}
# ★★★ ここまで追加 ★★★

# --- 設定関連定数 ---
CONFIG_FILE = "config.json"
ALARMS_FILE = "alarms.json"
CHARACTERS_DIR = "characters"
PROFILE_IMAGE_FILENAME = "profile.png"
MEMORY_FILENAME = "memory.json"
API_HISTORY_LIMIT_OPTIONS = {"10": "10往復", "20": "20往復", "30": "30往復", "40": "40往復", "50": "50往復", "60": "60往復", "70": "70往復", "80": "80往復", "90": "90往復", "100": "100往復", "all": "全ログ"}
UI_HISTORY_MAX_LIMIT = 200
DEFAULT_API_HISTORY_LIMIT_OPTION = "all"
DEFAULT_ALARM_API_HISTORY_TURNS = 10
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
# ★ 通知関連のグローバル変数を修正・復活
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
        "notification_service": "discord",
        "notification_webhook_url": None,
        "pushover_app_token": None,
        "pushover_user_key": None
    }

    config = {}
    if not os.path.exists(CONFIG_FILE):
        config = default_config
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f: json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e: print(f"設定ファイルの作成に失敗しました: {e}")
    else:
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f: config = json.load(f)
        except Exception as e:
            print(f"'{CONFIG_FILE}' の読み込みエラー: {e}。デフォルト設定を使用します。")
            config = default_config

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

    NOTIFICATION_SERVICE_GLOBAL = config.get("notification_service", "discord")
    NOTIFICATION_WEBHOOK_URL_GLOBAL = config.get("notification_webhook_url")
    PUSHOVER_APP_TOKEN_GLOBAL = config.get("pushover_app_token")
    PUSHOVER_USER_KEY_GLOBAL = config.get("pushover_user_key")

    needs_update = False
    for key, default_value in default_config.items():
        if key not in config:
            config[key] = default_value
            needs_update = True
    if needs_update:
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f: json.dump(config, f, indent=2, ensure_ascii=False)
            print(f"'{CONFIG_FILE}' に不足していたキーを追記しました。")
        except Exception as e: print(f"設定ファイルの更新に失敗しました: {e}")

def save_config(key, value):
    try:
        config = {}
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f: config = json.load(f)
        config[key] = value
        with open(CONFIG_FILE, "w", encoding="utf-8") as f: json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e: print(f"設定の保存エラー ({key}): {e}")

# ★★★ ここから追加 ★★★
def get_effective_settings(character_name: str) -> dict:
    """共通設定とキャラクター個別設定をマージして、有効な設定セットを返す。"""

    # 1. ベースとなる共通設定を準備
    effective_settings = {
        "model_name": initial_model_global,
        "api_key_name": initial_api_key_name_global,
        "send_thoughts": initial_send_thoughts_to_api_global,
        "send_notepad": True, # UIのデフォルト値に合わせる
        "use_common_prompt": True, # UIのデフォルト値に合わせる
        "send_core_memory": True, # UIのデフォルト値に合わせる
        "send_scenery": True, # UIのデフォルト値に合わせる
        # ★★★ ここを修正 ★★★
        "voice_id": "vindemiatrix" # デフォルトをサポートされている声に変更
    }

    # 2. キャラクター個別設定ファイルが存在すれば、それで上書きする
    if character_name:
        char_config_path = os.path.join(CHARACTERS_DIR, character_name, "character_config.json")
        if os.path.exists(char_config_path):
            try:
                with open(char_config_path, "r", encoding="utf-8") as f:
                    char_config = json.load(f)

                override = char_config.get("override_settings", {})
                for key, value in override.items():
                    # 値がNoneでない項目だけを上書き
                    if value is not None:
                        effective_settings[key] = value
            except (json.JSONDecodeError, IOError) as e:
                print(f"警告: '{char_config_path}' の読み込みに失敗しました: {e}")

    return effective_settings
# ★★★ ここまで追加 ★★★
