# [memos_manager.py を、この内容で完全に置き換える]

from memos import MOS, MOSConfig, GeneralMemCube, GeneralMemCubeConfig
import config_manager
import os
import uuid # ★★★ この行を追加 ★★★

# ★★★【核心的な修正】ローカルの、カスタム器官を、インポートする ★★★
from memos_ext.google_genai_llm import GoogleGenAILLM, GoogleGenAILLMConfig
from memos_ext.google_genai_embedder import GoogleGenAIEmbedder, GoogleGenAIEmbedderConfig
# ★★★ ここまで ★★★

_mos_instances = {}

def get_mos_instance(character_name: str) -> MOS:
    if character_name in _mos_instances:
        return _mos_instances[character_name]

    print(f"--- MemOSインスタンスを初期化中: {character_name} ---")

    memos_config_data = config_manager.CONFIG_GLOBAL.get("memos_config", {})
    # neo4j_config の読み込み部分を、以下のように修正
    neo4j_config = memos_config_data.get("neo4j_config", {}).copy() # ★ .copy()で安全なコピーを作成

    # ★★★【核心的な修正】ここから ★★★
    # キャラクター名から、常に、同じ、ユニークなIDを、生成する（決定論的UUID）
    # これにより、日本語名でも、安全な、データベース名が、作られる
    NEXUSARK_NAMESPACE = uuid.UUID('0ef9569c-368c-4448-99b2-320956435a26') # プロジェクト固定のID
    char_uuid = uuid.uuid5(NEXUSARK_NAMESPACE, character_name)

    # UUIDを、ハイフンなしの、短い、文字列に、変換して、名前に、使用する
    db_name_for_char = f"nexusark_{char_uuid.hex}"
    neo4j_config["db_name"] = db_name_for_char
    # ★★★ ここまで ★★★

    api_key_name = config_manager.initial_api_key_name_global
    api_key = config_manager.GEMINI_API_KEYS.get(api_key_name, "")

    # Pydanticの型検証を通過させるため、ダミーのバックエンドで設定オブジェクトを作成
    dummy_llm_config_for_validation = {
        "backend": "ollama", "config": {"model_name_or_path": "placeholder"},
    }
    dummy_embedder_config_for_validation = {
        "backend": "ollama", "config": {"model_name_or_path": "placeholder"},
    }

    mos_config = MOSConfig(
        user_id=character_name,
        chat_model=dummy_llm_config_for_validation,
        # 【追加】MemReaderのためのダミー設定を追加
        mem_reader={
            "backend": "simple_struct",
            "config": {
                "llm": dummy_llm_config_for_validation,
                "embedder": dummy_embedder_config_for_validation,
                "chunker": {
                    "backend": "sentence",
                    "config": {"tokenizer_or_token_counter": "gpt2"},
                },
            },
        }
    )

    mem_cube_config = GeneralMemCubeConfig(
        user_id=character_name,
        cube_id=f"{character_name}_main_cube",
        text_mem={
            "backend": "tree_text",
            "config": {
                "extractor_llm": dummy_llm_config_for_validation,
                "dispatcher_llm": dummy_llm_config_for_validation,
                "graph_db": { "backend": "neo4j", "config": neo4j_config },
                "embedder": dummy_embedder_config_for_validation,
            }
        }
    )

    mos = MOS(mos_config)
    mem_cube = GeneralMemCube(mem_cube_config)

    # Nexus Ark専用の、カスタム器官を、直接、生成
    # ★★★ バッチ処理と通常の対話で、同じLLM (flash-lite) を使用する ★★★
    google_llm_config = GoogleGenAILLMConfig(
        model_name_or_path="gemini-2.5-flash-lite",
        google_api_key=api_key
    )
    google_llm_instance = GoogleGenAILLM(google_llm_config)

    google_embedder_config = GoogleGenAIEmbedderConfig(
        model_name_or_path="embedding-001",
        google_api_key=api_key
    )
    google_embedder_instance = GoogleGenAIEmbedder(google_embedder_config)

    # 初期化された、MOSとMemCubeの、各コンポーネントを、本物の、カスタム器官に、置き換える
    mos.chat_llm = google_llm_instance
    mem_cube.text_mem.extractor_llm = google_llm_instance
    mem_cube.text_mem.dispatcher_llm = google_llm_instance
    mem_cube.text_mem.embedder = google_embedder_instance

    # CubeをMOSに登録
    cube_path = os.path.join("characters", character_name, "memos_cube")
    if not os.path.exists(cube_path):
        os.makedirs(cube_path, exist_ok=True)
        mem_cube.dump(cube_path)

    mos.register_mem_cube(cube_path, mem_cube_id=mem_cube.config.cube_id)

    _mos_instances[character_name] = mos
    print(f"--- MemOSインスタンスの準備完了 (カスタム器官移植済み): {character_name} ---")
    return mos
