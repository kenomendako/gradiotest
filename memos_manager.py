# [memos_manager.py の get_mos_instance 関数を、これで完全に置き換える]

from memos import MOS, MOSConfig, GeneralMemCube, GeneralMemCubeConfig
from memos.mem_reader.factory import MemReaderFactory
from memos.configs.mem_reader import SimpleStructMemReaderConfig
import config_manager
import os
import uuid
import neo4j
import time

from memos_ext.google_genai_llm import GoogleGenAILLM, GoogleGenAILLMConfig
from memos_ext.google_genai_embedder import GoogleGenAIEmbedder, GoogleGenAIEmbedderConfig

_mos_instances = {}

def get_mos_instance(character_name: str) -> MOS:
    if character_name in _mos_instances:
        return _mos_instances[character_name]

    print(f"--- MemOSインスタンスを初期化中: {character_name} ---")

    # --- 1. 設定とAPIキーの取得 ---
    memos_config_data = config_manager.CONFIG_GLOBAL.get("memos_config", {})
    neo4j_config = memos_config_data.get("neo4j_config", {}).copy()
    api_key_name = config_manager.initial_api_key_name_global
    api_key = config_manager.GEMINI_API_KEYS.get(api_key_name, "")

    # --- 2. キャラクター固有のデータベース名を生成 ---
    NEXUSARK_NAMESPACE = uuid.UUID('0ef9569c-368c-4448-99b2-320956435a26')
    char_uuid = uuid.uuid5(NEXUSARK_NAMESPACE, character_name)
    db_name_for_char = f"nexusark-{char_uuid.hex}"
    neo4j_config["db_name"] = db_name_for_char

    # --- 3. データベースの存在確認と、自動作成 ---
    driver = None
    try:
        driver = neo4j.GraphDatabase.driver(
            neo4j_config["uri"],
            auth=(neo4j_config["user"], neo4j_config["password"])
        )

        with driver.session(database="system") as session:
            result = session.run("SHOW DATABASES WHERE name = $db_name", db_name=db_name_for_char)
            db_exists = len([record for record in result]) > 0

        if not db_exists:
            print(f"--- データベース '{db_name_for_char}' が存在しません。新規作成します... ---")
            with driver.session(database="system") as session:
                session.run(f"CREATE DATABASE `{db_name_for_char}` IF NOT EXISTS")

            print("--- データベースがオンラインになるのを待っています... ---")
            for i in range(120):
                is_online = False
                try:
                    with driver.session(database="system") as session:
                        result = session.run(f"SHOW DATABASE `{db_name_for_char}` YIELD currentStatus")
                        record = result.single()
                        if record and record["currentStatus"] == "online":
                            is_online = True
                except Exception:
                    pass

                if is_online:
                    print(f"--- データベース '{db_name_for_char}' が、正常に、オンラインです。 ---")
                    break

                print(f"    - 待機中... ({i+1}/120秒)")
                time.sleep(1)
            else:
                raise Exception(f"データベース '{db_name_for_char}' の起動を、タイムアウトしました。")
    finally:
        if driver:
            driver.close()

    # --- 4. MemOSの初期化 ---
    dummy_llm_config_factory = {"backend": "ollama", "config": {"model_name_or_path": "placeholder"}}
    dummy_embedder_config_factory = {"backend": "ollama", "config": {"model_name_or_path": "placeholder"}}

    mos_config = MOSConfig(
        user_id=character_name,
        chat_model=dummy_llm_config_factory,
        mem_reader={
            "backend": "simple_struct",
            "config": {
                "llm": dummy_llm_config_factory,
                "embedder": dummy_embedder_config_factory,
                "chunker": {"backend": "sentence", "config": {"tokenizer_or_token_counter": "gpt2"}},
            },
        }
    )
    # ▼▼▼【ここからが修正の核心】▼▼▼
    mem_cube_config = GeneralMemCubeConfig(
        user_id=character_name,
        cube_id=f"{character_name}_main_cube",
        text_mem={
            "backend": "tree_text",
            "config": {
                "extractor_llm": dummy_llm_config_factory,
                "dispatcher_llm": dummy_llm_config_factory,
                "graph_db": { "backend": "neo4j", "config": neo4j_config },
                "embedder": dummy_embedder_config_factory,
                "reorganize": False # ★★★ Reorganizerを明確に無効化 ★★★
            }
        }
    )
    mos = MOS(mos_config)
    mem_cube = GeneralMemCube(mem_cube_config)

    google_llm_instance = GoogleGenAILLM(GoogleGenAILLMConfig(model_name_or_path="gemini-2.5-flash-lite", google_api_key=api_key))
    google_embedder_instance = GoogleGenAIEmbedder(GoogleGenAIEmbedderConfig(model_name_or_path="embedding-001", google_api_key=api_key))

    # --- 移植手術：MOSインスタンスの心臓部をGoogle製に置換 ---
    mos.chat_llm = google_llm_instance
    mos.mem_reader.llm = google_llm_instance
    mos.mem_reader.embedder = google_embedder_instance

    # --- 移植手術：MemCubeインスタンスの心臓部もGoogle製に置換 ---
    mem_cube.text_mem.extractor_llm = google_llm_instance
    mem_cube.text_mem.dispatcher_llm = google_llm_instance
    mem_cube.text_mem.embedder = google_embedder_instance
    # ▲▲▲【修正ここまで】▲▲▲

    # --- 5. Cubeの登録と、バックグラウンド処理の停止 ---
    cube_path = os.path.join("characters", character_name, "memos_cube")
    if not os.path.exists(cube_path):
        os.makedirs(cube_path, exist_ok=True)
        mem_cube.dump(cube_path)
    mos.register_mem_cube(cube_path, mem_cube_id=mem_cube.config.cube_id)

    print("--- 記憶の自動整理機能を、バッチ処理のために、完全に、停止します... ---")
    mos.mem_reorganizer_wait()
    mos.mem_reorganizer_off()
    print("--- 自動整理機能の、完全停止を、確認しました。 ---")

    _mos_instances[character_name] = mos
    print(f"--- MemOSインスタンスの準備完了 (自動整理機能・停止済み): {character_name} ---")
    return mos
