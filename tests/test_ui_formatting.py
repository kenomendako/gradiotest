
import os
import sys

# Add the project root to sys.path
sys.path.append(os.getcwd())

from utils import format_tool_result_for_ui

def test_format_tool_result():
    # Test case 1: Successful read_project_file with "失敗" in content
    result_suspect = "【ファイル内容: nexus_ark.py】\n(System): ...コピーに失敗しました..."
    formatted = format_tool_result_for_ui("read_project_file", result_suspect)
    print(f"Test 1 (Content with '失敗'): {formatted}")
    assert "🛠️ ファイル「nexus_ark.py」" in formatted, "Should show success message even with '失敗' in content"

    # Test case 2: Actual error in read_project_file (starts with 【エラー】)
    result_error = "【エラー】ファイルが見つかりません: config.json"
    formatted = format_tool_result_for_ui("read_project_file", result_error)
    print(f"Test 2 (Actual error): {formatted}")
    assert "⚠️ ツール「read_project_file」の実行に失敗しました。" in formatted

    # Test case 3: list_project_files
    result_list = "project_root/\n  src/\n  tests/"
    formatted = format_tool_result_for_ui("list_project_files", result_list)
    print(f"Test 3 (List files): {formatted}")
    assert "🛠️ プロジェクトのファイル一覧を取得しました。" in formatted

    # Test case 4: Other tool (generic pattern)
    result_other_err = "Error: Connection failed"
    formatted = format_tool_result_for_ui("web_search_tool", result_other_err)
    print(f"Test 4 (Other tool error): {formatted}")
    assert "⚠️ ツール「web_search_tool」の実行に失敗しました。" in formatted

    # Test case 5: Developer tool with "Exception:" in content (should NOT trigger error)
    result_exception = "【ファイル内容: utils.py (L1-L100 / 全983行)】\n    except Exception:\n        print('handled')"
    formatted = format_tool_result_for_ui("read_project_file", result_exception)
    print(f"Test 5 (Content with 'Exception:'): {formatted}")
    assert "🛠️ ファイル「utils.py」" in formatted, "Should NOT trigger error for 'Exception:' in file content"

    # Test case 6: Developer tool with "Error:" in content (should NOT trigger error)
    result_error_text = "【ファイル内容: log.txt (L1-L50 / 全200行)】\n    Error: This is just log text\n    Another line"
    formatted = format_tool_result_for_ui("read_project_file", result_error_text)
    print(f"Test 6 (Content with 'Error:'): {formatted}")
    assert "🛠️ ファイル" in formatted, "Should NOT trigger error for 'Error:' in file content"

    # Test case 7: Developer tool with "エラー:" in content (should NOT trigger error)
    result_japanese = "【ファイル内容: config.json (L1-L30 / 全50行)】\n  \"message\": \"エラー: 接続失敗\""
    formatted = format_tool_result_for_ui("read_project_file", result_japanese)
    print(f"Test 7 (Content with 'エラー:'): {formatted}")
    assert "🛠️ ファイル" in formatted, "Should NOT trigger error for 'エラー:' in file content"

    # Test case 8: Directory error
    result_dir_error = "【エラー】'src' はディレクトリです。中身を読むには..."
    formatted = format_tool_result_for_ui("read_project_file", result_dir_error)
    print(f"Test 8 (Directory error): {formatted}")
    assert "⚠️ ツール「read_project_file」の実行に失敗しました。" in formatted

    print("✅ All UI formatting tests passed!")

if __name__ == "__main__":
    test_format_tool_result()

