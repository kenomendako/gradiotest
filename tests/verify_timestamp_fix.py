import re

def test_split_logic(original_content):
    # 後方互換性: 新形式 [THOUGHT] と旧形式 【Thoughts】 の両方に対応
    thoughts_pattern = re.compile(r"(\[THOUGHT\][\s\S]*?\[/THOUGHT\]|【Thoughts】[\s\S]*?【/Thoughts】)", re.IGNORECASE)
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
        "name": "Legacy format with model name",
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
        "name": "Complex body with multiple lines (legacy)",
        "content": "【Thoughts】\n思考\n【/Thoughts】\n本文1行目\n2行目\n\n2026-01-12 (Tue) 08:00:00 | custom-model"
    },
    # 新形式 [THOUGHT] のテストケース
    {
        "name": "New [THOUGHT] format with model name",
        "content": "[THOUGHT]\n新形式の思考内容\n[/THOUGHT]\n本文です。\n\n2026-01-21 (Tue) 19:30:00 | gemini-2.5-flash"
    },
    {
        "name": "New [THOUGHT] format without model name",
        "content": "[THOUGHT]\n新形式の思考\n[/THOUGHT]\n\n本文のみ。\n\n2026-01-21 (Tue) 12:00:00"
    },
    {
        "name": "New [THOUGHT] format with multiline thoughts",
        "content": "[THOUGHT]\nこれは新形式の思考ログです。\n複数行に渡る内容も正しく処理されるべき。\n[/THOUGHT]\nこれが本文です。\n\n2026-01-21 (Wed) 10:00:00 | gemini-2.5-flash"
    }
]

print("=" * 60)
print("思考ログ・タイムスタンプ分離テスト (新形式対応版)")
print("=" * 60)

passed = 0
failed = 0
for tc in test_cases:
    t, b, ts = test_split_logic(tc["content"])
    print(f"\nCASE: {tc['name']}")
    print(f"  Thoughts:  {repr(t[:50] + '...' if len(t) > 50 else t)}")
    print(f"  Body:      {repr(b[:50] + '...' if len(b) > 50 else b)}")
    print(f"  Timestamp: {repr(ts)}")

    # 検証: タイムスタンプが検出されること
    if not ts:
        print(f"  ❌ FAILED: Timestamp not detected!")
        failed += 1
    # 思考ログがある場合は検出されること
    elif "[THOUGHT]" in tc["content"].upper() or "【Thoughts】" in tc["content"]:
        if t:
            print(f"  ✅ PASSED")
            passed += 1
        else:
            print(f"  ❌ FAILED: Thoughts not detected!")
            failed += 1
    else:
        print(f"  ✅ PASSED")
        passed += 1

print("\n" + "=" * 60)
print(f"結果: {passed} passed, {failed} failed")
print("=" * 60)

