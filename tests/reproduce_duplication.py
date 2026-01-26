
import sys
import os

# Add parent directory to path to import modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from langchain_core.messages import AIMessage, ToolMessage
import utils

def test_filter_logic():
    print("--- Testing Filter Logic ---")

    # Mock utils.get_content_as_string
    def mock_get_content(msg):
        if isinstance(msg, AIMessage):
            return msg.content
        return str(msg.content)
    
    utils.get_content_as_string = mock_get_content

    # Case 1: Exact Duplicates
    msgs = [AIMessage(content="Hello."), AIMessage(content="Hello.")]
    filtered = run_filter(msgs)
    print(f"Case 1 (Exact): Input=2, Output={len(filtered)} (Expected 1)")
    assert len(filtered) == 1

    # Case 2: Substring (Short then Long)
    msgs = [AIMessage(content="Hello"), AIMessage(content="Hello World")]
    filtered = run_filter(msgs)
    print(f"Case 2 (Short-Long): Input=2, Output={len(filtered)} (Expected 1 - 'Hello World')")
    # "Hello" is in "Hello World". "Hello" is removed.
    assert len(filtered) == 1
    assert filtered[0].content == "Hello World"

    # Case 3: Substring (Long then Short)
    msgs = [AIMessage(content="Hello World"), AIMessage(content="Hello")]
    filtered = run_filter(msgs)
    print(f"Case 3 (Long-Short): Input=2, Output={len(filtered)} (Expected 1 - 'Hello World')")
    # "Hello" is in "Hello World". "Hello" is removed.
    assert len(filtered) == 1
    assert filtered[0].content == "Hello World"

    # Case 4: The "Slightly Cut Off" Case (Suffix)
    # "Hello." and "lo."
    msgs = [AIMessage(content="Hello."), AIMessage(content="lo.")]
    filtered = run_filter(msgs)
    print(f"Case 4 (Suffix): Input=2, Output={len(filtered)} (Expected 1 - 'Hello.')")
    # "lo." is in "Hello.". "lo." is removed.
    if len(filtered) == 1 and filtered[0].content == "Hello.":
        print("  -> Passed")
    else:
        print(f"  -> FAILED. Output: {[m.content for m in filtered]}")

    # Case 5: The "Concatenated" Case
    # "おはよう。\n今日も頑張ろうね" and "おはよう。\n今日も頑張ろうね"
    msgs = [AIMessage(content="おはよう。\n今日も頑張ろうね"), AIMessage(content="おはよう。\n今日も頑張ろうね")]
    filtered = run_filter(msgs)
    print(f"Case 5 (Concatenated Exact): Input=2, Output={len(filtered)} (Expected 1)")
    assert len(filtered) == 1

    # Case 6: "おはよう。" and "今日も頑張ろうね" (Separate)
    msgs = [AIMessage(content="おはよう。"), AIMessage(content="今日も頑張ろうね")]
    filtered = run_filter(msgs)
    print(f"Case 6 (Separate): Input=2, Output={len(filtered)} (Expected 2)")
    assert len(filtered) == 2

    # Case 7: Complex Overlap
    # "Hello" and "Hello."
    msgs = [AIMessage(content="Hello"), AIMessage(content="Hello.")]
    filtered = run_filter(msgs)
    print(f"Case 7 (Punctuation): Input=2, Output={len(filtered)} (Expected 1 - 'Hello.')")
    assert len(filtered) == 1
    assert filtered[0].content == "Hello."

def run_filter(raw_new_messages):
    # Copy-paste logic from ui_handlers.py lines 721-760
    new_messages = []
    
    for i, msg in enumerate(raw_new_messages):
        content_str = ""
        if isinstance(msg, AIMessage):
            content_str = utils.get_content_as_string(msg)
        elif isinstance(msg, ToolMessage):
            content_str = str(msg.content)
        
        if not content_str or not content_str.strip():
            continue

        is_redundant = False
        for j, other_msg in enumerate(raw_new_messages):
            if i == j: continue 

            other_content = ""
            if isinstance(other_msg, AIMessage):
                other_content = utils.get_content_as_string(other_msg)
            elif isinstance(other_msg, ToolMessage):
                other_content = str(other_msg.content)

            # 判定1: 自分が他のメッセージの「一部（substring）」であり、かつ相手の方が長い場合
            if content_str in other_content and len(content_str) < len(other_content):
                is_redundant = True
                break
            
            # 判定2: 完全一致する場合、インデックスが後のものを残す（または最初を残す）
            # ここでは「最初に出てきたもの」を正とし、後続の重複を削除する
            if content_str == other_content and i > j:
                is_redundant = True
                break
        
        if not is_redundant:
            new_messages.append(msg)
    
    return new_messages

if __name__ == "__main__":
    test_filter_logic()
