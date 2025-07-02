from typing import List, Annotated, TypedDict
from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages

# LangGraphの各ノード間で受け渡される「状態」を定義します。
class AgentState(TypedDict):
    messages: Annotated[List[AnyMessage], add_messages]
    rag_chunks: List[str]
    reflection: str
    character_name: str
    chat_history: str
    system_prompt: str
    api_history_limit_option: str
