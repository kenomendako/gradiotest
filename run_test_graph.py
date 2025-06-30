import asyncio
from langchain_core.messages import HumanMessage
from agent.graph import graph

async def main():
    """
    作成した最小構成のLangGraphが正しく動作するかをテストします。
    """
    print("--- 最小構成グラフのテスト実行開始 ---")

    # ユーザーからの入力を模倣したデータを作成します
    inputs = {"messages": [HumanMessage(content="こんにちは、ルシアン")]}

    # グラフを非同期で実行します
    # .astream() は、グラフの各ステップの出力をリアルタイムでストリームとして返します。
    print(f"\n入力:\n{inputs}\n")
    print("====================\n")

    async for output in graph.astream(inputs):
        # すべてのノードの出力を、キーと値のペアで表示します
        for key, value in output.items():
            print(f"ノード '{key}' の出力:")
            print("---")
            print(value)
        print("\n====================\n")

    print("--- テスト実行完了 ---")

if __name__ == "__main__":
    # 非同期関数mainを実行します
    asyncio.run(main())
