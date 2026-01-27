
import os
import sys

# Add the project root to sys.path
sys.path.append(os.getcwd())

from utils import format_tool_result_for_ui

def test_format_tool_result():
    # Test case 1: Successful read_project_file with suspicious content
    result_suspect = "【ファイル内容: nexus_ark.py】\n(System): ...コピーに失敗しました..."
    formatted = format_tool_result_for_ui("read_project_file", result_suspect)
    print(f"Test 1 (Successful read): {formatted}")
    assert "🛠️ ファイル「nexus_ark.py」を読み取りました。" in formatted

    # Test case 2: Actual error in read_project_file
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

    print("✅ All UI formatting tests passed!")

if __name__ == "__main__":
    test_format_tool_result()
