# config_manager.py の内容を、このコードで完全に置き換えてください

import json
import os
import traceback
from google.genai import types

SUPPORTED_VOICES = {
    # ... (省略) ...
    "achird": "Achird (女性、クリアで落ち着いた声)", "alcyone": "Alcyone (女性、温かくフレンドリーな声)", "callirrhoe": "Callirrhoe (女性、深く落ち着いた声)", "despina": "Despina (女性、明るくエネルギッシュな声)", "erinome": "Erinome (女性、クリアで表現力豊かな声)", "kore": "Kore (女性、明るくクリアな声)", "laomedeia": "Laomedeia (女性、温かく落ち着いた声)", "leda": "Leda (女性、クリアで明るい声)", "pulcherrima": "Pulcherrima (女性、温かく優しい声)", "sadachbia": "Sadachbia (女性、深くクリアな声)", "schedar": "Schedar (女性、温かくフレンドリーな声)", "sulafat": "Sulafat (女性、深く落ち着いた声)", "umbriel": "Umbriel (女性、クリアでプロフェッショナルな声)", "vindemiatrix": "Vindemiatrix (女性、温かく落ち着いた声)", "zephyr": "Zephyr (女性、明るくフレンドリーな声)",
    "achernar": "Achernar (男性、深く落ち着いた声)", "algenib": "Algenib (男性、クリアでエネルギッシュな声)", "algieba": "Algieba (男性、深くクリアな声)", "alnilam": "Alnilam (男性、温かくフレンドリーな声)", "aoede": "Aoede (男性、深く温かい声)", "autonoe": "Autonoe (男性、クリアで落ち着いた声)", "charon": "Charon (男性、深く信頼感のある声)", "enceladus": "Enceladus (男性、温かく落ち着いた声)", "fenrir": "Fenrir (男性、クリアで力強い声)", "gacrux": "Gacrux (男性、深く落ち着いた声)", "iapetus": "Iapetus (男性、クリアでフレンドリーな声)", "orus": "Orus (男性、深く温かい声)", "puck": "Puck (男性、明るくエネルギッシュな声)", "rasalgethi": "Rasalgethi (男性、温かく落ち着いた声)", "sadaltager": "Sadaltager (男性、クリアでプロフェッショナルな声)", "zubenelgenubi": "Zubenelgenubi (男性、深くクリアな声)",
}

CONFIG_FILE, ALARMS_FILE, CHARACTERS_DIR = "config.json", "alarms.json", "characters"
PROFILE_IMAGE_FILENAME, MEMORY_FILENAME = "profile.png", "memory.json"
API_HISTORY_LIMIT_OPTIONS = {"10": "10往復", "20": "20往復", "30": "30往復", "40": "40往復", "50": "50往復", "60": "60往復", "70": "70往復", "80": "80往復", "90": "90往復", "100": "100往復", "all": "全ログ"}
UI_HISTORY_MAX_LIMIT, DEFAULT_API_HISTORY_LIMIT_OPTION, DEFAULT_ALARM_API_HISTORY_TURNS = 200, "all", 10
SAFETY_CONFIG = [
    {"category": types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, "threshold": types.HarmBlockThreshold.BLOCK_NONE},
    {"category": types.HarmCategory.HARM_CATEGORY_HARASSMENT, "threshold": types.HarmBlockThreshold.BLOCK_NONE},
    {"category": types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, "threshold": types.HarmBlockThreshold.BLOCK_NONE},
    {"category": types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, "threshold": types.HarmBlockThreshold.BLOCK_NONE},
]

initial_character_global, initial_model_global, initial_api_key_name_global = None, None, None
initial_send_thoughts_to_api_global = True
initial_api_history_limit_option_global = DEFAULT_API_HISTORY_LIMIT_OPTION
initial_alarm_api_history_turns_global = DEFAULT_ALARM_API_HISTORY_TURNS
initial_tavily_api_key_global = None
API_KEYS, TAVILY_API_KEY, AVAILABLE_MODELS_GLOBAL, DEFAULT_MODEL_GLOBAL = {}, "", [], None
NOTIFICATION_SERVICE_GLOBAL, NOTIFICATION_WEBHOOK_URL_GLOBAL = "discord", None
PUSHOVER_APP_TOKEN_GLOBAL, PUSHOVER_USER_KEY_GLOBAL = None, None

