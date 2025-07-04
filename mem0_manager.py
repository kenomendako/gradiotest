# mem0_manager.py

import os
from mem0 import Memory
from mem0.configs.base import MemoryConfig, LlmConfig, EmbedderConfig, VectorStoreConfig

# キャラクターごとにMem0インスタンスをキャッシュするための辞書
_mem0_instances = {}

def get_mem0_instance(character_name: str, api_key: str) -> Memory:
    """
    キャラクター名とAPIキーに基づいて、対応するMem0インスタンスを取得または生成する。
    インスタンスはキャッシュされ、同じキャラクターには同じインスタンスが返される。
    """
    if character_name in _mem0_instances:
        # キャッシュに存在すればそれを返す
        return _mem0_instances[character_name]

    print(f"--- 新しいMem0インスタンスを生成中: {character_name} ---")

    qdrant_path = os.path.abspath(os.path.join("characters", character_name, "mem0_qdrant_data"))
    safe_collection_name = f"nexus_ark_memories_{''.join(filter(str.isalnum, character_name.lower()))}"

    # Mem0の設定オブジェクトを構築
    config = MemoryConfig(
        llm=LlmConfig(
            provider="gemini",
            config={
                # ★★★ 修正箇所 ★★★
                # モデル名を、指定された 'gemini-2.5-flash' に修正します。
                "model": "gemini-2.5-flash",
                "api_key": api_key,
            }
        ),
        embedder=EmbedderConfig(
            provider="gemini",
            config={
                "model": "models/text-embedding-004",
                "api_key": api_key,
                "embedding_dims": 768
            }
        ),
        vector_store=VectorStoreConfig(
            provider="qdrant",
            config={
                "path": qdrant_path,
                "collection_name": safe_collection_name,
                "embedding_model_dims": 768
            }
        )
    )

    mem0_instance = Memory(config=config)
    print(f"--- Mem0インスタンス生成完了: {character_name} (Collection: {safe_collection_name}) ---")

    _mem0_instances[character_name] = mem0_instance

    return mem0_instance
