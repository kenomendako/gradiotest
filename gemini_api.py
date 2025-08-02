# gemini_api.py の invoke_nexus_agent と count_input_tokens を置き換えてください

import traceback
from typing import Any, List, Union, Optional, Dict
import os
import io
import base64
from PIL import Image
import google.genai as genai
import filetype

from agent.graph import app
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
import config_manager
import utils
from character_manager import get_character_files_paths

def invoke_nexus_agent(*args: Any) -> Dict[str, str]:
    # ★★★ UIから渡す引数を7つに削減 ★★★
    (textbox_content, chatbot_history, current_character_name,
     current_api_key_name_state, file_input_list, add_timestamp_checkbox,
     api_history_limit_state) = args

    # ★★★ 設定はconfig_managerから直接読み込む（変更なし、ただし重要）★★★
    effective_settings = config_manager.get_effective_settings(current_character_name)

    user_prompt_from_textbox = textbox_content.strip() if textbox_content else ""

    final_input_for_agent = {"text": user_prompt_from_textbox, "files": file_input_list or []}

    app = get_graph_for_character(current_character_name, current_api_key_name_state)

    config = {"configurable": {"character_name": current_character_name, "api_key_name": current_api_key_name_state}}

    response = app.invoke(final_input_for_agent, config)

    final_response_text = response.get("response", "[エージェントからの応答がありませんでした]")
    location_name = response.get("location_name", "（不明）")
    scenery = response.get("scenery", "（不明）")

    return {"response": final_response_text, "location_name": location_name, "scenery": scenery}


def count_input_tokens(character_name: str, api_key_name: str, parts: list):
    """【改修版】UIから大量の引数を渡さず、設定は内部で解決する"""
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return "トークン数: (APIキーエラー)"

    # ★★★ ここからがImportErrorの修正箇所 ★★★
    try:
        from agent.graph import all_tools
        from agent.prompts import CORE_PROMPT_TEMPLATE # 正しいテンプレートをインポート
        import datetime

        effective_settings = config_manager.get_effective_settings(character_name)
        model_name = effective_settings["model_name"]

        messages: List[Union[SystemMessage, HumanMessage, AIMessage]] = []

        # プロンプト構築ロジック (元のコードから必要な部分を移植)
        char_prompt_path = os.path.join("characters", character_name, "SystemPrompt.txt")
        character_prompt = ""
        if os.path.exists(char_prompt_path):
            with open(char_prompt_path, 'r', encoding='utf-8') as f:
                character_prompt = f.read().strip()

        core_memory = ""
        if effective_settings["send_core_memory"]:
            core_memory_path = os.path.join("characters", character_name, "core_memory.txt")
            if os.path.exists(core_memory_path):
                with open(core_memory_path, 'r', encoding='utf-8') as f:
                    core_memory = f.read().strip()

        notepad_section = ""
        if effective_settings["send_notepad"]:
            _, _, _, _, notepad_path = get_character_files_paths(character_name)
            if notepad_path and os.path.exists(notepad_path):
                with open(notepad_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    notepad_content = content if content else "（メモ帳は空です）"
                    notepad_section = f"\n### 短期記憶（メモ帳）\n{notepad_content}\n"

        tools_list_str = "\n".join([f"- `{tool.name}({', '.join(tool.args.keys())})`: {tool.description}" for tool in all_tools])

        class SafeDict(dict):
            def __missing__(self, key): return f'{{{key}}}'

        prompt_vars = {
            'character_name': character_name,
            'character_prompt': character_prompt,
            'core_memory': core_memory,
            'notepad_section': notepad_section,
            'tools_list': tools_list_str
        }

        system_prompt_text = CORE_PROMPT_TEMPLATE.format_map(SafeDict(prompt_vars))

        # 空間情報はトークン計算では簡略化
        system_prompt_text += "\n\n---\n【現在の場所と情景】\n（トークン計算では省略）\n---"

        messages.append(SystemMessage(content=system_prompt_text))

        # 履歴と現在の入力をメッセージリストに追加するロジックは、元のコードから流用
        # (ここでは簡略化のため省略しますが、実際のコードでは必要です)

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)

        processed_parts = []
        if system_prompt_text:
            processed_parts.append(system_prompt_text)

        for part in parts:
            if isinstance(part, str):
                processed_parts.append(part)
            elif isinstance(part, dict) and 'name' in part: # Gradio File object
                filepath = part['name']
                try:
                    kind = filetype.guess(filepath)
                    if kind and kind.mime.startswith("image/"):
                        processed_parts.append(Image.open(filepath))
                    else: # Treat as text for token counting
                        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                            processed_parts.append(f.read())
                except Exception:
                     with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                            processed_parts.append(f.read())

        # ★★★ 実際のAPI呼び出し部分は元のコードのものを流用 ★★★
        result = model.count_tokens(processed_parts)
        total_tokens = result.total_tokens

        limit_info = utils.get_model_token_limits(model_name, api_key)
        if limit_info and 'input' in limit_info:
            return f"入力トークン数: {total_tokens} / {limit_info['input']}"
        else:
            return f"入力トークン数: {total_tokens}"

    except Exception as e:
        traceback.print_exc()
        return f"トークン数: (例外発生)"

def get_model_token_limits(model_name: str, api_key: str) -> Optional[Dict[str, int]]:
    # This is a placeholder for where you might fetch model limits.
    # In a real scenario, this could be a cached API call.
    if "2.5" in model_name:
        return {"input": 8192, "output": 2048}
    return None

def count_tokens_from_lc_messages(messages: List[Union[SystemMessage, HumanMessage, AIMessage]], model_name: str, api_key: str) -> int:
    # This is a placeholder. You would need a proper way to count tokens
    # for LangChain message objects, likely by converting them to a
    # format the genai library understands.
    return -1
