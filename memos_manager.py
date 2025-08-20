# [memos_manager.py の全文を、これで完全に置き換える]
from memos import MOS, MOSConfig, GeneralMemCube, GeneralMemCubeConfig
from memos.mem_reader.factory import MemReaderFactory
from memos.configs.mem_reader import SimpleStructMemReaderConfig
import config_manager
import os
import uuid
import neo4j
import time
import shutil

from memos_ext.google_genai_llm import GoogleGenAILLM, GoogleGenAILLMConfig
from memos_ext.google_genai_embedder import GoogleGenAIEmbedder, GoogleGenAIEmbedderConfig

_mos_instances = {}

def get_mos_instance(character_name: str) -> MOS:
    if character_name in _mos_instances:
        return _mos_instances[character_name]

    print(f"--- MemOSインスタンスを初期化中: {character_name} ---")

    # --- 1. 設定とAPIキーの取得 ---
    api_key_name = config_manager.initial_api_key_name_global
    api_key = config_manager.GEMINI_API_KEYS.get(api_key_name, "")

    # --- 2. 接続情報をconfig.jsonから直接取得 ---
    # この時点でconfig_manager.load_config()は実行済みなので、CONFIG_GLOBALは最新
    memos_config_data = config_manager.CONFIG_GLOBAL.get("memos_config", {})
    neo4j_config_for_memos = memos_config_data.get("neo4j_config", {})
    
    DB_NAME = neo4j_config_for_memos.get("db_name")
    NEO4J_URI = neo4j_config_for_memos.get("uri")
    NEO4J_USER = neo4j_config_for_memos.get("user")
    NEO4J_PASSWORD = neo4j_config_for_memos.get("password")

    if not all([DB_NAME, NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD]):
        raise ValueError("config.json内のneo4j_config設定が不完全です。")
    
    # --- 3. データベースの存在確認と、自動作成 ---
    driver = None
    db_exists = False # 変数をここで初期化
    try:
        driver = neo4j.GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        with driver.session(database="system") as session:
            result = session.run("SHOW DATABASES WHERE name = $db_name", db_name=DB_NAME)
            # db_exists をここで設定
            db_exists = any(record for record in result)

        if not db_exists:
            print(f"--- データベース '{DB_NAME}' が存在しません。新規作成します... ---")
            with driver.session(database="system") as session:
                session.run(f"CREATE DATABASE `{DB_NAME}` IF NOT EXISTS")
            
            print(f"--- データベース '{DB_NAME}' のオンライン待機中... ---")
            time.sleep(5) # DB作成直後は少し待つ
            for _ in range(24): # 最大2分間待機
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

    # --- 4. MemOSの初期化 ---
    dummy_llm_config_factory = {"backend": "ollama", "config": {"model_name_or_path": "placeholder"}}
    dummy_embedder_config_factory = {"backend": "ollama", "config": {"model_name_or_path": "placeholder"}}

    mos_config = MOSConfig(
        user_id=character_name,
        chat_model=dummy_llm_config_factory,
        mem_reader={"backend": "simple_struct", "config": {
            "llm": dummy_llm_config_factory, "embedder": dummy_embedder_config_factory,
            "chunker": {"backend": "sentence", "config": {"tokenizer_or_token_counter": "gpt2"}},
        }}
    )
    mem_cube_config = GeneralMemCubeConfig(
        user_id=character_name,
        cube_id=f"{character_name}_main_cube",
        text_mem={ "backend": "tree_text", "config": {
            "extractor_llm": dummy_llm_config_factory, "dispatcher_llm": dummy_llm_config_factory,
            "graph_db": { "backend": "neo4j", "config": neo4j_config_for_memos },
            "embedder": dummy_embedder_config_factory, "reorganize": False
        }}
    )
    
    mos = MOS(mos_config)
    mem_cube = GeneralMemCube(mem_cube_config)

    google_llm_instance = GoogleGenAILLM(GoogleGenAILLMConfig(model_name_or_path="gemini-2.5-flash-lite", google_api_key=api_key))
    google_embedder_instance = GoogleGenAIEmbedder(GoogleGenAIEmbedderConfig(model_name_or_path="embedding-001", google_api_key=api_key))

    # --- 移植手術 ---
    mos.chat_llm = google_llm_instance
    mos.mem_reader.llm = google_llm_instance
    mos.mem_reader.embedder = google_embedder_instance
    mem_cube.text_mem.extractor_llm = google_llm_instance
    mem_cube.text_mem.dispatcher_llm = google_llm_instance
    mem_cube.text_mem.embedder = google_embedder_instance

    # --- 5. 【修正の核心】データベースと同期したMemCubeの永続化ロジック ---
    cube_path = os.path.join("characters", character_name, "memos_cube")
    
    if not db_exists:
        # データベースが存在しなかった場合、それは完全な新規作成を意味する。
        # 古いキャッシュが存在すれば、それは不整合の原因なので、必ず削除する。
        if os.path.exists(cube_path):
            print(f"--- [警告] 新規データベース作成に伴い、古いMemCubeキャッシュ ({cube_path}) を削除して再構築します。")
            shutil.rmtree(cube_path)

        print(f"--- MemCubeキャッシュを新規作成します: {cube_path}")
        os.makedirs(cube_path, exist_ok=True)
        mem_cube.dump(cube_path)

    else:
        # データベースが既に存在する場合、キャッシュも存在するはず。
        # 存在しない場合のみ、何らかの理由で消えたと判断し、作成する。
        if not os.path.exists(cube_path):
            print(f"--- MemCubeキャッシュが存在しないため、新規作成します: {cube_path}")
            os.makedirs(cube_path, exist_ok=True)
            mem_cube.dump(cube_path)
        else:
            print(f"--- 既存のデータベースとMemCubeキャッシュを尊重して読み込みます: {cube_path}")
    
    mos.register_mem_cube(cube_path, mem_cube_id=mem_cube.config.cube_id)

    # --- 6. Reorganizerの強制停止 ---
    print("--- 記憶の自動整理機能を、バッチ処理のために、完全に、停止します... ---")
    mos.mem_reorganizer_wait()
    mos.mem_reorganizer_off()
    print("--- 自動整理機能の、完全停止を、確認しました。 ---")

    _mos_instances[character_name] = mos
    print(f"--- MemOSインスタンスの準備完了 (自動整理機能・停止済み): {character_name} ---")
    return mos
