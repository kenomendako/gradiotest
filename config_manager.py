# config_manager.py (最終確定版)

import json
import os
import constants

# --- グローバル変数 ---
GEMINI_API_KEYS = {} # ★ API_KEYS から GEMINI_API_KEYS に変更
AVAILABLE_MODELS_GLOBAL = []
DEFAULT_MODEL_GLOBAL = "gemini-2.5-pro"
# ★ TAVILY_API_KEY は load_config で設定されるので、ここでの定義は不要

# ▼▼▼ 新しいグローバル変数を追加 ▼▼▼
NOTIFICATION_SERVICE_GLOBAL = "discord"
NOTIFICATION_WEBHOOK_URL_GLOBAL = None
PUSHOVER_CONFIG = {} # ★ pushover_app_token と user_key をここにまとめる
TAVILY_API_KEY = None # ★ Tavilyキーもここに明示的に定義

SUPPORTED_VOICES = {
    "zephyr": "Zephyr (明るい)",
    "puck": "Puck (アップビート)",
    "charon": "Charon (情報が豊富)",
    "kore": "Kore (しっかりした)",
    "fenrir": "Fenrir (興奮した)",
    "leda": "Leda (若々しい)",
    "orus": "Orus (しっかりした)",
    "aoede": "Aoede (軽快)",
    "callirrhoe": "Callirrhoe (のんびりした)",
    "autonoe": "Autonoe (明るい)",
    "enceladus": "Enceladus (息遣いの多い)",
    "iapetus": "Iapetus (クリア)",
    "umbriel": "Umbriel (のんびりした)",
    "algieba": "Algieba (スムーズ)",
    "despina": "Despina (スムーズ)",
    "erinome": "Erinome (クリア)",
    "algenib": "Algenib (しわがれた)",
    "rasalgethi": "Rasalgethi (情報が豊富)",
    "laomedeia": "Laomedeia (アップビート)",
    "achernar": "Achernar (柔らかい)",
    "alnilam": "Alnilam (しっかりした)",
    "schedar": "Schedar (均一)",
    "gacrux": "Gacrux (成人向け)",
    "pulcherrima": "Pulcherrima (前向き)",
    "achird": "Achird (フレンドリー)",
    "zubenelgenubi": "Zubenelgenubi (カジュアル)",
    "vindemiatrix": "Vindemiatrix (優しい)",
    "sadachbia": "Sadachbia (生き生きした)",
    "sadaltager": "Sadaltager (知識が豊富)",
    "sulafat": "Sulafat (温かい)",
}

initial_api_key_name_global = "default"
initial_character_global = "Default"
initial_model_global = DEFAULT_MODEL_GLOBAL
initial_send_thoughts_to_api_global = True
initial_api_history_limit_option_global = constants.DEFAULT_API_HISTORY_LIMIT_OPTION
initial_alarm_api_history_turns_global = constants.DEFAULT_ALARM_API_HISTORY_TURNS

