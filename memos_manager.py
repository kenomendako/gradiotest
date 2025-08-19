# [memos_manager.py の get_mos_instance 関数を、これで完全に置き換える]

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

    # ▼▼▼【ここからが修正の核心】▼▼▼
    # --- 2. 接続情報をプログラム内で直接定義し、汚染の可能性を排除 ---
    DB_NAME = "nexusark-memos-db"

    # config.jsonから認証情報のみを読み込む
    neo4j_auth_config = config_manager.CONFIG_GLOBAL.get("memos_config", {}).get("neo4j_config", {})
    NEO4J_URI = neo4j_auth_config.get("uri", "bolt://localhost:7687")
    NEO4J_USER = neo4j_auth_config.get("user", "neo4j")
    NEO4J_PASSWORD = neo4j_auth_config.get("password")

    if not NEO4J_PASSWORD or NEO4J_PASSWORD == "YOUR_NEO4J_PASSWORD":
        raise ValueError("Neo4jのパスワードがconfig.jsonに設定されていません。")

    # MemOSに直接注入するための最終的な設定オブジェクトを作成
    neo4j_config_for_memos = {
        "uri": NEO4J_URI,
        "user": NEO4J_USER,
        "password": NEO4J_PASSWORD,
        "db_name": DB_NAME
    }

    # --- 3. データベースの存在確認と、自動作成 ---
    driver = None
    try:
        driver = neo4j.GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        with driver.session(database="system") as session:
            result = session.run("SHOW DATABASES WHERE name = $db_name", db_name=DB_NAME)
            db_exists = len([record for record in result]) > 0

        if not db_exists:
            print(f"--- データベース '{DB_NAME}' が存在しません。新規作成します... ---")
            with driver.session(database="system") as session:
                session.run(f"CREATE DATABASE `{DB_NAME}` IF NOT EXISTS")
            time.sleep(5) # DB作成後に少し待機
            print(f"--- データベース '{DB_NAME}' を作成しました。オンラインになるのを待ちます... ---")
            for _ in range(24): # 2分待つ
                try:
                    with driver.session(database=DB_NAME) as db_session:
                        db_session.run("RETURN 1")
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

    mos.chat_llm = google_llm_instance
    mos.mem_reader.llm = google_llm_instance
    mos.mem_reader.embedder = google_embedder_instance
    mem_cube.text_mem.extractor_llm = google_llm_instance
    mem_cube.text_mem.dispatcher_llm = google_llm_instance
    mem_cube.text_mem.embedder = google_embedder_instance

    # --- 5. 汚染された古いCubeを浄化し、クリーンな状態で登録する ---
    cube_path = os.path.join("characters", character_name, "memos_cube")

    # もし古いキャッシュディレクトリが存在すれば、それを完全に削除する
    if os.path.exists(cube_path):
        print(f"--- [警告] 古い、あるいは汚染されたMemCubeキャッシュ ({cube_path}) を検出しました。")
        print("---      これを強制的に削除し、クリーンな状態で再構築します。")
        shutil.rmtree(cube_path)

    # 常に新しい、クリーンなディレクトリを作成し、正しい設定でCubeを保存する
    os.makedirs(cube_path, exist_ok=True)
    mem_cube.dump(cube_path)

    # クリーンな状態のCubeを登録する
    mos.register_mem_cube(cube_path, mem_cube_id=mem_cube.config.cube_id)

    print("--- 記憶の自動整理機能を、バッチ処理のために、完全に、停止します... ---")
    mos.mem_reorganizer_wait()
    mos.mem_reorganizer_off()
    print("--- 自動整理機能の、完全停止を、確認しました。 ---")

    _mos_instances[character_name] = mos
    print(f"--- MemOSインスタンスの準備完了 (自動整理機能・停止済み): {character_name} ---")
    return mos
