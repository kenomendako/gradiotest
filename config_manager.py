# config_manager.py (v7: The True Final Covenant - 真・最終版)

import json
import os
import time
from typing import Any, List, Dict
import time 
import shutil 
import datetime 

import constants

# --- グローバル変数 ---
CONFIG_GLOBAL = {}
GEMINI_API_KEYS = {}
AVAILABLE_MODELS_GLOBAL = []
DEFAULT_MODEL_GLOBAL = "gemini-2.5-pro"
NOTIFICATION_SERVICE_GLOBAL = "discord"
NOTIFICATION_WEBHOOK_URL_GLOBAL = None
PUSHOVER_CONFIG = {}

SUPPORTED_VOICES = {
    "zephyr": "Zephyr (明るい)", "puck": "Puck (アップビート)", "charon": "Charon (情報が豊富)",
    "kore": "Kore (しっかりした)", "fenrir": "Fenrir (興奮した)", "leda": "Leda (若々しい)",
    "orus": "Orus (しっかりした)", "aoede": "Aoede (軽快)", "callirrhoe": "Callirrhoe (のんびりした)",
    "autonoe": "Autonoe (明るい)", "enceladus": "Enceladus (息遣いの多い)", "iapetus": "Iapetus (クリア)",
    "umbriel": "Umbriel (のんびりした)", "algieba": "Algieba (スムーズ)", "despina": "Despina (スムーズ)",
    "erinome": "Erinome (クリア)", "algenib": "Algenib (しわがれた)", "rasalgethi": "Rasalgethi (情報が豊富)",
    "laomedeia": "Laomedeia (アップビート)", "achernar": "Achernar (柔らかい)", "alnilam": "Alnilam (しっかりした)",
    "schedar": "Schedar (均一)", "gacrux": "Gacrux (成熟したt)", "pulcherrima": "Pulcherrima (前向き)",
    "achird": "Achird (フレンドリー)", "zubenelgenubi": "Zubenelgenubi (カジュアル)",
    "vindemiatrix": "Vindemiatrix (優しい)", "sadachbia": "Sadachbia (生き生きした)",
    "sadaltager": "Sadaltager (知識が豊富)", "sulafat": "Sulafat (温かい)",
}

# --- 起動時の初期値を保持するグローバル変数 ---
initial_api_key_name_global = "default"
initial_room_global = "Default"
initial_model_global = DEFAULT_MODEL_GLOBAL
initial_send_thoughts_to_api_global = True
initial_api_history_limit_option_global = constants.DEFAULT_API_HISTORY_LIMIT_OPTION
initial_alarm_api_history_turns_global = constants.DEFAULT_ALARM_API_HISTORY_TURNS
initial_streaming_speed_global = 0.01


# --- [v8] 自己修復機能付きコンフィグ管理 ---

def _create_config_backup():
    """config.jsonのバックアップを作成し、ローテーションする。"""
    backup_dir = os.path.join("backups", "config")
    os.makedirs(backup_dir, exist_ok=True)

    if not os.path.exists(constants.CONFIG_FILE):
        return # バックアップ対象がない場合は何もしない

    try:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"config_{timestamp}.json.bak"
        backup_path = os.path.join(backup_dir, backup_filename)
        shutil.copy2(constants.CONFIG_FILE, backup_path)

        # ローテーション処理
        rotation_count = CONFIG_GLOBAL.get("backup_rotation_count", 10)
        existing_backups = sorted(
            [f for f in os.listdir(backup_dir) if f.endswith(".bak")],
            key=lambda f: os.path.getmtime(os.path.join(backup_dir, f))
        )
        if len(existing_backups) > rotation_count:
            for f_del in existing_backups[:len(existing_backups) - rotation_count]:
                os.remove(os.path.join(backup_dir, f_del))

    except Exception as e:
        print(f"警告: config.jsonのバックアップ作成に失敗しました: {e}")

