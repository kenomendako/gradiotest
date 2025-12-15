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
        force_google: bool = False,  # 内部処理用にGeminiを強制使用する場合True
        room_name: str = None  # ルーム名（ルーム個別のプロバイダ設定を取得するため）
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
            room_name: ルーム名。指定するとルーム個別のプロバイダ設定を優先する。
        """
        config_manager.load_config() 
        
        # ルーム名を渡してルーム個別のプロバイダ設定を優先する
        active_provider = config_manager.get_active_provider(room_name)
        
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
            # ルーム個別のOpenAI設定を優先
            # generation_configにopenai_settingsが含まれていればそれを使用
            room_openai_settings = None
            if generation_config and isinstance(generation_config, dict):
                room_openai_settings = generation_config.get("openai_settings")
            
            if room_openai_settings and room_openai_settings.get("base_url"):
                # ルーム個別設定を使用
                base_url = room_openai_settings.get("base_url")
                openai_api_key = room_openai_settings.get("api_key", "dummy")
                provider_name = room_openai_settings.get("profile", "Room-specific")
                print(f"--- [LLM Factory] Using room-specific OpenAI settings ---")
            else:
                # フォールバック: グローバルなアクティブプロファイルの設定を取得
                openai_setting = config_manager.get_active_openai_setting()
                if not openai_setting:
                    raise ValueError("No active OpenAI provider profile found.")
                base_url = openai_setting.get("base_url")
                openai_api_key = openai_setting.get("api_key")
                provider_name = openai_setting.get("name")
            
            # OllamaなどはAPIキーが不要な場合があるが、ライブラリの仕様上ダミーが必要なことがある
            if not openai_api_key:
                openai_api_key = "dummy"

            print(f"--- [LLM Factory] Creating OpenAI-compatible client ---")
            print(f"  - Provider: {provider_name}")
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