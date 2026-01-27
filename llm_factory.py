# llm_factory.py

import os
from langchain_google_genai import ChatGoogleGenerativeAI, HarmBlockThreshold, HarmCategory
from langchain_openai import ChatOpenAI
import config_manager
import gemini_api # 既存のGemini設定ロジックを再利用するため

class LLMFactory:
    @staticmethod
    def create_chat_model(
        model_name: str = None,
        temperature: float = 0.7,
        top_p: float = 0.95,
        max_retries: int = 0,
        api_key: str = None, # Gemini用 (OpenAI系は設定から取得)
        generation_config: dict = None,
        force_google: bool = False,  # 内部処理用にGeminiを強制使用する場合True
        room_name: str = None,  # ルーム名（ルーム個別のプロバイダ設定を取得するため）
        internal_role: str = None  # [Phase 2] "processing", "summarization", "supervisor"
    ):
        """
        現在の設定(active_provider)に基づいて、適切なLangChain ChatModelインスタンスを生成して返す。
        
        Args:
            model_name: 使用するモデル名（internal_role指定時は省略可）
            temperature: 生成温度
            top_p: Top-P
            max_retries: リトライ回数（Agent側で制御するため基本0）
            api_key: Geminiを使用する場合のAPIキー
            generation_config: その他の生成設定（安全性設定など）
            force_google: Trueの場合、active_providerに関係なくGemini Nativeを使用。
                          内部処理（検索クエリ生成、情景描写等）はGemini固定のため。
                          ※internal_role指定時は無視される（後方互換用）
            room_name: ルーム名。指定するとルーム個別のプロバイダ設定を優先する。
            internal_role: [Phase 2] 内部処理のロール。"processing", "summarization", "supervisor"のいずれか。
                          指定すると、config.jsonの内部モデル設定に基づいてプロバイダとモデルを自動選択。
        """
        config_manager.load_config() 
        
        # --- [Phase 2] internal_role優先ロジック ---
        if internal_role:
            # config_managerから内部モデル設定を取得
            provider, internal_model_name = config_manager.get_effective_internal_model(internal_role)
            print(f"--- [LLM Factory] Internal role mode: {internal_role} ---")
            print(f"  - Provider: {provider}")
            print(f"  - Model: {internal_model_name}")
            
            # プロバイダに応じて処理を分岐
            if provider == "google":
                # api_key が未指定なら自動補完
                if not api_key:
                    api_key = config_manager.get_active_gemini_api_key(room_name)
                    
                if not api_key:
                    raise ValueError("Google provider requires an API key. No valid key found.")
                    
                return gemini_api.get_configured_llm(
                    model_name=internal_model_name,
                    api_key=api_key,
                    generation_config=generation_config or {}
                )
            elif provider == "zhipu":
                # [Phase 3] Zhipu AI (GLM-4) 対応
                zhipu_api_key = config_manager.ZHIPU_API_KEY
                if not zhipu_api_key:
                    raise ValueError("Zhipu AI provider requires an API key. Please set it in Settings.")
                
                print(f"--- [LLM Factory] Creating ZhipuAI client ---")
                return ChatOpenAI(
                    base_url="https://open.bigmodel.cn/api/paas/v4/",
                    api_key=zhipu_api_key,
                    model=internal_model_name,
                    temperature=temperature,
                    max_retries=max_retries,
                    streaming=True
                )
            elif provider == "groq":
                # [Phase 3b] Groq対応
                groq_api_key = config_manager.GROQ_API_KEY
                if not groq_api_key:
                    raise ValueError("Groq provider requires an API key. Please set it in Settings.")
                
                print(f"--- [LLM Factory] Creating Groq client ---")
                return ChatOpenAI(
                    base_url="https://api.groq.com/openai/v1",
                    api_key=groq_api_key,
                    model=internal_model_name,
                    temperature=temperature,
                    max_retries=max_retries,
                    streaming=True
                )
            elif provider == "local":
                # [Phase 3c] ローカルLLM対応 (llama-cpp-python)
                local_model_path = config_manager.LOCAL_MODEL_PATH
                if not local_model_path or not os.path.exists(local_model_path):
                    raise ValueError(f"Local LLM requires a valid GGUF model path. Current: '{local_model_path}'")
                
                print(f"--- [LLM Factory] Creating Local LLM client (llama.cpp) ---")
                print(f"  - Model path: {local_model_path}")
                
                try:
                    from langchain_community.chat_models import ChatLlamaCpp
                    return ChatLlamaCpp(
                        model_path=local_model_path,
                        temperature=temperature,
                        n_ctx=4096,  # コンテキスト長（設定可能にする余地あり）
                        n_gpu_layers=0,  # CPU版デフォルト（0=CPU、-1=全層GPU）
                        verbose=False
                    )
                except ImportError:
                    raise ValueError("llama-cpp-python is not installed. Run: pip install llama-cpp-python")
            else:
                # 未対応プロバイダ - エラーを投げる（フォールバックはPhase 4で実装）
                raise ValueError(f"Unsupported internal model provider: {provider}")
        
        # --- 以下は既存ロジック（internal_role未指定時） ---
        
        # モデル名から注釈（かっこ書き）を除去する
        # 例: "gemini-3-flash-preview (Slow Response)" -> "gemini-3-flash-preview"
        internal_model_name = model_name.split(" (")[0].strip() if model_name else model_name

        # ルーム名を渡してルーム個別のプロバイダ設定を優先する
        active_provider = config_manager.get_active_provider(room_name)
        
        # 【マルチモデル対応】内部処理用モデルは強制的にGemini APIを使用
        # ユーザー設定のプロバイダ（OpenAI等）に関係なく、Gemini固定が必要な処理用
        if force_google:
            print(f"--- [LLM Factory] Force Google mode: Using Gemini Native for internal processing ---")
            print(f"  - Model: {internal_model_name}")
            active_provider = "google"

        # --- Google Gemini (Native) ---
        if active_provider == "google":
            # api_key が未指定なら自動補完
            key_name_for_log = "Unknown"
            if not api_key:
                api_key = config_manager.get_active_gemini_api_key(room_name)
                # ログ用にキー名を取得
                key_name = config_manager.get_active_gemini_api_key_name(room_name)
                if key_name:
                    key_name_for_log = key_name
                
            if not api_key:
                raise ValueError("Google provider requires an API key. No valid key found.")

            # マスクされたキーを作成 (例: AIza...5678)
            masked_key = f"{api_key[:4]}...{api_key[-4:]}" if len(api_key) > 8 else "***"
            
            print(f"--- [LLM Factory] Initializing Gemini Model ---")
            print(f"  - Model: {internal_model_name}")
            print(f"  - API Key: {key_name_for_log} ({masked_key})")
                
            return gemini_api.get_configured_llm(
                model_name=internal_model_name,
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

    @staticmethod
    def create_chat_model_with_fallback(
        internal_role: str,
        room_name: str = None,
        temperature: float = 0.7,
        **kwargs
    ):
        """
        [Phase 4] フォールバック機構付きでチャットモデルを生成する。
        
        プライマリプロバイダでエラーが発生した場合、設定されたフォールバック順序に従って
        次のプロバイダを試行する。
        
        Args:
            internal_role: "processing", "summarization", "supervisor" のいずれか
            room_name: ルーム名
            temperature: 生成温度
            **kwargs: その他のオプション
            
        Returns:
            LangChain ChatModel インスタンス
            
        Raises:
            ValueError: すべてのプロバイダで失敗した場合
        """
        settings = config_manager.get_internal_model_settings()
        primary_provider = settings.get("provider", "google")
        fallback_enabled = settings.get("fallback_enabled", True)
        fallback_order = settings.get("fallback_order", ["google"])
        
        # 試行するプロバイダリストを構築（プライマリ + フォールバック順）
        providers_to_try = [primary_provider]
        if fallback_enabled:
            for fb_provider in fallback_order:
                if fb_provider != primary_provider and fb_provider not in providers_to_try:
                    providers_to_try.append(fb_provider)
        
        errors = []
        for provider in providers_to_try:
            try:
                # プロバイダを一時的に上書きして試行
                original_provider = settings.get("provider")
                settings["provider"] = provider
                config_manager.save_config_if_changed("internal_model_settings", settings)
                
                print(f"[LLM Factory] Trying provider: {provider}")
                model = LLMFactory.create_chat_model(
                    internal_role=internal_role,
                    room_name=room_name,
                    temperature=temperature,
                    **kwargs
                )
                
                # 成功したらプロバイダを元に戻す
                settings["provider"] = original_provider
                config_manager.save_config_if_changed("internal_model_settings", settings)
                
                return model
                
            except Exception as e:
                error_msg = f"{provider}: {str(e)}"
                errors.append(error_msg)
                print(f"[LLM Factory] Fallback: Provider '{provider}' failed: {e}")
                continue
        
        # すべてのプロバイダで失敗
        raise ValueError(f"All providers failed: {'; '.join(errors)}")