import os
import sys
import psutil
import time
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.append(os.getcwd())

import rag_manager
import constants

def print_memory():
    process = psutil.Process()
    mem = process.memory_info().rss / (1024 * 1024)
    print(f"[Memory] {mem:.2f} MB")

def test_rag_optimization():
    room_name = "ルシアン"
    api_key = os.getenv("GOOGLE_API_KEY", "dummy_key")
    
    print("--- RAG Optimization Test Start ---")
    print_memory()
    
    # 1. RAGManager インスタンス化 (遅延ロードの確認)
    print("\n[Step 1] Initializing RAGManager...")
    rm = rag_manager.RAGManager(room_name, api_key)
    print_memory()
    
    # 2. 初回検索 (インデックスロード & 埋め込みモデル初期化)
    print("\n[Step 2] First Search (Triggering Index Load)...")
    start_time = time.time()
    # 実際には検索結果は重要ではないので、ダミー検索
    try:
        results = rm.search("テスト", k=1)
        print(f"First search completed in {time.time() - start_time:.2f}s")
    except Exception as e:
        print(f"Search error (expected if key is dummy): {e}")
    print_memory()
    
    # 3. 2回目検索 (キャッシュヒットの確認)
    print("\n[Step 3] Second Search (Cache Hit Check)...")
    start_time = time.time()
    try:
        results = rm.search("テスト", k=1)
        print(f"Second search completed in {time.time() - start_time:.2f}s")
    except Exception as e:
        print(f"Search error: {e}")
    print_memory()
    
    # 最近のキャッシュの内容を確認
    print("\n[Step 4] Cache Status:")
    for path, (db, ts) in rag_manager.RAGManager._index_cache.items():
        print(f" Cached Index: {Path(path).name}, TS: {ts}")

    print("\n--- RAG Optimization Test Finished ---")

if __name__ == "__main__":
    test_rag_optimization()