def _restore_from_backup() -> bool:
    """最も新しいバックアップからconfig.jsonを復元する。"""
    backup_dir = os.path.join("backups", "config")
    if not os.path.isdir(backup_dir):
        return False

    try:
        backups = sorted(
            [f for f in os.listdir(backup_dir) if f.endswith(".bak")],
            key=lambda f: os.path.getmtime(os.path.join(backup_dir, f)),
            reverse=True # 新しいものが先頭に来るように
        )
        if not backups:
            return False

        latest_backup = os.path.join(backup_dir, backups[0])
        print(f"--- [自己修復] 破損したconfig.jsonをバックアップ '{backups[0]}' から復元します ---")
        shutil.copy2(latest_backup, constants.CONFIG_FILE)
        return True

    except Exception as e:
        print(f"!!! エラー: バックアップからの復元に失敗しました: {e}")
        return False

def load_config_file() -> dict:
    """
    config.jsonを安全に読み込む。ファイルが破損している場合はバックアップから自動復元を試みる。
    """
    if os.path.exists(constants.CONFIG_FILE):
        try:
            with open(constants.CONFIG_FILE, "r", encoding="utf-8") as f:
                content = f.read()
            if not content.strip(): # 空ファイルの場合
                raise json.JSONDecodeError("File is empty", "", 0)
            return json.loads(content)
        except (json.JSONDecodeError, IOError):
            print("警告: config.jsonが空または破損しています。バックアップからの復元を試みます...")
            if _restore_from_backup():
                # 復元に成功したら、再度読み込みを試みる
                try:
                    with open(constants.CONFIG_FILE, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception as e:
                    print(f"!!! エラー: 復元後のconfig.jsonの読み込みにも失敗しました: {e}")
    # ファイルが存在しない、または復元にも失敗した場合
    return {}


def _save_config_file(config_data: dict):
    """
    設定データを一時ファイルに書き込んでからリネームする、堅牢な保存処理。
    """
    # ステップ1: まず現在の設定をバックアップ
    _create_config_backup()

    # ステップ2: アトミックな書き込み処理
    temp_file_path = constants.CONFIG_FILE + ".tmp"
    max_retries = 5
    retry_delay = 0.1

    for attempt in range(max_retries):
        try:
            with open(temp_file_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
            os.replace(temp_file_path, constants.CONFIG_FILE)
            return
        except PermissionError as e:
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                print(f"'{constants.CONFIG_FILE}' 保存エラー: {e}")
                if os.path.exists(temp_file_path):
                    try:
                        os.remove(temp_file_path)
                    except OSError:
                        pass
        except Exception as e:
            print(f"'{constants.CONFIG_FILE}' 保存エラー: {e}")
            if os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except OSError:
                    pass
            return


def save_config_if_changed(key: str, value: Any) -> bool:
    """
    現在の設定値と比較し、変更があった場合のみconfig.jsonに安全に保存する。
    変更があった場合は True を、変更がなかった場合は False を返す。
    """
    config = load_config_file()
    if config.get(key) == value:
        return False  # 変更なし

    config[key] = value
    _save_config_file(config)
    return True

# --- 公開APIキー管理関数 ---
def add_or_update_gemini_key(key_name: str, key_value: str):
    global GEMINI_API_KEYS
    config = load_config_file()
    if "gemini_api_keys" not in config or not isinstance(config.get("gemini_api_keys"), dict):
        config["gemini_api_keys"] = {}

    existing_keys = config["gemini_api_keys"]
    if len(existing_keys) == 1 and "your_key_name" in existing_keys:
        del existing_keys["your_key_name"]

    config["gemini_api_keys"][key_name] = key_value
    _save_config_file(config)
    GEMINI_API_KEYS = config["gemini_api_keys"]

def delete_gemini_key(key_name: str):
    global GEMINI_API_KEYS
    config = load_config_file()
    if "gemini_api_keys" in config and isinstance(config.get("gemini_api_keys"), dict) and key_name in config["gemini_api_keys"]:
        del config["gemini_api_keys"][key_name]

        if not config["gemini_api_keys"]:
            config["gemini_api_keys"] = {"your_key_name": "YOUR_API_KEY_HERE"}

        # paid_api_key_names が存在すれば、削除する
        if "paid_api_key_names" in config and key_name in config["paid_api_key_names"]:
            try:
                config["paid_api_key_names"].remove(key_name)
            except ValueError:
                pass

        if config.get("last_api_key_name") == key_name:
            config["last_api_key_name"] = None
        _save_config_file(config)
        GEMINI_API_KEYS = config.get("gemini_api_keys", {})

def update_pushover_config(user_key: str, app_token: str):
    config = load_config_file()
    config["pushover_user_key"] = user_key
    config["pushover_app_token"] = app_token
    _save_config_file(config)


# --- Theme Management Helpers ---

_file_based_themes_cache = {}

def load_file_based_themes() -> Dict[str, "gr.themes.Base"]:
    """
    `themes/` ディレクトリをスキャンし、有効なテーマファイルを読み込んでキャッシュする。
    """
    global _file_based_themes_cache
    if _file_based_themes_cache:
        return _file_based_themes_cache

    from pathlib import Path
    import importlib.util

    themes_dir = Path("themes")
    if not themes_dir.is_dir():
        return {}

    loaded_themes = {}
    for file_path in themes_dir.glob("*.py"):
        theme_name = file_path.stem
        try:
            spec = importlib.util.spec_from_file_location(theme_name, str(file_path))
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                if hasattr(module, "load") and callable(module.load):
                    theme_object = module.load()
                    import gradio as gr
                    if isinstance(theme_object, gr.themes.Base):
                        loaded_themes[theme_name] = theme_object
        except Exception as e:
            print(f"警告: テーマファイル '{file_path.name}' の読み込みに失敗しました: {e}")

    _file_based_themes_cache = loaded_themes
    return loaded_themes

def get_all_themes() -> Dict[str, str]:
    """UIのドロップダウン用に、すべての利用可能なテーマ名とソースの辞書を返す。"""
    themes = {}
    
    # 1. ファイルベースのテーマ
    file_themes = load_file_based_themes()
    for name in sorted(file_themes.keys()):
        themes[name] = "file"
        
    # 2. JSONベースのカスタムテーマ
    custom_themes_from_json = CONFIG_GLOBAL.get("theme_settings", {}).get("custom_themes", {})
    for name in sorted(custom_themes_from_json.keys()):
        if name not in themes: # ファイルテーマを優先
            themes[name] = "json"
            
    # 3. プリセットテーマ
    for name in ["Soft", "Default", "Monochrome", "Glass"]:
        if name not in themes:
            themes[name] = "preset"
            
    return themes

def get_theme_object(theme_name: str):
    """指定された名前のテーマオブジェクトを取得する。"""
    import gradio as gr
    # 1. ファイルベースのテーマから検索
    file_themes = load_file_based_themes()
    if theme_name in file_themes:
        return file_themes[theme_name]

    # 2. JSONベースのカスタムテーマから検索・構築
    custom_themes_from_json = CONFIG_GLOBAL.get("theme_settings", {}).get("custom_themes", {})
    if theme_name in custom_themes_from_json:
        params = custom_themes_from_json[theme_name]
        try:
            default_arg_keys = ["primary_hue", "secondary_hue", "neutral_hue", "text_size", "spacing_size", "radius_size", "font", "font_mono"]
            default_args = {k: v for k, v in params.items() if k in default_arg_keys}
            set_args = {k: v for k, v in params.items() if k not in default_args}

            if 'font' in default_args and isinstance(default_args['font'], list):
                 default_args['font'] = [gr.themes.GoogleFont(name) if isinstance(name, str) and ' ' in name else name for name in default_args['font']]

            theme_obj = gr.themes.Default(**default_args)
            if set_args:
                theme_obj = theme_obj.set(**set_args)
            return theme_obj
        except Exception as e:
            print(f"警告: カスタムテーマ '{theme_name}' の構築に失敗しました: {e}")

    # 3. プリセットテーマから検索
    preset_map = {"Soft": gr.themes.Soft, "Default": gr.themes.Default, "Monochrome": gr.themes.Monochrome, "Glass": gr.themes.Glass}
    if theme_name in preset_map:
        return preset_map[theme_name]()

    # 4. フォールバック
    print(f"警告: テーマ '{theme_name}' が見つかりません。デフォルトのSoftテーマを使用します。")
    return gr.themes.Soft()


# --- メインの読み込み関数 (真・最終版) ---
def load_config():
    global CONFIG_GLOBAL, GEMINI_API_KEYS, initial_api_key_name_global, initial_room_global, initial_model_global
    global initial_send_thoughts_to_api_global, initial_api_history_limit_option_global, initial_alarm_api_history_turns_global
    global AVAILABLE_MODELS_GLOBAL, DEFAULT_MODEL_GLOBAL, initial_streaming_speed_global
    global NOTIFICATION_SERVICE_GLOBAL, NOTIFICATION_WEBHOOK_URL_GLOBAL, PUSHOVER_CONFIG

    # ステップ1：全てのキーを含む、理想的なデフォルト設定を定義
    default_config = {
        "gemini_api_keys": {"your_key_name": "YOUR_API_KEY_HERE"},
        "paid_api_key_names": [],
        "available_models": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"],
        "default_model": "gemini-2.5-pro",
        "image_generation_mode": "new", 
        "search_provider": "google",
        "last_room": "Default",
        "last_model": "gemini-2.5-pro",
        "last_api_key_name": None,
        "last_send_thoughts_to_api": True,
        "last_api_history_limit_option": constants.DEFAULT_API_HISTORY_LIMIT_OPTION,
        "alarm_api_history_turns": constants.DEFAULT_ALARM_API_HISTORY_TURNS,
        "notification_service": "discord",
        "notification_webhook_url": None,
        "pushover_app_token": "",
        "pushover_user_key": "",
        "log_archive_threshold_mb": 10,
        "log_keep_size_mb": 5,
        "backup_rotation_count": 10,
        "theme_settings": {
            "active_theme": "nexus_ark_theme", # デフォルトテーマをファイル名に変更
            "custom_themes": {} # config.jsonで管理するカスタムテーマは最初は空
        }
    }

    # ステップ2：ユーザーの設定ファイルを読み込む
    user_config = load_config_file()

    # ステップ3：【賢いマージ】テーマ設定をディープマージする
    default_theme_settings = default_config["theme_settings"]
    user_theme_settings = user_config.get("theme_settings", {})
    # ユーザーのカスタムテーマのみを尊重する（ファイルベースのテーマはjsonにマージしない）
    final_theme_settings = {
        "active_theme": user_theme_settings.get("active_theme", default_theme_settings["active_theme"]),
        "custom_themes": user_theme_settings.get("custom_themes", {})
    }

    # ステップ4：【賢いマージ】available_modelsを統合する
    default_models_set = set(default_config["available_models"])
    user_models_set = set(user_config.get("available_models", []))
    merged_models = sorted(list(default_models_set | user_models_set))

    # ステップ5：ユーザー設定を優先しつつ、不足キーを補完
    config = default_config.copy()
    config.update(user_config)
    # 統合したモデルリストとテーマ設定で、最終的な設定を上書き
    config["available_models"] = merged_models
    config["theme_settings"] = final_theme_settings

    # ステップ6：不要なキーをクリーンアップ
    keys_to_remove = ["memos_config", "api_keys", "default_api_key_name"]
    config_keys_changed = False
    for key in keys_to_remove:
        if key in config:
            config.pop(key)
            config_keys_changed = True

    # ステップ7：キー構成の変化、またはモデルリスト/テーマ設定の変化があった場合のみファイルを更新
    if (config_keys_changed or
        set(user_config.get("available_models", [])) != set(config["available_models"]) or
        user_config.get("theme_settings") != config["theme_settings"] or # テーマ設定の変更もチェック
        not os.path.exists(constants.CONFIG_FILE)):
        print("--- [情報] 設定ファイルに新しいキーやモデル、テーマを追加、または不要なキーを削除しました。config.jsonを更新します。 ---")
        _save_config_file(config)

    # ステップ8：メモリ上の最終的な設定を、グローバル変数に反映
    CONFIG_GLOBAL = config.copy()

    GEMINI_API_KEYS = config.get("gemini_api_keys", {})
    if not GEMINI_API_KEYS:
        GEMINI_API_KEYS = {"your_key_name": "YOUR_API_KEY_HERE"}

    AVAILABLE_MODELS_GLOBAL = config.get("available_models")
    DEFAULT_MODEL_GLOBAL = config.get("default_model")
    initial_room_global = config.get("last_room")
    initial_model_global = config.get("last_model")
    initial_send_thoughts_to_api_global = config.get("last_send_thoughts_to_api")
    initial_api_history_limit_option_global = config.get("last_api_history_limit_option")
    initial_alarm_api_history_turns_global = config.get("alarm_api_history_turns")
    initial_streaming_speed_global = config.get("last_streaming_speed")
    NOTIFICATION_SERVICE_GLOBAL = config.get("notification_service")
    NOTIFICATION_WEBHOOK_URL_GLOBAL = config.get("notification_webhook_url")
    PUSHOVER_CONFIG = {
        "user_key": config.get("pushover_user_key"),
        "app_token": config.get("pushover_app_token")
    }

    valid_api_keys = [k for k, v in GEMINI_API_KEYS.items() if isinstance(v, str) and v and v != "YOUR_API_KEY_HERE"]
    last_key = config.get("last_api_key_name")
    if last_key and last_key in valid_api_keys:
        initial_api_key_name_global = last_key
    elif valid_api_keys:
        initial_api_key_name_global = valid_api_keys[0]
    else:
        initial_api_key_name_global = list(GEMINI_API_KEYS.keys())[0] if GEMINI_API_KEYS else "your_key_name"


def get_effective_settings(room_name: str, **kwargs) -> dict:
    """
    ルームのファイル設定と、UIからのリアルタイムな設定（kwargs）をマージして、
    最終的に適用される設定値を返す。
    """
    effective_settings = {
        "model_name": DEFAULT_MODEL_GLOBAL, "voice_id": "iapetus", "voice_style_prompt": "",
        "add_timestamp": True, "send_thoughts": initial_send_thoughts_to_api_global,
        "send_notepad": True, "use_common_prompt": True,
        "send_core_memory": True,
        "enable_scenery_system": True, # この行を追加
        "send_scenery": True,
        "send_current_time": True,
        "auto_memory_enabled": False,
        "enable_typewriter_effect": True,
        "streaming_speed": 0.01,
        "temperature": 0.8, "top_p": 0.95,
        "safety_block_threshold_harassment": "BLOCK_ONLY_HIGH",
        "safety_block_threshold_hate_speech": "BLOCK_ONLY_HIGH",
        "safety_block_threshold_sexually_explicit": "BLOCK_ONLY_HIGH",
        "safety_block_threshold_dangerous_content": "BLOCK_ONLY_HIGH"
    }
    
    room_config_path = os.path.join(constants.ROOMS_DIR, room_name, "room_config.json")
    if os.path.exists(room_config_path):
        try:
            with open(room_config_path, "r", encoding="utf-8") as f:
                room_config = json.load(f)
            override_settings = room_config.get("override_settings", {})
            for k, v in override_settings.items():
                # model_name はここでは読み込まない
                if v is not None and k != "model_name":
                    effective_settings[k] = v
        except Exception as e:
            print(f"ルーム設定ファイル '{room_config_path}' の読み込みエラー: {e}")

    for key, value in kwargs.items():
        # "global_model_from_ui" はモデル決定ロジックで使うので、ここでは除外
        if key not in ["global_model_from_ui"] and value is not None:
            effective_settings[key] = value

    # --- モデル選択の最終決定ロジック ---
    global_model_from_ui = kwargs.get("global_model_from_ui")

    # UIからの指定があればそれを使い、なければ共通のデフォルトを使う
    final_model_name = global_model_from_ui or DEFAULT_MODEL_GLOBAL
    effective_settings["model_name"] = final_model_name

    # 念の為のフォールバック
    if not effective_settings.get("model_name"):
        effective_settings["model_name"] = DEFAULT_MODEL_GLOBAL

    return effective_settings

from typing import Tuple

def get_api_key_choices_for_ui() -> List[Tuple[str, str]]:
    """UI用の選択肢リストを (表示名, 値) のタプルで返す。表示名には Paid ラベルを付与する。"""
    paid_key_names = CONFIG_GLOBAL.get("paid_api_key_names", []) if isinstance(CONFIG_GLOBAL, dict) else []
    choices: List[Tuple[str, str]] = []
    for key_name in sorted(GEMINI_API_KEYS.keys()):
        display = f"{key_name} (Paid)" if key_name in paid_key_names else key_name
        choices.append((display, key_name))
    return choices

def load_redaction_rules() -> List[Dict[str, str]]:
    """redaction_rules.jsonから置換ルールを読み込む。"""
    if os.path.exists(constants.REDACTION_RULES_FILE):
        try:
            with open(constants.REDACTION_RULES_FILE, "r", encoding="utf-8") as f:
                content = f.read()
                if not content.strip(): return []
                rules = json.loads(content)
                if isinstance(rules, list) and all(isinstance(r, dict) and "find" in r and "replace" in r for r in rules):
                    return rules
        except (json.JSONDecodeError, IOError):
            print(f"警告: {constants.REDACTION_RULES_FILE} の読み込みに失敗しました。")
    return []

def save_redaction_rules(rules: List[Dict[str, str]]):
    """置換ルールをredaction_rules.jsonに保存する。"""
    try:
        with open(constants.REDACTION_RULES_FILE, "w", encoding="utf-8") as f:
            json.dump(rules, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"エラー: {constants.REDACTION_RULES_FILE} の保存に失敗しました: {e}")

def save_theme_settings(active_theme: str, custom_themes: Dict):
    """
    アクティブなテーマ名とカスタムテーマの定義をconfig.jsonに保存する。
    """
    config = load_config_file()
    if "theme_settings" not in config:
        config["theme_settings"] = {}
    config["theme_settings"]["active_theme"] = active_theme
    config["theme_settings"]["custom_themes"] = custom_themes
    _save_config_file(config)

from typing import Optional

def get_latest_api_key_name_from_config() -> Optional[str]:
    """
    config.jsonを直接読み込み、最後に選択された有効なAPIキー名を返す。
    UIの状態に依存しないため、バックグラウンドスレッドから安全に呼び出せる。
    """
    config = load_config_file()
    last_key_name = config.get("last_api_key_name")

    # 有効な（値が設定されている）APIキーのリストを取得
    api_keys_dict = config.get("gemini_api_keys", {})
    valid_keys = [
        k for k, v in api_keys_dict.items()
        if v and isinstance(v, str) and not v.startswith("YOUR_API_KEY")
    ]

    # 最後に使ったキーが今も有効なら、それを返す
    if last_key_name and last_key_name in valid_keys:
        return last_key_name

    # そうでなければ、有効なキーリストの最初のものを返す
    if valid_keys:
        return valid_keys[0]

    # 有効なキーが一つもなければ、Noneを返す
    return None


def has_valid_api_key() -> bool:
    """
    設定ファイルに、有効な（プレースホルダではない）Gemini APIキーが一つでも存在するかどうかを返す。
    """
    if not GEMINI_API_KEYS:
        return False
    for key, value in GEMINI_API_KEYS.items():
        if value and isinstance(value, str) and value != "YOUR_API_KEY_HERE":
            return True
    return False

def get_current_global_model() -> str:
    """
    config.jsonから、現在ユーザーが共通設定で選択している
    有効なグローバルモデル名を返す。
    """
    # 常に最新の設定をファイルから読み込む
    config = load_config_file()
    
    # last_modelキーが存在し、かつ利用可能モデルリストに含まれていればそれを優先
    last_model = config.get("last_model")
    available_models = config.get("available_models", [])
    if last_model and last_model in available_models:
        return last_model
        
    # それ以外の場合は、default_modelキーを返す
    return config.get("default_model", DEFAULT_MODEL_GLOBAL)