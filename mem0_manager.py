# mem0_manager.py

import os
from mem0 import Memory
from mem0.configs.base import MemoryConfig, LlmConfig, EmbedderConfig, VectorStoreConfig

# キャラクターごとにMem0インスタンスをキャッシュするための辞書
_mem0_instances = {}

def get_mem0_instance(character_name: str, api_key: str, model_name: str = "gemini-2.5-flash-lite-preview-06-17") -> Memory:
    """
    キャラクター名、APIキー、モデル名に基づいて、対応するMem0インスタンスを取得または生成する。
    """
    # ★★★ 修正点：モデル名も含めてキャッシュのキーにする ★★★
    instance_key = f"{character_name}_{model_name}"
    if instance_key in _mem0_instances:
        return _mem0_instances[instance_key]

    print(f"--- 新しいMem0インスタンスを生成中 (Character: {character_name}, Model: {model_name}) ---")

    # ... (qdrant_path, safe_collection_name の部分は変更なし) ...
    qdrant_path = os.path.abspath(os.path.join("characters", character_name, "mem0_qdrant_data"))
    safe_collection_name = f"nexus_ark_memories_{''.join(filter(str.isalnum, character_name.lower()))}"


    config = MemoryConfig(
        llm=LlmConfig(
            provider="gemini",
            config={
                "model": model_name, # ★★★ 修正点：引数で受け取ったモデル名を使用 ★★★
                "api_key": api_key,
            }
        ),
        embedder=EmbedderConfig(
            provider="gemini",
            config={
                "model": "models/text-embedding-004", # Embedderモデルは固定
                "api_key": api_key,
                "embedding_dims": 768
            }
        ),
        vector_store=VectorStoreConfig(
            provider="qdrant",
            config={
                "path": qdrant_path,
                "collection_name": safe_collection_name,
                "embedding_model_dims": 768 # QdrantにはEmbedderの次元数を指定
            }
        )
    )

    mem0_instance = Memory(config=config)
    print(f"--- Mem0インスタンス生成完了 (Collection: {safe_collection_name}, Model: {model_name}) ---")

    _mem0_instances[instance_key] = mem0_instance
    return mem0_instance