def load_config():
    # (グローバル変数の宣言部分を、上記に合わせて修正)
    global GEMINI_API_KEYS, initial_api_key_name_global, initial_character_global, initial_model_global
    global initial_send_thoughts_to_api_global, initial_api_history_limit_option_global, initial_alarm_api_history_turns_global
    global AVAILABLE_MODELS_GLOBAL, DEFAULT_MODEL_GLOBAL, TAVILY_API_KEY
    global NOTIFICATION_SERVICE_GLOBAL, NOTIFICATION_WEBHOOK_URL_GLOBAL, PUSHOVER_CONFIG

    # (default_config のキー名を "api_keys" から "gemini_api_keys" に変更)
    default_config = {
        "gemini_api_keys": {"your_key_name_1": "YOUR_API_KEY_HERE"}, "available_models": ["gemini-2.5-pro"], "default_model": "gemini-2.5-pro",
        "default_api_key_name": "your_key_name_1", "last_character": "Default", "last_model": "gemini-2.5-pro",
        "last_api_key_name": "your_key_name_1", "last_send_thoughts_to_api": True,
        "last_api_history_limit_option": constants.DEFAULT_API_HISTORY_LIMIT_OPTION, "alarm_api_history_turns": constants.DEFAULT_ALARM_API_HISTORY_TURNS,
        "tavily_api_key": "YOUR_TAVILY_API_KEY_HERE", "notification_service": "discord", "notification_webhook_url": None,
        "pushover_app_token": "", "pushover_user_key": ""
    }

    config = _load_config_file()
    # デフォルトを先に適用し、既存の設定で上書きする
    config_with_defaults = default_config.copy()
    config_with_defaults.update(config)
    config = config_with_defaults

    # --- Gemini APIキーの読み込み ---
    GEMINI_API_KEYS = config.get("gemini_api_keys") # ★ getのキー名を変更
    valid_api_keys = list(GEMINI_API_KEYS.keys()) if isinstance(GEMINI_API_KEYS, dict) else []

    if not valid_api_keys or "YOUR_API_KEY_HERE" in GEMINI_API_KEYS.values():
        print("警告: config.jsonに有効なGemini APIキーが設定されていません。")
        initial_api_key_name_global = config.get("default_api_key_name")
    else:
        last_key = config.get("last_api_key_name")
        if last_key and last_key in valid_api_keys:
            initial_api_key_name_global = last_key
        else:
            default_key = config.get("default_api_key_name")
            if default_key and default_key in valid_api_keys:
                initial_api_key_name_global = default_key
            else:
                initial_api_key_name_global = valid_api_keys[0]

    # --- Pushover設定の読み込み ---
    PUSHOVER_CONFIG = {
        "user_key": config.get("pushover_user_key"),
        "app_token": config.get("pushover_app_token")
    }

    # --- その他の設定読み込み（変更なし） ---
    AVAILABLE_MODELS_GLOBAL = config.get("available_models")
    DEFAULT_MODEL_GLOBAL = config.get("default_model")
    initial_character_global = config.get("last_character")
    # ... (以降の既存の読み込み処理はそのまま)
    initial_model_global = config.get("last_model")
    initial_send_thoughts_to_api_global = config.get("last_send_thoughts_to_api")
    initial_api_history_limit_option_global = config.get("last_api_history_limit_option")
    initial_alarm_api_history_turns_global = config.get("alarm_api_history_turns")
    TAVILY_API_KEY = config.get("tavily_api_key")
    NOTIFICATION_SERVICE_GLOBAL = config.get("notification_service")
    NOTIFICATION_WEBHOOK_URL_GLOBAL = config.get("notification_webhook_url")

    _save_config_file(config)


def add_or_update_gemini_key(key_name: str, key_value: str):
    """GeminiのAPIキーをconfig.jsonに追加または更新する"""
    config = _load_config_file()
    if "gemini_api_keys" not in config:
        config["gemini_api_keys"] = {}
    config["gemini_api_keys"][key_name] = key_value
    _save_config_file(config)
    load_config() # グローバル変数を再読み込み

def delete_gemini_key(key_name: str):
    """GeminiのAPIキーをconfig.jsonから削除する"""
    config = _load_config_file()
    if "gemini_api_keys" in config and key_name in config["gemini_api_keys"]:
        del config["gemini_api_keys"][key_name]
        _save_config_file(config)
        load_config()

def update_pushover_config(user_key: str, app_token: str):
    """Pushoverの設定をconfig.jsonに保存する"""
    config = _load_config_file()
    config["pushover_user_key"] = user_key
    config["pushover_app_token"] = app_token
    _save_config_file(config)
    load_config()

def update_tavily_key(api_key: str):
    """TavilyのAPIキーをconfig.jsonに保存する"""
    config = _load_config_file()
    config["tavily_api_key"] = api_key
    _save_config_file(config)
    load_config()

# 既存のload/saveを補助する内部関数
def _load_config_file() -> dict:
    if os.path.exists(constants.CONFIG_FILE):
        try:
            with open(constants.CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}

def _save_config_file(config_data: dict):
    with open(constants.CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2, ensure_ascii=False)


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
        "voice_id": "iapetus", # ★ "nova" から "iapetus" に変更
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
