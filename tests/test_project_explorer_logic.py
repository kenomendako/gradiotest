
import os
import fnmatch
from typing import List

def _should_exclude(path: str, root_path: str, exclude_dirs: List[str], exclude_files: List[str]) -> bool:
    """パスが除外対象かどうかを判定する (Mocked for testing)"""
    rel_path = os.path.relpath(path, root_path)
    parts = rel_path.split(os.sep)
    
    # ディレクトリ除外チェック
    for part in parts:
        if part in exclude_dirs:
            return True
            
    # ファイル除外チェック
    filename = os.path.basename(path)
    for pattern in exclude_files:
        if fnmatch.fnmatch(filename, pattern):
            return True
            
    return False

def test_should_exclude():
    root = "/project"
    exclude_dirs = [".git", "node_modules"]
    exclude_files = ["*.pyc", ".env"]

    # --- Test Cases ---
    
    # 1. Normal file (not excluded)
    assert _should_exclude("/project/src/main.py", root, exclude_dirs, exclude_files) == False
    
    # 2. File in excluded dir
    assert _should_exclude("/project/.git/config", root, exclude_dirs, exclude_files) == True
    
    # 3. File in nested excluded dir
    assert _should_exclude("/project/src/node_modules/pkg/index.js", root, exclude_dirs, exclude_files) == True
    
    # 4. Excluded file pattern
    assert _should_exclude("/project/src/utils.pyc", root, exclude_dirs, exclude_files) == True
    
    # 5. Excluded file exact name
    assert _should_exclude("/project/.env", root, exclude_dirs, exclude_files) == True

    # 6. Deeply nested normal file
    assert _should_exclude("/project/a/b/c/d.txt", root, exclude_dirs, exclude_files) == False

    print("✅ All exclusion tests passed!")

if __name__ == "__main__":
    test_should_exclude()
