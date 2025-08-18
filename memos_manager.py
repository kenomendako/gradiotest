# [memos_manager.py を、この内容で完全に置き換える]

from memos import MOS, MOSConfig, GeneralMemCube, GeneralMemCubeConfig
import config_manager
import os
import uuid
import neo4j # ★★★ この行を追加 ★★★
import time  # ★★★ この行を追加 ★★★

# ★★★【核心的な修正】ローカルの、カスタム器官を、インポートする ★★★
from memos_ext.google_genai_llm import GoogleGenAILLM, GoogleGenAILLMConfig
from memos_ext.google_genai_embedder import GoogleGenAIEmbedder, GoogleGenAIEmbedderConfig
# ★★★ ここまで ★★★

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
    db_name_for_char = f"nexusark-{char_uuid.hex}" # ★★★ アンダースコアを、ダッシュに、変更 ★★★
    neo4j_config["db_name"] = db_name_for_char

    # --- 3. ★★★【核心部分】データベースの存在確認と、自動作成 ★★★ ---
    driver = None
    try:
        # まず、システムデータベースに接続するためのドライバーを作成
        driver = neo4j.GraphDatabase.driver(
            neo4j_config["uri"],
            auth=(neo4j_config["user"], neo4j_config["password"])
        )

        # データベースが存在するか確認するクエリ
        with driver.session(database="system") as session:
            result = session.run("SHOW DATABASES WHERE name = $db_name", db_name=db_name_for_char)
            db_exists = len([record for record in result]) > 0

        # 存在しない場合のみ、作成コマンドを実行
        if not db_exists:
            print(f"--- データベース '{db_name_for_char}' が存在しません。新規作成します... ---")
            with driver.session(database="system") as session:
                # データベース作成コマンドは非同期で完了しないことがある
                session.run(f"CREATE DATABASE `{db_name_for_char}` IF NOT EXISTS")

            print("--- データベースがオンラインになるのを待っています... ---")

            # ★★★ ここからが、修正の核心 ★★★
            # データベースがSHOW DATABASESでリストされるまで、少し待つ
            for _ in range(15): # 最大15秒待つ
                with driver.session(database="system") as session:
                    result = session.run("SHOW DATABASES WHERE name = $db_name", db_name=db_name_for_char)
                    # single()ではなく、リストとして評価し、空でないことを確認する
                    records = list(result)
                    if records:
                        # データベースがリストされたら、次にその状態を確認
                        status_result = session.run("SHOW DATABASE `$db_name` YIELD currentStatus", db_name=db_name_for_char)
                        single_record = status_result.single()
                        if single_record and single_record["currentStatus"] == "online":
                            print(f"--- データベース '{db_name_for_char}' がオンラインになりました。 ---")
                            break
                print("    - まだ作成中です。1秒待機します...")
                time.sleep(1)
            else:
                # ループがbreakせずに終了した場合（タイムアウト）
                raise Exception(f"データベース '{db_name_for_char}' の起動をタイムアウトしました。")
            # ★★★ ここまでが、修正の核心 ★★★
    finally:
        if driver:
            driver.close()
    # --- ここまでが核心部分 ---

    # 4. MemOSの初期化 (これ以降は変更なし)
    # ... (前回のコードと同じダミー設定と、カスタム器官の移植ロジック) ...
    dummy_llm_config_for_validation = {
        "backend": "ollama", "config": {"model_name_or_path": "placeholder"},
    }
    dummy_embedder_config_for_validation = {
        "backend": "ollama", "config": {"model_name_or_path": "placeholder"},
    }
    mos_config = MOSConfig(
        user_id=character_name,
        chat_model=dummy_llm_config_for_validation,
        mem_reader={
            "backend": "simple_struct",
            "config": {
                "llm": dummy_llm_config_for_validation,
                "embedder": dummy_embedder_config_for_validation,
                "chunker": {"backend": "sentence", "config": {"tokenizer_or_token_counter": "gpt2"}},
            },
        }
    )
    mem_cube_config = GeneralMemCubeConfig(
        user_id=character_name,
        cube_id=f"{character_name}_main_cube",
        text_mem={
            "backend": "tree_text",
            "config": {
                "extractor_llm": mos_config.chat_model,
                "dispatcher_llm": mos_config.chat_model,
                "graph_db": { "backend": "neo4j", "config": neo4j_config },
                "embedder": {
                     "backend": "google_genai",
                     "config": { "model_name_or_path": "embedding-001", "google_api_key": api_key },
                }
            }
        }
    )
    mos = MOS(mos_config)
    mem_cube = GeneralMemCube(mem_cube_config)

    # Nexus Ark専用の、カスタム器官を、直接、生成
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

    # 5. CubeをMOSに登録
    cube_path = os.path.join("characters", character_name, "memos_cube")
    if not os.path.exists(cube_path):
        os.makedirs(cube_path, exist_ok=True)
        mem_cube.dump(cube_path)
    mos.register_mem_cube(cube_path, mem_cube_id=mem_cube.config.cube_id)

    _mos_instances[character_name] = mos
    print(f"--- MemOSインスタンスの準備完了 (カスタム器官移植済み): {character_name} ---")
    return mos
