import os
from langchain_core.messages import HumanMessage, AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import MemorySaver

from character_manager import get_character_files_paths
from rag_manager import search_relevant_chunks
from utils import load_chat_log
from .state import AgentState
from .prompts import REFLECTION_PROMPT_TEMPLATE, ANSWER_GENERATION_PROMPT_TEMPLATE

# --- ノードの定義 ---

def get_initial_state(inputs: dict):
    """
    グラフ実行の最初に呼ばれ、キャラクター名とシステムプロンプトを読み込む。
    """
    print("--- グラフ実行: get_initial_state ---")
    character_name = inputs["character_name"]

    system_prompt = "あなたは対話パートナーです。" # デフォルト値
    try:
        _, sys_prompt_path, _, _ = get_character_files_paths(character_name)
        if sys_prompt_path and os.path.exists(sys_prompt_path):
            with open(sys_prompt_path, 'r', encoding='utf-8') as f:
                system_prompt = f.read()
    except Exception as e:
        print(f"警告: {character_name}のシステムプロンプト読み込みに失敗: {e}")

    return {
        "messages": inputs["messages"],
        "character_name": character_name,
        "system_prompt": system_prompt,
        "api_history_limit_option": inputs["api_history_limit_option"]
    }

def prepare_history_node(state: AgentState):
    """
    過去のチャットログを整形して状態に追加するノード。
    """
    print("--- グラフ実行: prepare_history_node ---")
    character_name = state["character_name"]
    log_file_path, _, _, _ = get_character_files_paths(character_name)

    messages = load_chat_log(log_file_path, character_name)
    limit_option = state.get("api_history_limit_option", "all")
    if limit_option.isdigit():
        limit = int(limit_option)
        if len(messages) > limit * 2:
            messages = messages[-(limit*2):]

    history_str = "\n\n".join([f"## {msg.get('role', 'unknown')}:\n\n{msg.get('content', '')}" for msg in messages])

    return {"chat_history": history_str}

def rag_search_node(state: AgentState):
    """
    ユーザーの最新のメッセージに基づいてRAG検索を実行するノード。
    """
    print("--- グラフ実行: rag_search_node ---")
    user_prompt = state["messages"][-1].content
    character_name = state["character_name"]

    relevant_chunks = search_relevant_chunks(character_name, user_prompt)
    print(f"RAG検索結果: {len(relevant_chunks)}件のチャンクを発見")

    return {"rag_chunks": relevant_chunks}

def reflection_node(state: AgentState):
    """
    システムプロンプト、RAG検索結果、ユーザープロンプトを基に、応答の「骨子」を生成するノード。
    """
    print("--- グラフ実行: reflection_node ---")
    prompt = REFLECTION_PROMPT_TEMPLATE.format(
        system_prompt=state["system_prompt"],
        user_prompt=state["messages"][-1].content,
        rag_chunks="\n---\n".join(state["rag_chunks"])
    )

    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.7, google_api_key=os.environ.get("GOOGLE_API_KEY"))
    reflection_result = llm.invoke(prompt)
    print(f"応答の骨子: {reflection_result.content}")

    return {"reflection": reflection_result.content}

def answer_generation_node(state: AgentState):
    """
    システムプロンプト、骨子、会話履歴を基に、最終的なAIの応答を生成するノード。
    """
    print("--- グラフ実行: answer_generation_node ---")
    prompt = ANSWER_GENERATION_PROMPT_TEMPLATE.format(
        character_name=state["character_name"],
        system_prompt=state["system_prompt"],
        reflection=state["reflection"],
        chat_history=state["chat_history"]
    )

    llm = ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0.9, google_api_key=os.environ.get("GOOGLE_API_KEY"))
    final_response = llm.invoke(prompt)
    print(f"最終生成応答: {final_response.content}")

    return {"messages": [AIMessage(content=final_response.content)]}

# --- グラフの構築 ---

memory = MemorySaver()
builder = StateGraph(AgentState, checkpointer=memory)

# ノードをグラフに追加
builder.add_node("get_initial_state", get_initial_state)
builder.add_node("prepare_history", prepare_history_node)
builder.add_node("rag_search", rag_search_node)
builder.add_node("reflection", reflection_node)
builder.add_node("answer_generation", answer_generation_node)

# エッジ（ノード間の繋がり）を定義
builder.add_edge(START, "get_initial_state")
builder.add_edge("get_initial_state", "prepare_history")
builder.add_edge("get_initial_state", "rag_search")

builder.add_conditional_edges(
    "prepare_history",
    lambda x: "reflection",
    {"reflection": "reflection"}
)
builder.add_conditional_edges(
    "rag_search",
    lambda x: "reflection",
    {"reflection": "reflection"}
)

builder.add_edge("reflection", "answer_generation")
builder.add_edge("answer_generation", END)

# グラフをコンパイル
graph = builder.compile(checkpointer=memory)
