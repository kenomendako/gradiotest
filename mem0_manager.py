from mem0 import Memory
from mem0.configs import MemoryConfig
from mem0.llms.gemini import GeminiConfig
from mem0.embeddings.gemini import GeminiEmbeddingConfig
from mem0.vector_stores.qdrant import QdrantConfig

def get_mem0_instance(character_name: str, api_key: str) -> Memory:
    """
    キャラクター名とAPIキーを受け取り、対応するMem0のMemoryインスタンスを返します。

    Args:
        character_name: キャラクター名。
        api_key: Google Gemini APIキー。

    Returns:
        Mem0のMemoryインスタンス。
    """
    llm_config = GeminiConfig(
        model_name="gemini-1.5-flash-latest",
        api_key=api_key,
        # temperature=0.7,  # 必要に応じて調整
        # max_tokens=1000, # 必要に応じて調整
    )

    embedding_config = GeminiEmbeddingConfig(
        model_name="models/text-embedding-004",
        api_key=api_key,
        # task_type="retrieval_document", # 必要に応じて調整
    )

    vector_store_config = QdrantConfig(
        path=f"characters/{character_name}/mem0_qdrant_data",
        collection_name=f"nexus_ark_{character_name}_memories",
        # host="localhost", # Qdrantサーバーをローカルで実行する場合
        # port=6333,       # Qdrantサーバーのポート
        # api_key="YOUR_QDRANT_API_KEY", # Qdrant Cloudを使用する場合
    )

    config = MemoryConfig(
        llm_config=llm_config,
        embedding_config=embedding_config,
        vector_store_config=vector_store_config,
        # version="0.0.1", # 必要に応じてバージョンを指定
        # system_prompt="You are a helpful AI assistant.", # 必要に応じてシステムプロンプトを指定
    )

    mem0_instance = Memory.from_config(config)
    return mem0_instance

if __name__ == '__main__':
    # 簡単なテスト用（実行にはAPIキーの設定が必要）
    # from dotenv import load_dotenv
    # import os
    # load_dotenv()
    # GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
    # if not GOOGLE_API_KEY:
    #     print("Google APIキーが設定されていません。 .envファイルを確認してください。")
    # else:
    #     try:
    #         lucien_mem0 = get_mem0_instance("Lucien", GOOGLE_API_KEY)
    #         print("LucienのMem0インスタンスが正常に作成されました。")
    #         # 簡単な記憶の追加と検索
    #         lucien_mem0.add("今日の天気は晴れだった。")
    #         memories = lucien_mem0.search("今日の天気は？")
    #         if memories:
    #             print(f"検索結果: {memories[0]['text']}")
    #         else:
    #             print("関連する記憶は見つかりませんでした。")

    #         # 別のキャラクターのインスタンス
    #         elara_mem0 = get_mem0_instance("Elara", GOOGLE_API_KEY)
    #         print("ElaraのMem0インスタンスが正常に作成されました。")
    #         elara_mem0.add("好きな食べ物はリンゴだ。")
    #         memories_elara = elara_mem0.search("好きな食べ物は？")
    #         if memories_elara:
    #             print(f"Elaraの検索結果: {memories_elara[0]['text']}")
    #         else:
    #             print("Elaraの関連する記憶は見つかりませんでした。")

    #     except Exception as e:
    #         print(f"Mem0インスタンスの作成またはテスト中にエラーが発生しました: {e}")
    pass
