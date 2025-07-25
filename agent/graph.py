import os
import re
import traceback
from datetime import datetime
from langchain_core.messages import SystemMessage, ToolMessage
from .tools_definition import all_tools
from .langchain_chat_with_agent import get_configured_llm
from .agent_state import AgentState
from .memory_manager import find_location_id_by_name, read_memory_by_path

CORE_PROMPT_TEMPLATE = """
（ここからシステムプロンプト）
あなたは、{character_name}という名前のキャラクターとして応答を生成するAIです。

【キャラクター設定】
{character_prompt}

【行動指針】
- ユーザーからの入力に対し、上記の設定に基づいて自然で魅力的な応答を返してください。
- 応答には、キャラクターの口調、性格、背景を反映させてください。
- 以下のツールを必要に応じて使用し、キャラクターの行動や情報収集を行ってください。
- ユーザーに質問したり、会話を広げることもできます。

【コアメモリ】
キャラクターに関する記憶や、会話全体で維持すべき重要な情報です。
{core_memory}

【利用可能なツール】
{tools_list}
（システムプロンプトここまで）
"""

def context_generator_node(state: AgentState):
    print("--- コンテキスト生成ノード (context_generator_node) 実行 ---")
    character_name = state['character_name']
    api_key = state['api_key']
    scenery_text = "（現在の場所の情景描写は、取得できませんでした）"
    space_def = "（現在の場所の定義・設定は、取得できませんでした）" # ★★★ 1. space_defを初期化 ★★★

    try:
        location_to_describe = None
        last_tool_message = next((msg for msg in reversed(state['messages']) if isinstance(msg, ToolMessage)), None)
        if last_tool_message and "Success: Location set to" in last_tool_message.content:
            match = re.search(r"'(.*?)'", last_tool_message.content)
            if match:
                location_to_describe = match.group(1)
                print(f"  - ツール実行結果から最新の場所 '{location_to_describe}' を特定しました。")

        if not location_to_describe:
            try:
                location_file_path = os.path.join("characters", character_name, "current_location.txt")
                if os.path.exists(location_file_path):
                    with open(location_file_path, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                        if content:
                            location_to_describe = content
                            print(f"  - ファイルから現在の場所 '{location_to_describe}' を読み込みました。")
            except Exception as e:
                print(f"  - 警告: 現在地ファイル読込エラー: {e}")

        if not location_to_describe:
            location_to_describe = "living_space"
            print(f"  - 場所が特定できなかったため、デフォルトの '{location_to_describe}' を使用します。")

        llm_flash = get_configured_llm("gemini-1.5-flash", api_key)
        
        found_id_result = find_location_id_by_name.invoke({"location_name": location_to_describe, "character_name": character_name})
        id_to_use = location_to_describe
        if not found_id_result.startswith("Error:"):
            id_to_use = found_id_result
        
        # ★★★ 2. read_memory_by_pathの結果を space_def 変数に保持 ★★★
        space_def = read_memory_by_path.invoke({"path": f"living_space.{id_to_use}", "character_name": character_name})

        if not space_def.startswith("【Error】") and not space_def.startswith("Error:"):
            now = datetime.now()

            # ★★★ 3. scenery_prompt をご希望の内容に修正 ★★★
            # 修正案：より詩的で、五感を刺激するような指示に変更
            scenery_prompt = (
                f"空間定義:{space_def}\n"
                f"時刻:{now.strftime('%H:%M')} / 季節:{now.month}月\n\n"
                "以上の情報から、あなたは情景描写の専門家として、この空間の「今この瞬間」を切り取ってください。\n"
                "【ルール】\n"
                "- 人物やキャラクターの描写は絶対に含めないでください。\n"
                "- 2〜3文の簡潔な文章にまとめてください。\n"
                "- 気温、湿度、光と影、音、香り、空気の質感など、五感に訴えかける具体的な描写を重視してください。"
            )

            scenery_text = llm_flash.invoke(scenery_prompt).content
            print(f"  - 生成された情景描写: {scenery_text}")
        else:
            print(f"  - 警告: 場所「{location_to_describe}」(ID: {id_to_use}) の定義が見つかりません。")
            space_def = "（現在の場所の定義・設定は、取得できませんでした）" # エラー時にも初期化

    except Exception as e:
        print(f"--- 警告: 情景描写の生成中にエラーが発生しました ---\n{traceback.format_exc()}")

    # (中略... character_prompt, core_memory, tools_list_str の読み込みは変更なし)
    char_prompt_path = os.path.join("characters", character_name, "SystemPrompt.txt")
    core_memory_path = os.path.join("characters", character_name, "core_memory.txt")
    character_prompt = ""
    if os.path.exists(char_prompt_path):
        with open(char_prompt_path, 'r', encoding='utf-8') as f: character_prompt = f.read().strip()
    core_memory = ""
    if state.get("send_core_memory", True):
        if os.path.exists(core_memory_path):
            with open(core_memory_path, 'r', encoding='utf-8') as f:
                core_memory = f.read().strip()

    tools_list_str = "\n".join([f"- `{tool.name}({', '.join(tool.args.keys())})`: {tool.description}" for tool in all_tools])

    class SafeDict(dict):
        def __missing__(self, key):
            return f'{{{key}}}'
            
    prompt_vars = {
        'character_name': character_name,
        'character_prompt': character_prompt,
        'core_memory': core_memory,
        'tools_list': tools_list_str
    }
    formatted_core_prompt = CORE_PROMPT_TEMPLATE.format_map(SafeDict(prompt_vars))
    
    # ★★★ 4. 最終的なシステムプロンプトに場所の定義・設定を追加 ★★★
    final_system_prompt_text = (
        f"{formatted_core_prompt}\n"
        "---\n"
        f"【現在の情景】\n{scenery_text}\n\n"
        f"【現在の場所の定義・設定】\n{space_def}\n"
        "---"
    )

    return {"system_prompt": SystemMessage(content=final_system_prompt_text)}
