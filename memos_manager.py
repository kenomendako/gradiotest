# memos_manager.py

# このファイル全体を、以下のコードで完全に置き換えてください

from memos import MOS, MOSConfig, GeneralMemCube, GeneralMemCubeConfig
from memos.mem_reader.factory import MemReaderFactory
from memos.configs.mem_reader import SimpleStructMemReaderConfig
import config_manager
import constants
import os
import shutil
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

    print(f"--- MemOSインスタンスを初期化中: {character_name} ---")

    # --- 1. 設定情報の取得 ---
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
    
    # --- 2. データベースの存在確認と自動作成 (変更なし) ---
    driver = None
    db_exists = False
    try:
        driver = neo4j.GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        with driver.session(database="system") as session:
            result = session.run("SHOW DATABASES WHERE name = $db_name", db_name=DB_NAME)
            db_exists = any(record for record in result)

        if not db_exists:
            print(f"--- データベース '{DB_NAME}' が存在しません。新規作成します... ---")
            with driver.session(database="system") as session:
                session.run(f"CREATE DATABASE `{DB_NAME}` IF NOT EXISTS")
            
            print(f"--- データベース '{DB_NAME}' のオンライン待機中... ---")
            time.sleep(5)
            for _ in range(24):
                try:
                    with driver.session(database=DB_NAME) as db_session:
                        db_session.run("RETURN 1").consume()
                    print(f"--- データベース '{DB_NAME}' は正常にオンラインです。 ---")
                    break
                except Exception:
                    time.sleep(5)
            else:
                raise Exception(f"データベース '{DB_NAME}' の起動をタイムアウトしました。")
    finally:
        if driver: driver.close()

    # --- 3. 【最終儀式】最初から全てがGoogle製のコンポーネントを定義 ---

    # Google製LLMインスタンスの生成
    google_llm_instance = GoogleGenAILLM(GoogleGenAILLMConfig(
        model_name_or_path=constants.INTERNAL_PROCESSING_MODEL,
        google_api_key=api_key
    ))

    # Google製Embedderインスタンスの生成
    google_embedder_instance = GoogleGenAIEmbedder(GoogleGenAIEmbedderConfig(
        model_name_or_path="embedding-001",
        google_api_key=api_key
    ))

    # --- 4. 設計図 (Config) の作成 ---

    # MOS (司令塔) の設計図
    mos_config = MOSConfig(
        user_id=character_name,
        # chat_model と mem_reader に、ダミーではなく完成品を渡す
        chat_model=google_llm_instance,
        mem_reader=MemReaderFactory.create_mem_reader(
            "simple_struct",
            SimpleStructMemReaderConfig(
                llm=google_llm_instance,
                embedder=google_embedder_instance,
                chunker={"backend": "sentence", "config": {"tokenizer_or_token_counter": "gpt2"}},
            )
        )
    )

    # MemCube (書庫) の設計図
    mem_cube_config = GeneralMemCubeConfig(
        user_id=character_name,
        cube_id=f"{character_name}_main_cube",
        text_mem={
            "backend": "tree_text",
            "config": {
                "extractor_llm": google_llm_instance,
                "dispatcher_llm": google_llm_instance,
                "embedder": google_embedder_instance,
                "graph_db": {"backend": "neo4j", "config": neo4j_config_for_memos},
                "reorganize": False
            }
        }
    )

    # --- 5. インスタンスの生成と登録 ---
    mos = MOS(mos_config)
    mem_cube = GeneralMemCube(mem_cube_config)

    # MemCubeをMOSに登録
    cube_path = os.path.join(constants.ROOMS_DIR, character_name, "memos_cube")
    if not os.path.exists(cube_path):
        os.makedirs(cube_path, exist_ok=True)
        mem_cube.dump(cube_path)
    
    mos.register_mem_cube(cube_path, mem_cube_id=mem_cube.config.cube_id)

    # --- 6. 自動整理機能の完全停止 ---
    print("--- 記憶の自動整理機能を、完全に、停止します... ---")
    mos.mem_reorganizer_wait()
    mos.mem_reorganizer_off()
    print("--- 自動整理機能の、完全停止を、確認しました。 ---")

    _mos_instances[character_name] = mos
    print(f"--- MemOSインスタンスの準備完了 (完全Google製): {character_name} ---")
    return mos
