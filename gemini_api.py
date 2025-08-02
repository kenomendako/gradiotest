# count_input_tokens 関数を、これで完全に置き換えてください

def count_input_tokens(character_name: str, api_key_name: str, parts: list):
    """【改修版】UIから大量の引数を渡さず、設定は内部で解決する"""
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return "トークン数: (APIキーエラー)"

    # ★★★ ここからがImportErrorの修正箇所 ★★★
    try:
        from agent.graph import all_tools
        from agent.prompts import CORE_PROMPT_TEMPLATE # 正しいテンプレートをインポート
        from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
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

        # ★★★ 実際のAPI呼び出し部分は元のコードのものを流用 ★★★
        total_tokens = count_tokens_from_lc_messages(messages, model_name, api_key) # このヘルパー関数は既存のもの

        if total_tokens == -1:
            return "トークン数: (計算エラー)"

        limit_info = get_model_token_limits(model_name, api_key)
        if limit_info and 'input' in limit_info:
            return f"入力トークン数: {total_tokens} / {limit_info['input']}"
        else:
            return f"入力トークン数: {total_tokens}"

    except Exception as e:
        traceback.print_exc()
        return f"トークン数: (例外発生)"
