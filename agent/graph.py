# agent/graph.py の、内容を、以下の、最終版で、完全に、置き換えてください

import os
import traceback
from typing import TypedDict, Annotated, List, Literal
from langchain_core.messages import SystemMessage, HumanMessage, BaseMessage, ToolMessage, AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END, START, add_messages
from datetime import datetime

# LangGraphの標準的なツール実行ノードをインポート
from langgraph.prebuilt import ToolNode

from agent.prompts import ACTOR_PROMPT_TEMPLATE
from tools.space_tools import set_current_location, find_location_id_by_name
from tools.memory_tools import read_memory_by_path, edit_memory, add_secret_diary_entry, summarize_and_save_core_memory, read_full_memory
from tools.notepad_tools import add_to_notepad, update_notepad, delete_from_notepad, read_full_notepad
from tools.web_tools import web_search_tool, read_url_tool
from tools.image_tools import generate_image
from rag_manager import diary_search_tool, conversation_memory_search_tool

# --- 1. ツール定義 ---
# task_complete_tool は廃止
all_tools = [
    set_current_location, find_location_id_by_name, read_memory_by_path, edit_memory,
    add_secret_diary_entry, summarize_and_save_core_memory, add_to_notepad,
    update_notepad, delete_from_notepad, read_full_notepad, web_search_tool,
    read_url_tool, diary_search_tool, conversation_memory_search_tool,
    generate_image, read_full_memory
]

# --- 2. 状態定義 ---
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    character_name: str
    api_key: str
    tavily_api_key: str
    model_name: str
    system_prompt: SystemMessage
    # task_complete フラグは廃止

# --- 3. モデル初期化 ---
def get_configured_llm(model_name: str, api_key: str):
    return ChatGoogleGenerativeAI(model=model_name, google_api_key=api_key, convert_system_message_to_human=False)

