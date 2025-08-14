# config_manager.py (v5: 後方互換性対応・最終版)

import json
import os
import constants

# --- グローバル変数 ---
# ▼▼▼ 以下の1行を新しく追加 ▼▼▼
CONFIG_GLOBAL = {}
GEMINI_API_KEYS = {}
AVAILABLE_MODELS_GLOBAL = []
DEFAULT_MODEL_GLOBAL = "gemini-2.5-pro"
NOTIFICATION_SERVICE_GLOBAL = "discord"
NOTIFICATION_WEBHOOK_URL_GLOBAL = None
PUSHOVER_CONFIG = {}
TAVILY_API_KEY = None

SUPPORTED_VOICES = {
    "zephyr": "Zephyr (明るい)", "puck": "Puck (アップビート)", "charon": "Charon (情報が豊富)",
    "kore": "Kore (しっかりした)", "fenrir": "Fenrir (興奮した)", "leda": "Leda (若々しい)",
    "orus": "Orus (しっかりした)", "aoede": "Aoede (軽快)", "callirrhoe": "Callirrhoe (のんびりした)",
    "autonoe": "Autonoe (明るい)", "enceladus": "Enceladus (息遣いの多い)", "iapetus": "Iapetus (クリア)",
    "umbriel": "Umbriel (のんびりした)", "algieba": "Algieba (スムーズ)", "despina": "Despina (スムーズ)",
    "erinome": "Erinome (クリア)", "algenib": "Algenib (しわがれた)", "rasalgethi": "Rasalgethi (情報が豊富)",
    "laomedeia": "Laomedeia (アップビート)", "achernar": "Achernar (柔らかい)", "alnilam": "Alnilam (しっかりした)",
    "schedar": "Schedar (均一)", "gacrux": "Gacrux (成人向け)", "pulcherrima": "Pulcherrima (前向き)",
    "achird": "Achird (フレンドリー)", "zubenelgenubi": "Zubenelgenubi (カジュアル)",
    "vindemiatrix": "Vindemiatrix (優しい)", "sadachbia": "Sadachbia (生き生きした)",
    "sadaltager": "Sadaltager (知識が豊富)", "sulafat": "Sulafat (温かい)",
}

initial_api_key_name_global = "default"
initial_character_global = "Default"
initial_model_global = DEFAULT_MODEL_GLOBAL
initial_send_thoughts_to_api_global = True
initial_api_history_limit_option_global = constants.DEFAULT_API_HISTORY_LIMIT_OPTION
initial_alarm_api_history_turns_global = constants.DEFAULT_ALARM_API_HISTORY_TURNS

# --- 内部ヘルパー関数 ---
def _load_config_file() -> dict:
    if os.path.exists(constants.CONFIG_FILE):
        try:
            with open(constants.CONFIG_FILE, "r", encoding="utf-8") as f:
                content = f.read()
                if not content.strip(): return {}
                return json.loads(content)
        except (json.JSONDecodeError, IOError): return {}
    return {}

def _save_config_file(config_data: dict):
    try:
        with open(constants.CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"'{constants.CONFIG_FILE}' 保存エラー: {e}")

# --- 公開APIキー管理関数 ---
def add_or_update_gemini_key(key_name: str, key_value: str):
    config = _load_config_file()
    if "gemini_api_keys" not in config or not isinstance(config.get("gemini_api_keys"), dict):
        config["gemini_api_keys"] = {}
    config["gemini_api_keys"][key_name] = key_value
    _save_config_file(config)
    load_config()

def delete_gemini_key(key_name: str):
    config = _load_config_file()
    if "gemini_api_keys" in config and isinstance(config.get("gemini_api_keys"), dict) and key_name in config["gemini_api_keys"]:
        del config["gemini_api_keys"][key_name]
        if config.get("last_api_key_name") == key_name:
            config["last_api_key_name"] = None
        _save_config_file(config)
        load_config()

def update_pushover_config(user_key: str, app_token: str):
    config = _load_config_file()
    config["pushover_user_key"] = user_key
    config["pushover_app_token"] = app_token
    _save_config_file(config)
    load_config()

def update_tavily_key(api_key: str):
    config = _load_config_file()
    config["tavily_api_key"] = api_key
    _save_config_file(config)
    load_config()

def save_config(key, value):
    config = _load_config_file()
    config[key] = value
    _save_config_file(config)
    load_config()

