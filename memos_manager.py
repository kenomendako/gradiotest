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

    # ... (設定とAPIキーの取得、DBの自動作成ロジックは、前回のまま) ...
    memos_config_data = config_manager.CONFIG_GLOBAL.get("memos_config", {})
    neo4j_config = memos_config_data.get("neo4j_config", {}).copy()
    api_key_name = config_manager.initial_api_key_name_global
    api_key = config_manager.GEMINI_API_KEYS.get(api_key_name, "")
    NEXUSARK_NAMESPACE = uuid.UUID('0ef9569c-368c-4448-99b2-320956435a26')
    char_uuid = uuid.uuid5(NEXUSARK_NAMESPACE, character_name)
    db_name_for_char = f"nexusark-{char_uuid.hex}"
    neo4j_config["db_name"] = db_name_for_char

    # --- 3. ★★★【核心部分】データベースの「作成命令」と「起動確認」の、儀式 ★★★ ---
    driver = None
    try:
        # まず、システムデータベースに接続するためのドライバーを作成
        driver = neo4j.GraphDatabase.driver(
            neo4j_config["uri"],
            auth=(neo4j_config["user"], neo4j_config["password"])
        )

        # 1. まず、「存在しなければ、作成せよ」と、無条件に、命令する
        # このコマンドは、既に、存在していても、エラーを、起こさない
        print(f"--- データベース '{db_name_for_char}' の存在を保証します... ---")
        with driver.session(database="system") as session:
            session.run(f"CREATE DATABASE `{db_name_for_char}` IF NOT EXISTS")

        # 2. 次に、「その、データベースが、オンラインになるまで、ひたすら、待つ」
        print("--- データベースがオンラインになるのを待っています... ---")
        for i in range(120): # 最大120秒（2分間）待つ
            is_online = False
            try:
                with driver.session(database="system") as session:
                    # SHOW DATABASE コマンドで、直接、状態を、確認する
                    result = session.run(f"SHOW DATABASE `{db_name_for_char}` YIELD currentStatus")
                    record = result.single()
                    # レコードが、存在し、かつ、状態が、'online'であることを、確認
                    if record and record["currentStatus"] == "online":
                        is_online = True
            except Exception as e:
                # データベースが、まだ、完全に、リストされていない場合、エラーが、発生することがある
                print(f"    - 状態確認中に、一時的な、エラー: {e}")

            if is_online:
                print(f"--- データベース '{db_name_for_char}' が、正常に、オンラインです。 ---")
                break

            print(f"    - 待機中... ({i+1}/120秒)")
            time.sleep(1)
        else:
            # ループが、breakせずに、終了した場合（タイムアウト）
            raise Exception(f"データベース '{db_name_for_char}' の起動を、タイムアウトしました。")

    finally:
        if driver:
            driver.close()

    # --- ★★★【核心的な修正】ここから ★★★ ---
    # 1. 全ての品質検査を通過させるための、完全なダミー設定を作成
    dummy_llm_config_factory = {"backend": "ollama", "config": {"model_name_or_path": "placeholder"}}
    dummy_embedder_config_factory = {"backend": "ollama", "config": {"model_name_or_path": "placeholder"}}

    # 2. ダミー設定を使って、全ての階層のConfigオブジェクトを、まず、作成する
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
            }
        }
    )

    # 3. ダミー設定で、MOSとMemCubeの、インスタンスを、生成する
    mos = MOS(mos_config)
    mem_cube = GeneralMemCube(mem_cube_config)

    # 4. Nexus Ark専用の、本物の、カスタム器官を、生成する
    google_llm_instance = GoogleGenAILLM(GoogleGenAILLMConfig(model_name_or_path="gemini-2.5-flash-lite", google_api_key=api_key))
    google_embedder_instance = GoogleGenAIEmbedder(GoogleGenAIEmbedderConfig(model_name_or_path="embedding-001", google_api_key=api_key))

    # 5. 【完全なる移植手術】生成された、インスタンスの、内部にある、全ての、ダミー器官を、本物に、置き換える
    mos.chat_llm = google_llm_instance
    mos.mem_reader.llm = google_llm_instance
    mos.mem_reader.embedder = google_embedder_instance # ★★★ この行を追加 ★★★
    mem_cube.text_mem.extractor_llm = google_llm_instance
    mem_cube.text_mem.dispatcher_llm = google_llm_instance
    mem_cube.text_mem.embedder = google_embedder_instance # ★★★ この行を追加 ★★★
    # ★★★ ここまで ★★★

    # 6. CubeをMOSに登録
    cube_path = os.path.join("characters", character_name, "memos_cube")
    if not os.path.exists(cube_path):
        os.makedirs(cube_path, exist_ok=True)
        mem_cube.dump(cube_path)
    mos.register_mem_cube(cube_path, mem_cube_id=mem_cube.config.cube_id)

    _mos_instances[character_name] = mos
    print(f"--- MemOSインスタンスの準備完了 (完全な器官移植済み): {character_name} ---")
    return mos
