
import sys
import os
from unittest.mock import MagicMock

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import ui_handlers
import room_manager

# Mock dependencies
room_manager.get_room_list_for_ui = MagicMock(return_value=[])
room_manager.delete_room = MagicMock(return_value=True)
room_manager.delete_backup = MagicMock(return_value=None)

print("Calling handle_delete_room...")
# Call with dummy values
ret = ui_handlers.handle_delete_room("dummy_room", "dummy_key")

print(f"Return tuple length: {len(ret)}")

# Verify items
# Output detailed list types for debugging
# for i, item in enumerate(ret):
#     print(f"{i}: {type(item)} - {item}")