# --- メインの読み込み関数 (最重要修正箇所) ---
def load_config():
    global CONFIG_GLOBAL, GEMINI_API_KEYS, initial_api_key_name_global, initial_character_global, initial_model_global
    global initial_send_thoughts_to_api_global, initial_api_history_limit_option_global, initial_alarm_api_history_turns_global
    global AVAILABLE_MODELS_GLOBAL, DEFAULT_MODEL_GLOBAL, TAVILY_API_KEY
    global NOTIFICATION_SERVICE_GLOBAL, NOTIFICATION_WEBHOOK_URL_GLOBAL, PUSHOVER_CONFIG

    default_config = {
        "gemini_api_keys": {"your_key_name": "YOUR_API_KEY_HERE"},
        "available_models": ["gemini-2.5-pro"], "default_model": "gemini-2.5-pro",
        "last_character": "Default", "last_model": "gemini-2.5-pro", "last_api_key_name": None,
        "default_api_key_name": None, "last_send_thoughts_to_api": True,
        "last_api_history_limit_option": constants.DEFAULT_API_HISTORY_LIMIT_OPTION,
        "alarm_api_history_turns": constants.DEFAULT_ALARM_API_HISTORY_TURNS,
        "tavily_api_key": "", "notification_service": "discord",
        "notification_webhook_url": None, "pushover_app_token": "", "pushover_user_key": "",
        "log_archive_threshold_mb": 10,
        "log_keep_size_mb": 5,
    }

    user_config = _load_config_file()
    config = default_config.copy()
    config.update(user_config)

    # ▼▼▼ 読み込んだ設定をグローバル辞書に格納 ▼▼▼
    CONFIG_GLOBAL = config.copy()

    config_updated = False
    if "api_keys" in config and "gemini_api_keys" not in user_config:
        print("--- [情報] 古いAPIキー形式('api_keys')を検出しました。新しい形式('gemini_api_keys')に自動的に移行します。 ---")
        config["gemini_api_keys"] = config.pop("api_keys")
        config_updated = True

    GEMINI_API_KEYS = config.get("gemini_api_keys", default_config["gemini_api_keys"])
    AVAILABLE_MODELS_GLOBAL = config.get("available_models", default_config["available_models"])
    DEFAULT_MODEL_GLOBAL = config.get("default_model", default_config["default_model"])
    initial_character_global = config.get("last_character", default_config["last_character"])
    initial_model_global = config.get("last_model", default_config["last_model"])
    initial_send_thoughts_to_api_global = config.get("last_send_thoughts_to_api", default_config["last_send_thoughts_to_api"])
    initial_api_history_limit_option_global = config.get("last_api_history_limit_option", default_config["last_api_history_limit_option"])
    initial_alarm_api_history_turns_global = config.get("alarm_api_history_turns", default_config["alarm_api_history_turns"])
    TAVILY_API_KEY = config.get("tavily_api_key", default_config["tavily_api_key"])
    NOTIFICATION_SERVICE_GLOBAL = config.get("notification_service", default_config["notification_service"])
    NOTIFICATION_WEBHOOK_URL_GLOBAL = config.get("notification_webhook_url", default_config["notification_webhook_url"])
    PUSHOVER_CONFIG = {
        "user_key": config.get("pushover_user_key", default_config["pushover_user_key"]),
        "app_token": config.get("pushover_app_token", default_config["pushover_app_token"])
    }

    valid_api_keys = [k for k, v in GEMINI_API_KEYS.items() if isinstance(v, str) and v and v != "YOUR_API_KEY_HERE"]

    last_key = config.get("last_api_key_name")
    if last_key and last_key in valid_api_keys:
        initial_api_key_name_global = last_key
    elif valid_api_keys:
        initial_api_key_name_global = valid_api_keys[0]
    else:
        initial_api_key_name_global = list(GEMINI_API_KEYS.keys())[0] if GEMINI_API_KEYS else "your_key_name"

    if not os.path.exists(constants.CONFIG_FILE) or config_updated or any(key not in user_config for key in default_config):
        _save_config_file(config)


def get_effective_settings(character_name: str, **kwargs) -> dict:
    """
    キャラクターのファイル設定と、UIからのリアルタイムな設定（kwargs）をマージして、
    最終的に適用される設定値を返す。
    """
    # 1. デフォルト設定を定義
    effective_settings = {
        "model_name": DEFAULT_MODEL_GLOBAL, "voice_id": "iapetus", "voice_style_prompt": "",
        "add_timestamp": False, "send_thoughts": initial_send_thoughts_to_api_global,
        "send_notepad": True, "use_common_prompt": False,
        "send_core_memory": True, "send_scenery": True,
        "temperature": 0.8, "top_p": 0.95,
        "safety_block_threshold_harassment": "BLOCK_ONLY_HIGH",
        "safety_block_threshold_hate_speech": "BLOCK_ONLY_HIGH",
        "safety_block_threshold_sexually_explicit": "BLOCK_ONLY_HIGH",
        "safety_block_threshold_dangerous_content": "BLOCK_ONLY_HIGH"
    }

    # 2. キャラクターの保存済み設定ファイルで上書き
    char_config_path = os.path.join(constants.CHARACTERS_DIR, character_name, "character_config.json")
    if os.path.exists(char_config_path):
        try:
            with open(char_config_path, "r", encoding="utf-8") as f:
                char_config = json.load(f)
            override_settings = char_config.get("override_settings", {})
            for k, v in override_settings.items():
                if v is not None:
                    effective_settings[k] = v
        except Exception as e:
            print(f"キャラクター設定ファイル '{char_config_path}' の読み込みエラー: {e}")

    # 3. UIから渡されたリアルタイムな設定（kwargs）で、さらに上書き
    for key, value in kwargs.items():
        if value is not None:
            effective_settings[key] = value

    # 4. モデル名が空の場合のフォールバック
    if not effective_settings.get("model_name"):
        effective_settings["model_name"] = DEFAULT_MODEL_GLOBAL

    return effective_settings
