from typing import List, Annotated, TypedDict
from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages

# LangGraphの各ノード間で受け渡される「状態」を定義します。
class AgentState(TypedDict):
    # messages: これまでの会話履歴
    messages: Annotated[List[AnyMessage], add_messages]

    # rag_chunks: RAG検索によって取得された、関連性の高い記憶の断片
    rag_chunks: List[str]

    # reflection: 応答の骨子やテーマなど、AIが内省した結果
    reflection: str

    # character_name: 現在対話しているキャラクターの名前
    character_name: str
