from langgraph.graph import StateGraph, END
from .state import AgentState
from langchain_core.messages import AIMessage

# エージェントの思考プロセスの一部となる「ノード」を定義します。
def parrot_node(state: AgentState):
    """
    受け取ったメッセージをそのままオウム返しするだけのシンプルなノード。
    LangGraphの基本動作を確認するために使用します。
    """
    # 現在のメッセージ履歴を取得します
    messages = state['messages']
    # 最後のメッセージを取得します
    last_message = messages[-1]

    # AIからの応答として、最後のメッセージをそのまま返します
    # LangGraphでは、ノードは状態を更新するための辞書を返す必要があります。
    return {"messages": [AIMessage(content=f"オウム返し： {last_message.content}")]}

# グラフの定義を開始します
builder = StateGraph(AgentState)

# "parrot"という名前でノードをグラフに追加します
builder.add_node("parrot", parrot_node)

# エントリーポイント（最初に呼ばれるノード）を"parrot"に設定します
builder.set_entry_point("parrot")

# "parrot"ノードが呼ばれたら、処理を終了(END)するようにエッジ（繋がり）を設定します
builder.add_edge("parrot", END)

# これまでの定義を元に、実行可能なグラフをコンパイルします
graph = builder.compile()
