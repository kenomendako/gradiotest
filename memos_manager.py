# [新規作成] memos_manager.py (最終仕様 - Code Review Fix)

from memos import MOS, MOSConfig, GeneralMemCube, GeneralMemCubeConfig
import config_manager
import os

# Backend classesを直接インポート
from memos.llms.google_genai import GoogleGenAILLM, GoogleGenAILLMConfig
from memos.embedders.google_genai import GoogleGenAIEmbedder, GoogleGenAIEmbedderConfig

_mos_instances = {}

def get_mos_instance(character_name: str) -> MOS:
    if character_name in _mos_instances:
        return _mos_instances[character_name]

    print(f"--- MemOSインスタンスを初期化中: {character_name} ---")

    memos_config_data = config_manager.CONFIG_GLOBAL.get("memos_config", {})
    neo4j_config = memos_config_data.get("neo4j_config", {})
    api_key_name = config_manager.initial_api_key_name_global
    api_key = config_manager.GEMINI_API_KEYS.get(api_key_name, "")

    # --- Backendのインスタンスを直接生成 ---
    # LLM (Flash)
    llm_flash_config = GoogleGenAILLMConfig(model_name_or_path="gemini-2.5-flash-lite", google_api_key=api_key)
    llm_flash = GoogleGenAILLM(llm_flash_config)

    # Embedder
    embedder_config = GoogleGenAIEmbedderConfig(model_name_or_path="embedding-001", google_api_key=api_key)
    embedder = GoogleGenAIEmbedder(embedder_config)

    # --- Configオブジェクトを生成 ---
    # ファクトリに頼らず、インスタンスを直接渡す
    mos_config = MOSConfig(
        user_id=character_name,
        chat_model=llm_flash, # 辞書の代わりにインスタンスを渡す
    )

    mem_cube_config = GeneralMemCubeConfig(
        user_id=character_name,
        cube_id=f"{character_name}_main_cube",
        text_mem={
            "backend": "tree_text",
            "config": {
                "extractor_llm": llm_flash, # 辞書の代わりにインスタンスを渡す
                "dispatcher_llm": llm_flash, # 辞書の代わりにインスタンスを渡す
                "graph_db": { "backend": "neo4j", "config": neo4j_config },
                "embedder": embedder, # 辞書の代わりにインスタンスを渡す
            }
        }
    )

    mos = MOS(mos_config)
    mem_cube = GeneralMemCube(mem_cube_config)
    cube_path = os.path.join("characters", character_name, "memos_cube")

    # Check if the cube already exists on disk
    if os.path.exists(os.path.join(cube_path, "cube_config.json")):
        # Load from disk if it exists
        print(f"--- MemOSキューブをディスクから読み込み中: {cube_path} ---")
        mos.register_mem_cube(cube_path, mem_cube_id=mem_cube.config.cube_id)
    else:
        # Create and dump if it doesn't exist
        print(f"--- 新しいMemOSキューブを作成・保存中: {cube_path} ---")
        os.makedirs(cube_path, exist_ok=True)
        mem_cube.dump(cube_path)
        mos.register_mem_cube(cube_path, mem_cube_id=mem_cube.config.cube_id)

    _mos_instances[character_name] = mos
    return mos
