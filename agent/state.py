from typing import List, Annotated, TypedDict
from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages

# LangGraphの各ノード間で受け渡される「状態」を定義します。
# まずは会話履歴(messages)のみを管理します。
class AgentState(TypedDict):
    messages: Annotated[List[AnyMessage], add_messages]