# --- 4. グラフのノード定義 ---
def context_generator_node(state: AgentState):
    print("--- コンテキスト生成ノード (context_generator_node) 実行 ---")
    character_name = state['character_name']
    api_key = state['api_key']
    scenery_text = "（現在の場所の情景描写は、取得できませんでした）"
    try:
        # このノードのロジックは変更なし
        llm_flash = get_configured_llm("gemini-1.5-flash-latest", api_key) # モデル名を最新版に更新
        location_from_file = "living_space"
        try:
            location_file_path = os.path.join("characters", character_name, "current_location.txt")
            if os.path.exists(location_file_path):
                with open(location_file_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content: location_from_file = content
        except Exception as e: print(f"  - 警告: 現在地ファイル読込エラー: {e}")

        found_id_result = find_location_id_by_name.invoke({"location_name": location_from_file, "character_name": character_name})
        # find_location_id_by_name が返すのはID文字列そのものか、エラーメッセージ
        if not found_id_result.startswith("【Error】"):
             space_def = read_memory_by_path.invoke({"path": f"living_space.{found_id_result}", "character_name": character_name})
        else:
             space_def = read_memory_by_path.invoke({"path": f"living_space.{location_from_file}", "character_name": character_name})


        if "【Error】" not in space_def and "エラー" not in space_def:
            now = datetime.now()
            scenery_prompt = f"空間定義:{space_def}\n時刻:{now.strftime('%H:%M')}\n季節:{now.month}月\n以上の情報から2-3文で、人物描写を排し気温・湿度・音・匂い・感触まで伝わるような精緻で写実的な情景を描写:"
            scenery_text = llm_flash.invoke(scenery_prompt).content
            print(f"  - 生成された情景描写: {scenery_text}")
        else:
            print(f"  - 警告: 場所「{location_from_file}」の定義が見つかりません。")

    except Exception as e:
        print(f"--- 警告: 情景描写の生成中にエラーが発生しました ---\n{traceback.format_exc()}")

    char_prompt_path = os.path.join("characters", character_name, "SystemPrompt.txt")
    core_memory_path = os.path.join("characters", character_name, "core_memory.txt")
    character_prompt = ""
    if os.path.exists(char_prompt_path):
        with open(char_prompt_path, 'r', encoding='utf-8') as f: character_prompt = f.read().strip()
    core_memory = ""
    if os.path.exists(core_memory_path):
        with open(core_memory_path, 'r', encoding='utf-8') as f: core_memory = f.read().strip()

    # 安全なフォーマット
    class SafeDict(dict):
        def __missing__(self, key):
            return f'{{{key}}}'
    prompt_vars = {
        'character_name': character_name,
        'character_prompt': character_prompt,
        'core_memory': core_memory
    }
    formatted_actor_prompt = ACTOR_PROMPT_TEMPLATE.format_map(SafeDict(prompt_vars))
    final_system_prompt_text = f"{formatted_actor_prompt}\n---\n【現在の情景】\n{scenery_text}\n---"

    return {"system_prompt": SystemMessage(content=final_system_prompt_text)}

def agent_node(state: AgentState):
    """思考と計画を担当するノード"""
    print("--- エージェントノード (agent_node) 実行 ---")
    llm = get_configured_llm(state['model_name'], state['api_key'])

    # ★★★ Tavily APIキーをツールにバインドする準備 ★★★
    llm_with_tools = llm.bind_tools(all_tools)

    # システムプロンプトとメッセージ履歴を結合
    messages_for_agent = [state['system_prompt']] + state['messages']

    # ★★★ web_search_tool に Tavily API キーを渡すための特別な処理は不要 ★★★
    # bind_tools が引数を自動で解決してくれるため、tool_executor側で処理する

    response = llm_with_tools.invoke(messages_for_agent)
    return {"messages": [response]}

# ★★★ tool_executor_node は LangGraph の ToolNode に置き換えるため不要 ★★★
# def tool_executor_node(state: AgentState): ...

def final_response_node(state: AgentState):
    """最終応答を生成するノード"""
    print("--- 応答生成ノード (final_response_node) 実行 ---")
    llm = get_configured_llm(state['model_name'], state['api_key'])
    messages_for_response = [state['system_prompt']] + state['messages']
    response = llm.invoke(messages_for_response)
    return {"messages": [response]}

# --- 5. ルーターの定義 (新しい形式) ---
def router(state: AgentState) -> Literal["__end__", "tool_node"]:
    """AIの応答にツール呼び出しが含まれているかどうかに基づいて、次にどこへ進むかを決定する。"""
    print("--- ルーター (router) 実行 ---")
    # 状態から最後のメッセージを取得
    last_message = state["messages"][-1]
    # 最後のメッセージにツール呼び出しがあるかチェック
    if not last_message.tool_calls:
        print("  - ツール呼び出しなし。思考完了と判断し、グラフを終了します。")
        return "__end__" # LangGraph v0.2.0以降では "end" ではなく "__end__" を推奨

    print("  - ツール呼び出しあり。ツール実行ノードへ。")
    # ツール呼び出しがあれば、ツール実行ノードへ
    return "tool_node"

# --- 6. グラフ構築 (新しい形式) ---
workflow = StateGraph(AgentState)

# ノードを追加
workflow.add_node("context_generator", context_generator_node)
workflow.add_node("agent", agent_node)
# LangGraph標準のToolNodeを使用
tool_node = ToolNode(all_tools)
workflow.add_node("tool_node", tool_node)
# final_response_nodeは、AIがツールを使わない場合に直接呼ばれることはなくなったため、削除しても良いが、
# 将来的な拡張性のために残すこともできる。今回はシンプルにするため、一旦コメントアウト。
# workflow.add_node("final_response_node", final_response_node)


# エッジ（処理の流れ）を定義
workflow.add_edge(START, "context_generator")
workflow.add_edge("context_generator", "agent")

# agentノードの後に、新しいルーターを条件付きエッジとして追加
workflow.add_conditional_edges(
    "agent",
    router,
    # ルーターの返す文字列と、次に向かうべきノード名をマッピング
    {
        "tool_node": "tool_node",
        "__end__": END
    }
)

# ツール実行後、再びエージェントノードに戻って次の思考を促す
workflow.add_edge("tool_node", "agent")

# コンパイル
app = workflow.compile()
print("--- 最終版v21：LangGraph標準のルーターとToolNodeを導入した最終グラフがコンパイルされました ---")
