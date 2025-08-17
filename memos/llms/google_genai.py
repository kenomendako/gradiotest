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
        genai.configure(api_key=self.config.google_api_key)

    def generate(self, messages: MessageList, **kwargs) -> str:
        contents = [
            {"role": msg["role"] if msg["role"] != "assistant" else "model", "parts": [msg["content"]]}
            for msg in messages
        ]
        # In the new google-genai SDK, the client is no longer needed.
        # We can call the model directly.
        model = genai.GenerativeModel(f"models/{self.config.model_name_or_path}")
        response = model.generate_content(
            contents=contents,
            **kwargs
        )
        return response.text

    def generate_stream(self, messages: MessageList, **kwargs):
        contents = [
            {"role": msg["role"] if msg["role"] != "assistant" else "model", "parts": [msg["content"]]}
            for msg in messages
        ]
        model = genai.GenerativeModel(f"models/{self.config.model_name_or_path}")
        response = model.generate_content(
            contents=contents,
            stream=True,
            **kwargs
        )
        for chunk in response:
            yield chunk.text
