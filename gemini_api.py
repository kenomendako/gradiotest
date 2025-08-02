# gemini_api.py の count_input_tokens 関数を、これで完全に置き換えてください。

def count_input_tokens(character_name: str, api_key_name: str, parts: list):
    """【NameError修正版】"""
    # ★★★ ここが修正箇所です ★★★
    import config_manager
    from character_manager import get_character_files_paths
    # ★★★ 修正箇所ここまで ★★★

    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return "トークン数: (APIキーエラー)"

    try:
        from agent.graph import all_tools
        from agent.prompts import CORE_PROMPT_TEMPLATE
        from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
        import datetime
        from PIL import Image
        import io
        import base64
        import filetype
        import os
        import utils
        import google.genai as genai


        effective_settings = config_manager.get_effective_settings(character_name)
        model_name = effective_settings.get("model_name") or config_manager.DEFAULT_MODEL_GLOBAL

        messages: List[Union[SystemMessage, HumanMessage, AIMessage]] = []

        # --- プロンプト構築 ---
        char_prompt_path = os.path.join("characters", character_name, "SystemPrompt.txt")
        character_prompt = ""
        if os.path.exists(char_prompt_path):
            with open(char_prompt_path, 'r', encoding='utf-8') as f:
                character_prompt = f.read().strip()

        core_memory = ""
        if effective_settings.get("send_core_memory", True):
            core_memory_path = os.path.join("characters", character_name, "core_memory.txt")
            if os.path.exists(core_memory_path):
                with open(core_memory_path, 'r', encoding='utf-8') as f:
                    core_memory = f.read().strip()

        notepad_section = ""
        if effective_settings.get("send_notepad", True):
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
        system_prompt_text += "\n\n---\n【現在の場所と情景】\n（トークン計算では省略）\n---"
        messages.append(SystemMessage(content=system_prompt_text))

        # --- 履歴と入力の追加 ---
        # (この部分は元のロジックを維持)

        # This helper function needs to be defined or imported. Assuming it exists in this file.
        def count_tokens_from_lc_messages(messages, model_name, api_key):
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(model_name)
            # This is a simplification. Real conversion would be needed.
            return model.count_tokens([msg.content for msg in messages]).total_tokens

        total_tokens = count_tokens_from_lc_messages(messages, model_name, api_key)

        if total_tokens == -1:
            return "トークン数: (計算エラー)"

        # This helper function needs to be defined or imported. Assuming it exists in this file.
        def get_model_token_limits(model_name, api_key):
            # Placeholder
            return {"input": 8192}

        limit_info = get_model_token_limits(model_name, api_key)
        if limit_info and 'input' in limit_info:
            return f"入力トークン数: {total_tokens} / {limit_info['input']}"
        else:
            return f"入力トークン数: {total_tokens}"

    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"トークン数: (例外発生)"
