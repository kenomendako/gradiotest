# tests/test_gemini_3_flash_long_context.py
"""
Gemini 3 Flash Preview で長いコンテキストを送信した場合のテスト。
実際のNexus Arkの使用状況に近い条件でテストします。
"""

import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config_manager

def generate_long_context(length_chars: int = 50000) -> str:
    """指定した文字数程度の長いコンテキストを生成"""
    base_text = """
これは長いコンテキストをシミュレートするためのテキストです。
ユーザーはAIとの会話を楽しんでおり、様々な話題について質問したり、
日常的な出来事を共有したりしています。
AIは親しみやすく、知的で、ユーザーの気持ちに寄り添った応答を心がけています。
時には冗談を言い、時には深い話をし、ユーザーとの絆を深めています。
"""
    # 必要な長さになるまでテキストを繰り返す
    repeated = base_text * (length_chars // len(base_text) + 1)
    return repeated[:length_chars]


def test_with_long_context(api_key: str, context_chars: int = 50000, model_name: str = "gemini-3-flash-preview"):
    """長いコンテキストでテスト"""
    print("\n" + "="*60)
    print(f"【テスト】長いコンテキスト ({context_chars:,} 文字)")
    print(f"  モデル: {model_name}")
    print("="*60)
    
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI, HarmCategory, HarmBlockThreshold
        from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
        
        llm = ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key,
            temperature=1.0,
            max_retries=0,
            timeout=600,  # 10分のタイムアウト
            safety_settings={
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }
        )
        
        # 長いシステムプロンプトを作成
        long_context = generate_long_context(context_chars)
        
        messages = [
            SystemMessage(content=f"あなたは親しみやすいAIアシスタントです。\n\n以下は過去の会話履歴です：\n{long_context}"),
            HumanMessage(content="こんにちは！今日の調子はどうですか？"),
        ]
        
        print(f"  タイムアウト設定: 600秒 (10分)")
        print(f"  システムプロンプト長: {len(messages[0].content):,} 文字")
        print(f"  リクエスト送信中...")
        
        start_time = time.time()
        chunks_received = 0
        full_response = ""
        first_chunk_time = None
        
        # ストリーミングで呼び出し
        for chunk in llm.stream(messages):
            if first_chunk_time is None:
                first_chunk_time = time.time() - start_time
                print(f"  最初のチャンク受信: {first_chunk_time:.2f} 秒後")
            
            chunks_received += 1
            if chunk.content:
                full_response += chunk.content
        
        elapsed = time.time() - start_time
        
        print(f"\n  ✅ 成功!")
        print(f"  総応答時間: {elapsed:.2f} 秒")
        print(f"  最初のチャンクまで: {first_chunk_time:.2f} 秒")
        print(f"  受信チャンク数: {chunks_received}")
        print(f"  応答内容: {full_response[:200] if full_response else '(空)'}")
        
        return True
        
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n  ❌ エラー発生!")
        print(f"  経過時間: {elapsed:.2f} 秒")
        print(f"  エラー種別: {type(e).__name__}")
        print(f"  エラー内容: {e}")
        traceback.print_exc()
        return False


def main():
    print("\n" + "#"*60)
    print("# Gemini 3 Flash Preview 長いコンテキストテスト")
    print("#"*60)
    
    config_manager.load_config()
    
    api_key = None
    for key_name, key_value in config_manager.GEMINI_API_KEYS.items():
        if key_value and not key_value.startswith("YOUR_API_KEY"):
            api_key = key_value
            print(f"\n使用するAPIキー: {key_name}")
            break
    
    if not api_key:
        print("\n❌ 有効なAPIキーが見つかりません。")
        return
    
    # 段階的にコンテキストサイズを増やしてテスト
    context_sizes = [10000, 50000, 100000]
    
    for size in context_sizes:
        result = test_with_long_context(api_key, size)
        if not result:
            print(f"\n⚠️ {size:,} 文字で失敗しました。これ以上のテストを中止します。")
            break
        print("")
    
    # 比較: Gemini 2.5 Flash でも同じテスト
    print("\n" + "="*60)
    print("【比較】Gemini 2.5 Flash で同じテスト")
    print("="*60)
    test_with_long_context(api_key, 50000, "gemini-2.5-flash")


if __name__ == "__main__":
    main()
