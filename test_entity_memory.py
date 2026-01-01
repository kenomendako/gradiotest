# test_entity_memory.py

import os
from entity_memory_manager import EntityMemoryManager

def test_crud():
    room_name = "ルシアン"
    manager = EntityMemoryManager(room_name)
    
    # 1. Create
    print("--- Testing Create ---")
    res = manager.create_or_update_entry("TestEntity", "This is a test content about an entity.")
    print(res)
    
    # Check if file exists
    expected_path = f"characters/{room_name}/memory/entities/TestEntity.md"
    if os.path.exists(expected_path):
        print(f"SUCCESS: File created at {expected_path}")
    else:
        print(f"FAILURE: File not found at {expected_path}")

    # 2. Read
    print("\n--- Testing Read ---")
    content = manager.read_entry("TestEntity")
    print(f"Content:\n{content}")
    
    # 3. Update (Append)
    print("\n--- Testing Update (Append) ---")
    res = manager.create_or_update_entry("TestEntity", "Additional facts appended.", append=True)
    print(res)
    content_updated = manager.read_entry("TestEntity")
    print(f"Updated Content:\n{content_updated}")

    # 4. List
    print("\n--- Testing List ---")
    entities = manager.list_entries()
    print(f"Entities: {entities}")

    # 5. Search
    print("\n--- Testing Search ---")
    matches = manager.search_entries("test")
    print(f"Search matches for 'test': {matches}")

if __name__ == "__main__":
    test_crud()
