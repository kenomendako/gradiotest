# -*- coding: utf-8 -*-
from langgraph.graph import StateGraph, END
from typing import TypedDict, Annotated
import os

# グラフの状態を定義
class GraphState(TypedDict):
    user_input: str
    processed_message: str # アノテーションを修正

# ノードの定義
def process_input_node(state: GraphState) -> GraphState:
    """ユーザー入力を受け取り、固定メッセージを付加するノード"""
    user_input = state["user_input"]
    # processed_message = f"{user_input} Hello, LangGraph!" # この行は不要になる
    # GraphStateのprocessed_messageは、実際にはprocess_input_nodeの返り値によって設定されるため、
    # ここで直接 state['processed_message'] を更新するのではなく、
    # 返り値の辞書に含めることで GraphState が更新される。
    # しかし、今回のケースでは Annotated を使わないので、単純に文字列結合を行う。
    new_processed_message = f"{user_input} Hello, LangGraph!"
    print(f"Node executed: process_input_node, input: '{user_input}', output: '{new_processed_message}'")
    return {"user_input": user_input, "processed_message": new_processed_message} # user_inputも返すようにする

def build_graph():
    """LangGraphのグラフを構築する"""
    workflow = StateGraph(GraphState)

    # ノードを追加
    workflow.add_node("process_input", process_input_node)

    # エッジを追加 (エントリーポイントからノードへ、ノードから終了へ)
    workflow.set_entry_point("process_input")
    workflow.add_edge("process_input", END)

    # グラフをコンパイル
    graph = workflow.compile()
    print("Graph compiled successfully.")
    return graph

def run_test_graph(input_message: str):
    """テストグラフを実行し、結果を表示する"""
    graph = build_graph()
    inputs = {"user_input": input_message}
    print(f"Running graph with input: {inputs}")
    result = graph.invoke(inputs)
    print(f"Graph execution result: {result}")
    return result.get("processed_message")

if __name__ == "__main__":
    # このスクリプトが直接実行された場合のテストコード
    print("--- Running rag_graph.py test ---")
    test_input = "ユーザーからの最初のメッセージです。"
    output = run_test_graph(test_input)
    expected_output = f"{test_input} Hello, LangGraph!"
    assert output == expected_output, f"Test failed! Expected '{expected_output}', got '{output}'"
    print(f"Test successful! Input: '{test_input}', Output: '{output}'")
    print("--- rag_graph.py test finished ---")
