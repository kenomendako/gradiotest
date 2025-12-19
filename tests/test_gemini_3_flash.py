# tests/test_gemini_3_flash.py
"""
Gemini 3 Flash Preview のタイムアウト問題をデバッグするためのシンプルなテストスクリプト。

使い方:
    python tests/test_gemini_3_flash.py

このスクリプトは以下をテストします:
1. Google GenAI SDK を直接使用したAPI呼び出し（タイムアウト設定付き）
2. LangChain を使用したAPI呼び出し（タイムアウト設定付き）
3. 応答時間とエラーの詳細なログ
"""

import os
import sys
import time
import traceback

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config_manager

def test_with_google_genai_sdk(api_key: str, model_name: str = "gemini-3-flash-preview"):
    """Google GenAI SDK を直接使用してテスト（推奨タイムアウト設定付き）"""
    print("\n" + "="*60)
    print(f"【テスト1】Google GenAI SDK 直接呼び出し")
    print(f"  モデル: {model_name}")
    print("="*60)
    
    try:
        import google.genai as genai
        from google.genai import types
        
        # クライアント作成（タイムアウト設定）
        # httpx のデフォルトタイムアウトは通常 5秒なので、長めに設定
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=300.0  # 5分のタイムアウト
            )
        )
        
        print("  タイムアウト設定: 300秒 (5分)")
        print("  リクエスト送信中...")
        
        start_time = time.time()
        
        # シンプルなプロンプトでテスト
        response = client.models.generate_content(
            model=f"models/{model_name}",
            contents="こんにちは！今日の調子はどうですか？一言で答えてください。",
            config=types.GenerateContentConfig(
                temperature=1.0,  # Gemini 3 推奨値
                max_output_tokens=100
            )
        )
        
        elapsed = time.time() - start_time
        
        print(f"\n  ✅ 成功!")
        print(f"  応答時間: {elapsed:.2f} 秒")
        print(f"  応答内容: {response.text[:200] if response.text else '(空)'}")
        
        return True
        
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n  ❌ エラー発生!")
        print(f"  経過時間: {elapsed:.2f} 秒")
        print(f"  エラー種別: {type(e).__name__}")
        print(f"  エラー内容: {e}")
        traceback.print_exc()
        return False


def test_with_langchain(api_key: str, model_name: str = "gemini-3-flash-preview"):
    """LangChain を使用してテスト（タイムアウト設定付き）"""
    print("\n" + "="*60)
    print(f"【テスト2】LangChain ChatGoogleGenerativeAI")
    print(f"  モデル: {model_name}")
    print("="*60)
    
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI, HarmCategory, HarmBlockThreshold
        from langchain_core.messages import HumanMessage
        
        # LangChain の ChatGoogleGenerativeAI 作成
        # request_timeout を設定（これが httpx のタイムアウトに渡される）
        llm = ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key,
            temperature=1.0,  # Gemini 3 推奨値
            max_retries=0,
            max_output_tokens=100,
            timeout=300,  # 5分のタイムアウト（秒）
            safety_settings={
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }
        )
        
        print("  タイムアウト設定: 300秒 (5分)")
        print("  リクエスト送信中...")
        
        start_time = time.time()
        
        # invoke で呼び出し
        response = llm.invoke([HumanMessage(content="こんにちは！今日の調子はどうですか？一言で答えてください。")])
        
        elapsed = time.time() - start_time
        
        print(f"\n  ✅ 成功!")
        print(f"  応答時間: {elapsed:.2f} 秒")
        print(f"  応答内容: {response.content[:200] if response.content else '(空)'}")
        
        return True
        
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n  ❌ エラー発生!")
        print(f"  経過時間: {elapsed:.2f} 秒")
        print(f"  エラー種別: {type(e).__name__}")
        print(f"  エラー内容: {e}")
        traceback.print_exc()
        return False


def test_with_langchain_stream(api_key: str, model_name: str = "gemini-3-flash-preview"):
    """LangChain のストリーミングを使用してテスト"""
    print("\n" + "="*60)
    print(f"【テスト3】LangChain Streaming")
    print(f"  モデル: {model_name}")
    print("="*60)
    
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI, HarmCategory, HarmBlockThreshold
        from langchain_core.messages import HumanMessage
        
        llm = ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key,
            temperature=1.0,
            max_retries=0,
            max_output_tokens=100,
            timeout=300,
            safety_settings={
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }
        )
        
        print("  タイムアウト設定: 300秒 (5分)")
        print("  ストリーミングリクエスト送信中...")
        
        start_time = time.time()
        chunks_received = 0
        full_response = ""
        
        # stream で呼び出し
        for chunk in llm.stream([HumanMessage(content="こんにちは！今日の調子はどうですか？一言で答えてください。")]):
            chunks_received += 1
            if chunk.content:
                full_response += chunk.content
                print(f"    チャンク {chunks_received}: {chunk.content[:50]}...")
        
        elapsed = time.time() - start_time
        
        print(f"\n  ✅ 成功!")
        print(f"  応答時間: {elapsed:.2f} 秒")
        print(f"  受信チャンク数: {chunks_received}")
        print(f"  完全な応答: {full_response[:200] if full_response else '(空)'}")
        
        return True
        
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n  ❌ エラー発生!")
        print(f"  経過時間: {elapsed:.2f} 秒")
        print(f"  エラー種別: {type(e).__name__}")
        print(f"  エラー内容: {e}")
        traceback.print_exc()
        return False


def test_comparison(api_key: str):
    """Gemini 3 Flash と Gemini 2.5 Flash を比較テスト"""
    print("\n" + "="*60)
    print("【テスト4】モデル比較テスト")
    print("="*60)
    
    models_to_test = [
        "gemini-3-flash-preview",
        "gemini-2.5-flash",
    ]
    
    for model in models_to_test:
        print(f"\n--- {model} ---")
        test_with_google_genai_sdk(api_key, model)


def main():
    print("\n" + "#"*60)
    print("# Gemini 3 Flash Preview タイムアウトデバッグテスト")
    print("#"*60)
    
    # 設定読み込み
    config_manager.load_config()
    
    # 有効なAPIキーを取得
    api_key = None
    for key_name, key_value in config_manager.GEMINI_API_KEYS.items():
        if key_value and not key_value.startswith("YOUR_API_KEY"):
            api_key = key_value
            print(f"\n使用するAPIキー: {key_name}")
            break
    
    if not api_key:
        print("\n❌ 有効なAPIキーが見つかりません。config.json を確認してください。")
        return
    
    # テスト実行
    results = {}
    
    # テスト1: Google GenAI SDK
    results["GenAI SDK"] = test_with_google_genai_sdk(api_key)
    
    # テスト2: LangChain invoke
    results["LangChain invoke"] = test_with_langchain(api_key)
    
    # テスト3: LangChain stream
    results["LangChain stream"] = test_with_langchain_stream(api_key)
    
    # テスト4: モデル比較
    print("\n" + "="*60)
    print("モデル比較テストをスキップします（手動で実行可能）")
    print("実行する場合: test_comparison(api_key)")
    print("="*60)
    
    # 結果サマリー
    print("\n" + "#"*60)
    print("# テスト結果サマリー")
    print("#"*60)
    for test_name, success in results.items():
        status = "✅ 成功" if success else "❌ 失敗"
        print(f"  {test_name}: {status}")


if __name__ == "__main__":
    main()
