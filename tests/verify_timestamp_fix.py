import re

def test_split_logic(original_content):
    thoughts_pattern = re.compile(r"(【Thoughts】[\s\S]*?【/Thoughts】)", re.IGNORECASE)
    # 修正後の正規表現
    timestamp_pattern = re.compile(r'(\d{4}-\d{2}-\d{2} \(...\) \d{2}:\d{2}:\d{2}(?: \| .*)?)$')

    thoughts_match = thoughts_pattern.search(original_content)
    timestamp_match = timestamp_pattern.search(original_content)

    thoughts_part = thoughts_match.group(1) if thoughts_match else ""
    timestamp_part = timestamp_match.group(1) if timestamp_match else ""

    body_part = original_content
    if thoughts_part: body_part = body_part.replace(thoughts_part, "")
    if timestamp_part: body_part = body_part.replace(timestamp_part, "")
    body_part = body_part.strip()

    return thoughts_part, body_part, timestamp_part

test_cases = [
    {
        "name": "Standard with model name",
        "content": "【Thoughts】\n思考内容\n【/Thoughts】\n本文です。\n\n2026-01-12 (Mon) 19:30:00 | gemini-1.5-flash"
    },
    {
        "name": "Standard without model name",
        "content": "本文です。\n\n2026-01-12 (Mon) 19:30:00"
    },
    {
        "name": "No newline before timestamp",
        "content": "本文です。2026-01-12 (Mon) 19:30:00"
    },
    {
        "name": "Single newline and model name",
        "content": "本文です。\n2026-01-12 (Mon) 19:30:00 | gpt-4o"
    },
    {
        "name": "Complex body with multiple lines",
        "content": "【Thoughts】\n思考\n【/Thoughts】\n本文1行目\n2行目\n\n2026-01-12 (Tue) 08:00:00 | custom-model"
    }
]

for tc in test_cases:
    t, b, ts = test_split_logic(tc["content"])
    print(f"CASE: {tc['name']}")
    print(f"  Thoughts:  {repr(t)}")
    print(f"  Body:      {repr(b)}")
    print(f"  Timestamp: {repr(ts)}")
    print("-" * 30)

    # 期待される結果: すべてのケースで timestamp_part が空でないこと
    if not ts:
        print(f"FAILED: {tc['name']} - Timestamp not detected!")
    else:
        print(f"PASSED: {tc['name']}")