def load_config():
    global API_KEYS, initial_api_key_name_global, initial_character_global, initial_model_global
    global initial_send_thoughts_to_api_global, initial_api_history_limit_option_global, initial_alarm_api_history_turns_global
    global AVAILABLE_MODELS_GLOBAL, DEFAULT_MODEL_GLOBAL, TAVILY_API_KEY
    global NOTIFICATION_SERVICE_GLOBAL, NOTIFICATION_WEBHOOK_URL_GLOBAL, PUSHOVER_APP_TOKEN_GLOBAL, PUSHOVER_USER_KEY_GLOBAL

    default_config = {
        "api_keys": {"your_key_name_1": "YOUR_API_KEY_HERE"}, "available_models": ["gemini-2.5-pro"], "default_model": "gemini-2.5-pro",
        "default_api_key_name": "your_key_name_1", "last_character": "Default", "last_model": "gemini-2.5-pro",
        "last_api_key_name": "your_key_name_1", "last_send_thoughts_to_api": True,
        "last_api_history_limit_option": DEFAULT_API_HISTORY_LIMIT_OPTION, "alarm_api_history_turns": DEFAULT_ALARM_API_HISTORY_TURNS,
        "tavily_api_key": "YOUR_TAVILY_API_KEY_HERE", "notification_service": "discord", "notification_webhook_url": None,
        "pushover_app_token": None, "pushover_user_key": None
    }
    config = default_config
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f: config = json.load(f)
        except Exception as e: print(f"'{CONFIG_FILE}' 読込エラー: {e}")

    API_KEYS = config.get("api_keys", {})
    AVAILABLE_MODELS_GLOBAL = config.get("available_models", ["gemini-2.5-pro"])
    DEFAULT_MODEL_GLOBAL = config.get("default_model", "gemini-2.5-pro")

    # ▼▼▼ 修正箇所 ▼▼▼
    # get_character_list()の呼び出しと、それに関連する検証ロジックを削除
    initial_api_key_name_global = config.get("last_api_key_name") or config.get("default_api_key_name") or (list(API_KEYS.keys())[0] if API_KEYS else None)
    initial_character_global = config.get("last_character", "Default")
    # ▲▲▲ 修正ここまで ▲▲▲

    initial_model_global = config.get("last_model", DEFAULT_MODEL_GLOBAL)
    initial_send_thoughts_to_api_global = config.get("last_send_thoughts_to_api", True)
    initial_api_history_limit_option_global = config.get("last_api_history_limit_option", DEFAULT_API_HISTORY_LIMIT_OPTION)
    initial_alarm_api_history_turns_global = config.get("alarm_api_history_turns", DEFAULT_ALARM_API_HISTORY_TURNS)
    TAVILY_API_KEY = config.get("tavily_api_key")
    NOTIFICATION_SERVICE_GLOBAL = config.get("notification_service", "discord")
    NOTIFICATION_WEBHOOK_URL_GLOBAL = config.get("notification_webhook_url")
    PUSHOVER_APP_TOKEN_GLOBAL = config.get("pushover_app_token")
    PUSHOVER_USER_KEY_GLOBAL = config.get("pushover_user_key")

    if 'add_timestamp' in config:
        del config['add_timestamp']
        save_config(None, config, is_full_config=True)
        print(f"情報: 古い共通設定 'add_timestamp' を '{CONFIG_FILE}' から削除しました。")

    needs_update = any(key not in config for key in default_config if key != 'add_timestamp')
    if needs_update:
        for key, value in default_config.items():
            if key != 'add_timestamp': config.setdefault(key, value)
        save_config(None, config, is_full_config=True)

def save_config(key, value, is_full_config=False):
    try:
        config_to_save = value if is_full_config else {}
        if not is_full_config:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r", encoding="utf-8") as f: config_to_save = json.load(f)
            config_to_save[key] = value
        with open(CONFIG_FILE, "w", encoding="utf-8") as f: json.dump(config_to_save, f, indent=2, ensure_ascii=False)
    except Exception as e: print(f"設定保存エラー ({key}): {e}")

def get_effective_settings(character_name: str) -> dict:
    effective_settings = {
        "model_name": initial_model_global, "api_key_name": initial_api_key_name_global,
        "add_timestamp": False, # ★★★ 追加 ★★★
        "send_thoughts": initial_send_thoughts_to_api_global, "send_notepad": True,
        "use_common_prompt": True, "send_core_memory": True, "send_scenery": True,
        "voice_id": "vindemiatrix", "voice_style_prompt": ""
    }
    if character_name:
        char_config_path = os.path.join(CHARACTERS_DIR, character_name, "character_config.json")
        if os.path.exists(char_config_path):
            try:
                with open(char_config_path, "r", encoding="utf-8") as f:
                    char_config = json.load(f)
                override = char_config.get("override_settings", {})
                for key, value in override.items():
                    if value is not None: effective_settings[key] = value
            except (json.JSONDecodeError, IOError) as e:
                print(f"警告: '{char_config_path}' の読込失敗: {e}")
    return effective_settings
# ★★★ 変更箇所ここまで ★★★
