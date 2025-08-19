# memos_ext/google_genai_embedder.py (新規作成)
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
        response = self.client.models.embed_content(
            model=f"models/{self.config.model_name_or_path}",
            contents=texts
        )
        return [embedding.values for embedding in response.embeddings] # ★★★ 正しい、オブジェクトの、作法 ★★★
