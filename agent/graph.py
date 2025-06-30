import os
from langchain_core.messages import HumanMessage, AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END
import config_manager
from rag_manager import search_relevant_chunks
from .state import AgentState
from .prompts import REFLECTION_PROMPT_TEMPLATE, ANSWER_GENERATION_PROMPT_TEMPLATE

# --- ノードの定義 ---

def rag_search_node(state: AgentState):
    """
    ユーザーの最新のメッセージに基づいてRAG検索を実行し、関連する記憶の断片を取得するノード。
    """
    print("--- グラフ実行: rag_search_node ---")
    user_prompt = state["messages"][-1].content
    character_name = state["character_name"]

    relevant_chunks = search_relevant_chunks(character_name, user_prompt)
    print(f"RAG検索結果: {len(relevant_chunks)}件のチャンクを発見")

    return {"rag_chunks": relevant_chunks}

def reflection_node(state: AgentState):
    """
    RAG検索結果とユーザープロンプトを基に、応答の「骨子」を生成するノード。
    """
    print("--- グラフ実行: reflection_node ---")
    user_prompt = state["messages"][-1].content
    rag_chunks_str = "\n---\n".join(state["rag_chunks"])

    # プロンプトを組み立て
    prompt = REFLECTION_PROMPT_TEMPLATE.format(user_prompt=user_prompt, rag_chunks=rag_chunks_str)

    # 応答の骨子を考えるのは、最も高速・効率的なliteモデルで
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-lite", temperature=0.7, google_api_key=os.environ.get("GOOGLE_API_KEY"))

    # 応答の骨子を生成
    reflection_result = llm.invoke(prompt)
    print(f"応答の骨子: {reflection_result.content}")

    return {"reflection": reflection_result.content}

def answer_generation_node(state: AgentState):
    """
    生成された「骨子」と会話履歴を基に、最終的なAIの応答を生成するノード。
    """
    print("--- グラフ実行: answer_generation_node ---")
    reflection = state["reflection"]
    character_name = state["character_name"]

    # 会話履歴を整形
    history_str = "\n".join([f"{msg.type}: {msg.content}" for msg in state["messages"]])

    # プロンプトを組み立て
    prompt = ANSWER_GENERATION_PROMPT_TEMPLATE.format(
        character_name=character_name,
        reflection=reflection,
        chat_history=history_str
    )

    # 最終的な応答は、最新の高性能モデルで生成
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0.9, google_api_key=os.environ.get("GOOGLE_API_KEY"))

    final_response = llm.invoke(prompt)
    print(f"最終生成応答: {final_response.content}")

    # 新しい応答をmessagesに追加して返す
    return {"messages": [AIMessage(content=final_response.content)]}


# --- グラフの構築 ---

builder = StateGraph(AgentState)

# ノードをグラフに追加
builder.add_node("rag_search", rag_search_node)
builder.add_node("reflection", reflection_node)
builder.add_node("answer_generation", answer_generation_node)

# エッジ（ノード間の繋がり）を定義
builder.set_entry_point("rag_search")
builder.add_edge("rag_search", "reflection")
builder.add_edge("reflection", "answer_generation")
builder.add_edge("answer_generation", END)

# グラフをコンパイル
graph = builder.compile()
