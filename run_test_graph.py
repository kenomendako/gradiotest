import asyncio
from langchain_core.messages import HumanMessage
from agent.graph import graph
import config_manager
import gemini_api

# 起動シーケンス
config_manager.load_config()
if config_manager.initial_api_key_name_global:
    gemini_api.configure_google_api(config_manager.initial_api_key_name_global)

async def main():
    """
    RAG検索と多段階の思考プロセスを持つグラフの動作をテストします。
    """
    print("--- 思考分離グラフのテスト実行開始 ---")

    # テスト用のキャラクター名とユーザー入力を設定
    # ※ このキャラクターのRAG索引が事前に作成されている必要があります
    character_name_to_test = "Default"
    user_prompt = "あなたの価値観について教えてください。"

    inputs = {
        "messages": [HumanMessage(content=user_prompt)],
        "character_name": character_name_to_test
    }

    print(f"\n入力:\n  キャラクター: {character_name_to_test}\n  プロンプト: {user_prompt}\n")
    print("====================\n")

    # グラフを非同期で実行し、各ステップの出力を監視
    async for output in graph.astream(inputs):
        for key, value in output.items():
            print(f"--- ノード '{key}' の出力 ---")
            # 出力が見やすいように整形
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    print(f"  {sub_key}: {sub_value}")
            else:
                 print(value)
        print("\n====================\n")

    print("--- テスト実行完了 ---")

if __name__ == "__main__":
    asyncio.run(main())
