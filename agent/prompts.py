# agent/prompts.py

CORE_PROMPT_TEMPLATE = """
## 思考の表現ルール
# ... (前略) ...

{character_prompt}

### コアメモリ：自己同一性の核
{core_memory}
{notepad_section}
---
## 利用可能なツールと、その活用ルール
{tools_list}
"""
