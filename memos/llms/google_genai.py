# src/memos/llms/google_genai.py (新規作成)
import google.genai as genai
from memos.configs.llm import BaseLLMConfig
from memos.llms.base import BaseLLM
from memos.types import MessageList

class GoogleGenAILLMConfig(BaseLLMConfig):
    google_api_key: str

class GoogleGenAILLM(BaseLLM):
    def __init__(self, config: GoogleGenAILLMConfig):
        self.config = config
        self.client = genai.Client(api_key=self.config.google_api_key)

    def generate(self, messages: MessageList) -> str:
        contents = [
            {"role": msg["role"] if msg["role"] != "assistant" else "model", "parts": [msg["content"]]}
            for msg in messages
        ]
        response = self.client.models.generate_content(
            model=f"models/{self.config.model_name_or_path}",
            contents=contents
        )
        return response.text

    def generate_stream(self, messages: MessageList, **kwargs):
        raise NotImplementedError("Streaming is not yet implemented for GoogleGenAILLM.")
