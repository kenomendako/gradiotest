# memos_manager.py (最終確定版: v2.2改 Jules's Post-Initialization Patch)

from memos import MOS, MOSConfig, GeneralMemCube, GeneralMemCubeConfig
import config_manager
import constants
import os
import neo4j
import time

# Nexus Ark用にカスタマイズしたGoogle GenAIのLLMとEmbedderをインポート
from memos_ext.google_genai_llm import GoogleGenAILLM, GoogleGenAILLMConfig
from memos_ext.google_genai_embedder import GoogleGenAIEmbedder, GoogleGenAIEmbedderConfig

# グローバルなインスタンスキャッシュ
_mos_instances = {}

def get_mos_instance(character_name: str) -> MOS:
    if character_name in _mos_instances:
        return _mos_instances[character_name]

    print(f"--- MemOSインスタンスを初期化中 (Post-Init Patch版): {character_name} ---")

    # --- 1. 設定情報の取得 (変更なし) ---
    api_key_name = config_manager.initial_api_key_name_global
    api_key = config_manager.GEMINI_API_KEYS.get(api_key_name, "")
    memos_config_data = config_manager.CONFIG_GLOBAL.get("memos_config", {})
    neo4j_config_for_memos = memos_config_data.get("neo4j_config", {})
    DB_NAME = neo4j_config_for_memos.get("db_name")
    NEO4J_URI = neo4j_config_for_memos.get("uri")
    NEO4J_USER = neo4j_config_for_memos.get("user")
    NEO4J_PASSWORD = neo4j_config_for_memos.get("password")

    if not all([DB_NAME, NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD]):
        raise ValueError("config.json内のneo4j_config設定が不完全です。")
    
    # DB存在確認と作成ロジック (変更なし)
    driver = None
    try:
        driver = neo4j.GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        with driver.session(database="system") as session:
            result = session.run("SHOW DATABASES WHERE name = $db_name", db_name=DB_NAME)
            if not any(record for record in result):
                print(f"--- データベース '{DB_NAME}' が存在しません。新規作成します... ---")
                session.run(f"CREATE DATABASE `{DB_NAME}` IF NOT EXISTS")
                print(f"--- データベース '{DB_NAME}' のオンライン待機中... ---")
                time.sleep(10)
                for _ in range(24):
                    try:
                        with driver.session(database=DB_NAME) as db_session:
                            db_session.run("RETURN 1").consume()
                        print(f"--- データベース '{DB_NAME}' は正常にオンラインです。 ---")
                        break
                    except neo4j.exceptions.ClientError:
                        time.sleep(5)
                else:
                    raise Exception(f"データベース '{DB_NAME}' の起動がタイムアウトしました。")
    finally:
        if driver: driver.close()

    # --- 2. 【心臓移植の準備】我々自身のコンポーネントを作成 ---
    google_llm_instance = GoogleGenAILLM(GoogleGenAILLMConfig(
        model_name_or_path=constants.INTERNAL_PROCESSING_MODEL,
        google_api_key=api_key
    ))
    google_embedder_instance = GoogleGenAIEmbedder(GoogleGenAIEmbedderConfig(
        model_name_or_path="embedding-001",
        google_api_key=api_key
    ))

    # --- 3. 【欺瞞の初期化】ダミーの設定でインスタンスをまず生成させる ---
    dummy_llm_config_factory = {"backend": "ollama", "config": {"model_name_or_path": "placeholder"}}
    dummy_embedder_config_factory = {"backend": "ollama", "config": {"model_name_or_path": "placeholder"}}
    dummy_chunker_config_factory = {"backend": "sentence", "config": {"tokenizer_or_token_counter": "gpt2"}}

    mos_config = MOSConfig(
        user_id=character_name,
        chat_model=dummy_llm_config_factory,
        mem_reader={
            "backend": "simple_struct",
            "config": {
                "llm": dummy_llm_config_factory,
                "embedder": dummy_embedder_config_factory,
                "chunker": dummy_chunker_config_factory
            }
        }
    )
    mem_cube_config = GeneralMemCubeConfig(
        user_id=character_name,
        cube_id=f"{character_name}_main_cube",
        text_mem={
            "backend": "tree_text",
            "config": {
                "extractor_llm": dummy_llm_config_factory,
                "dispatcher_llm": dummy_llm_config_factory,
                "embedder": dummy_embedder_config_factory,
                "graph_db": {"backend": "neo4j", "config": neo4j_config_for_memos},
                "reorganize": False
            }
        }
    )

    mos = MOS(mos_config)
    mem_cube = GeneralMemCube(mem_cube_config)

    # --- 4. 【心臓移植手術】生成されたインスタンスの属性を完全に上書き ---
    print("--- MemOSインスタンスの心臓移植手術を開始... ---")
    mos.chat_llm = google_llm_instance
    mos.mem_reader.llm = google_llm_instance
    mos.mem_reader.embedder = google_embedder_instance

    if hasattr(mem_cube, 'text_mem'):
        mem_cube.text_mem.extractor_llm = google_llm_instance
        mem_cube.text_mem.dispatcher_llm = google_llm_instance
        mem_cube.text_mem.embedder = google_embedder_instance
        if hasattr(mem_cube.text_mem, 'mem_reader'):
            mem_cube.text_mem.mem_reader.llm = google_llm_instance
            mem_cube.text_mem.mem_reader.embedder = google_embedder_instance
    print("--- 心臓移植手術完了。全てのエンジンをGoogle GenAIに置換しました。 ---")

    # --- 5. 登録と最終処理 (変更なし) ---
    cube_path = os.path.join(constants.ROOMS_DIR, character_name, "memos_cube")
    if not os.path.exists(cube_path):
        os.makedirs(cube_path, exist_ok=True)
        mem_cube.dump(cube_path)
    mos.register_mem_cube(cube_path, mem_cube_id=mem_cube.config.cube_id)

    mos.mem_reorganizer_wait()
    mos.mem_reorganizer_off()

    _mos_instances[character_name] = mos
    print(f"--- MemOSインスタンスの準備完了 (Post-Init Patch版): {character_name} ---")
    return mos
