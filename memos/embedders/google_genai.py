# src/memos/embedders/google_genai.py (新規作成)
import google.genai as genai
from memos.configs.embedder import BaseEmbedderConfig
from memos.embedders.base import BaseEmbedder
from typing import List

class GoogleGenAIEmbedderConfig(BaseEmbedderConfig):
    google_api_key: str

class GoogleGenAIEmbedder(BaseEmbedder):
    def __init__(self, config: GoogleGenAIEmbedderConfig):
        self.config = config
        genai.configure(api_key=self.config.google_api_key)

    def embed(self, texts: List[str]) -> List[List[float]]:
        response = genai.embed_content(
            model=f"models/{self.config.model_name_or_path}",
            content=texts,
            task_type="RETRIEVAL_DOCUMENT"
        )
        return response['embedding']

    async def aembed(self, texts: List[str]) -> List[List[float]]:
        response = await genai.embed_content_async(
            model=f"models/{self.config.model_name_or_path}",
            content=texts,
            task_type="RETRIEVAL_DOCUMENT"
        )
        return response['embedding']
