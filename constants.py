# constants.py
# アプリケーション全体で共有される定数を定義するファイル

# --- アプリケーション情報 ---
APP_VERSION = "v0.1.0"

import os

# --- ディレクトリとファイル名 ---
ROOMS_DIR = "characters"
ASSETS_DIR = "assets"
SAMPLE_PERSONA_DIR = os.path.join(ASSETS_DIR, "sample_persona")
AVATAR_DIR = "avatar"  # キャラクターフォルダ内のアバター動画用ディレクトリ
PROFILE_IMAGE_FILENAME = "profile.png"
MEMORY_FILENAME = "memory.txt"
NOTEPAD_FILENAME = "notepad.md"
CONFIG_FILE = "config.json"
ALARMS_FILE = "alarms.json"
REDACTION_RULES_FILE = "redaction_rules.json"


# --- UIとAPIの挙動に関する定数 ---
# (以降、変更なし)
UI_HISTORY_MAX_LIMIT = 200
API_HISTORY_LIMIT_OPTIONS = {"today": "本日分", "1": "1往復", "3": "3往復", "5": "5往復", "10": "10往復", "20": "20往復", "30": "30往復", "40": "40往復", "50": "50往復", "60": "60往復", "70": "70往復", "80": "80往復", "90": "90往復", "100": "100往復", "all": "全ログ"}
DEFAULT_API_HISTORY_LIMIT_OPTION = "20"
DEFAULT_ALARM_API_HISTORY_TURNS = 10

# --- 内部処理用AIモデル ---
INTERNAL_PROCESSING_MODEL = "gemini-2.5-flash-lite"
SUMMARIZATION_MODEL = "gemini-2.5-flash"          # 高品質（要約、文章生成など）
EMBEDDING_MODEL = "gemini-embedding-001"
SUPERVISOR_MODEL = "gemma-3-12b-it"

# --- 自動会話要約設定 ---
AUTO_SUMMARY_DEFAULT_THRESHOLD = 20000  # デフォルト閾値（文字数）
AUTO_SUMMARY_MIN_THRESHOLD = 5000       # 最小閾値
AUTO_SUMMARY_MAX_THRESHOLD = 100000     # 最大閾値
AUTO_SUMMARY_KEEP_RECENT_TURNS = 5      # 要約せず保持する直近往復数
AUTO_SUMMARY_TARGET_LENGTH = 2500       # 要約の目標トークン数

# --- ツール専用AIモデル ---
SEARCH_MODEL = "gemini-2.5-flash"

# --- エピソード記憶設定 ---
EPISODIC_MEMORY_OPTIONS = {
    "0": "なし（無効）",
    "1": "過去 1日",
    "2": "過去 2日",
    "3": "過去 3日",
    "4": "過去 4日",
    "5": "過去 5日",
    "7": "過去 1週間",
    "14": "過去 2週間",
    "30": "過去 1ヶ月",
    "90": "過去 3ヶ月"
}
DEFAULT_EPISODIC_MEMORY_DAYS = "0"

# --- Thinking (Reasoning) モデル設定 ---
THINKING_LEVEL_OPTIONS = {
    "auto": "既定 (AIに任せる / 通常モデル)",
    "none": "無効 (思考プロセスをスキップ)",
    "low": "低 (1,024 tokens)",
    "medium": "中 (4,096 tokens)",
    "high": "高 (16,384 tokens)",
    "extreme": "極高 (32,768 tokens)"
}
DEFAULT_THINKING_LEVEL = "auto"

# --- 表情差分設定 ---
EXPRESSIONS_FILE = "expressions.json"
EXPRESSION_TAG_PATTERN = r"【表情】…(\w+)…"  # 正規表現パターン

# デフォルト表情リスト
DEFAULT_EXPRESSIONS = [
    "idle",        # 待機/通常（必須）
    "thinking",    # 思考中
    "happy",       # 嬉しい
    "sad",         # 悲しい
    "angry",       # 怒り
    "surprised",   # 驚き
    "embarrassed"  # 照れ
]

# 表情→感情キーワードのマッピング（デフォルト）
DEFAULT_EXPRESSION_KEYWORDS = {
    "happy": ["嬉しい", "楽しい", "幸せ", "ありがとう", "わーい", "♪", "笑", "やった"],
    "sad": ["悲しい", "寂しい", "つらい", "残念", "ごめん"],
    "angry": ["怒", "許せない", "ムカつく", "イライラ"],
    "surprised": ["驚", "えっ", "まさか", "びっくり", "！？", "!?"],
    "embarrassed": ["照れ", "恥ずかしい", "えへへ", "///"],
    "thinking": ["うーん", "考え", "そうですね", "..."],
}