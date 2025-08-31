# memos_ext/google_genai_embedder.py
import google.genai as genai
from memos.configs.embedder import BaseEmbedderConfig
from memos.embedders.base import BaseEmbedder

class GoogleGenAIEmbedderConfig(BaseEmbedderConfig):
    google_api_key: str

class GoogleGenAIEmbedder(BaseEmbedder):
    def __init__(self, config: GoogleGenAIEmbedderConfig):
        self.config = config
        self.client = genai.Client(api_key=self.config.google_api_key)

    def embed(self, texts: list[str]) -> list[list[float]]:
        # embed_contentにはtask_typeは不要
        response = self.client.models.embed_content(
            model=f"models/{self.config.model_name_or_path}",
            contents=texts
        )
        # response.embeddingsはContentEmbeddingオブジェクトのリストなので、.valuesで値を取り出す
        return [embedding.values for embedding in response.embeddings]
