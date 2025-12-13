# llm_factory.py

import os
from langchain_google_genai import ChatGoogleGenerativeAI, HarmBlockThreshold, HarmCategory
from langchain_openai import ChatOpenAI
import config_manager
import gemini_api # 既存のGemini設定ロジックを再利用するため

class LLMFactory:
    @staticmethod
    def create_chat_model(
        model_name: str,
        temperature: float = 0.7,
        top_p: float = 0.95,
        max_retries: int = 0,
        api_key: str = None, # Gemini用 (OpenAI系は設定から取得)
        generation_config: dict = None,
        force_google: bool = False  # 内部処理用にGeminiを強制使用する場合True
    ):
        """
        現在の設定(active_provider)に基づいて、適切なLangChain ChatModelインスタンスを生成して返す。
        
        Args:
            model_name: 使用するモデル名
            temperature: 生成温度
            top_p: Top-P
            max_retries: リトライ回数（Agent側で制御するため基本0）
            api_key: Geminiを使用する場合のAPIキー
            generation_config: その他の生成設定（安全性設定など）
            force_google: Trueの場合、active_providerに関係なくGemini Nativeを使用。
                          内部処理（検索クエリ生成、情景描写等）はGemini固定のため。
        """
        config_manager.load_config() 
        
        active_provider = config_manager.get_active_provider()
        
        # 【マルチモデル対応】内部処理用モデルは強制的にGemini APIを使用
        # ユーザー設定のプロバイダ（OpenAI等）に関係なく、Gemini固定が必要な処理用
        if force_google:
            print(f"--- [LLM Factory] Force Google mode: Using Gemini Native for internal processing ---")
            print(f"  - Model: {model_name}")
            active_provider = "google"

        # --- Google Gemini (Native) ---
        if active_provider == "google":
            # 既存の gemini_api.get_configured_llm ロジックを利用
            # ※ api_key が必須
            if not api_key:
                raise ValueError("Google provider requires an API key.")
                
            return gemini_api.get_configured_llm(
                model_name=model_name,
                api_key=api_key,
                generation_config=generation_config
            )

        # --- OpenAI Compatible (OpenRouter, Groq, Ollama, etc.) ---
        elif active_provider == "openai":
            # 現在アクティブなプロファイルの設定を取得
            openai_setting = config_manager.get_active_openai_setting()
            if not openai_setting:
                raise ValueError("No active OpenAI provider profile found.")

            base_url = openai_setting.get("base_url")
            openai_api_key = openai_setting.get("api_key")
            
            # OllamaなどはAPIキーが不要な場合があるが、ライブラリの仕様上ダミーが必要なことがある
            if not openai_api_key:
                openai_api_key = "dummy"

            print(f"--- [LLM Factory] Creating OpenAI-compatible client ---")
            print(f"  - Provider: {openai_setting.get('name')}")
            print(f"  - Base URL: {base_url}")
            print(f"  - Model: {model_name}")

            return ChatOpenAI(
                base_url=base_url,
                api_key=openai_api_key,
                model=model_name,
                temperature=temperature,
                max_retries=max_retries,
                # ストリーミング対応のため必須
                streaming=True 
            )

        else:
            raise ValueError(f"Unknown provider: {active_provider}")