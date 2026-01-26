"""
ファイルロック機能のテスト
"""
import sys
sys.path.insert(0, '/home/baken/nexus_ark')

import json
import threading
import time
from pathlib import Path
import tempfile
import shutil

import constants

def test_file_lock_utils():
    """file_lock_utilsのテスト"""
    from file_lock_utils import safe_json_write, safe_json_read, safe_json_update
    
    print("\n=== ファイルロック機能テスト ===\n")
    
    # テスト用の一時ディレクトリを作成
    test_dir = Path(tempfile.mkdtemp())
    test_file = test_dir / "test.json"
    
    try:
        # テスト1: 基本的な読み書き
        print("テスト1: 基本的な読み書き")
        test_data = {"key": "value", "number": 42}
        success = safe_json_write(str(test_file), test_data)
        assert success, "書き込みに失敗"
        
        read_data = safe_json_read(str(test_file))
        assert read_data == test_data, f"データ不一致: {read_data} != {test_data}"
        print("  ✅ 読み書き成功")
        
        # テスト2: 並行書き込み（ロックなしだと破損リスク）
        print("\nテスト2: 並行書き込みの安全性")
        concurrent_file = test_dir / "concurrent.json"
        safe_json_write(str(concurrent_file), {"count": 0})
        
        errors = []
        
        def increment():
            for _ in range(10):
                def update_func(data):
                    data["count"] += 1
                    return data
                if not safe_json_update(str(concurrent_file), update_func):
                    errors.append("update failed")
                time.sleep(0.01)
        
        threads = [threading.Thread(target=increment) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        final_data = safe_json_read(str(concurrent_file))
        expected = 30  # 3スレッド × 10回
        assert final_data["count"] == expected, f"並行書き込みで不整合: {final_data['count']} != {expected}"
        assert not errors, f"エラー発生: {errors}"
        print(f"  ✅ 並行書き込み成功（count: {final_data['count']}）")
        
        # テスト3: 存在しないファイルの読み込み
        print("\nテスト3: 存在しないファイルの読み込み")
        nonexistent = test_dir / "nonexistent.json"
        data = safe_json_read(str(nonexistent), default={"default": True})
        assert data == {"default": True}, f"デフォルト値が返されない: {data}"
        print("  ✅ デフォルト値が正しく返される")
        
        print("\n=== 全テスト成功 ===")
        
    finally:
        # テストディレクトリを削除
        shutil.rmtree(test_dir, ignore_errors=True)

if __name__ == "__main__":
    test_file_lock_utils()
