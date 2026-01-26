
import sys
import os
import json
import shutil

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import ui_handlers
import constants
import room_manager

# Mock environment
TEST_ROOM = "test_theme_save_room"
ROOM_DIR = os.path.join(constants.ROOMS_DIR, TEST_ROOM)
if os.path.exists(ROOM_DIR):
    shutil.rmtree(ROOM_DIR)
os.makedirs(ROOM_DIR, exist_ok=True)

CONFIG_PATH = os.path.join(ROOM_DIR, "room_config.json")
with open(CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump({"room_name": TEST_ROOM}, f)

print(f"Created test room: {TEST_ROOM}")

# Prepare 43 arguments
# 0: Room Name
args = [TEST_ROOM]

# 1-4: Basic flags/style
# enabled, font, line, chat(4)
args.extend([True, 15, 1.6, "Chat"]) # len 5

# 5-9: basic colors (5 items)
args.extend(["#000"]*5) # len 10

# 10-21: detailed colors (12 items)
args.extend(["#111"]*12) # len 22

# 22: ui_opacity
args.append(0.9) # len 23

# 23: bg_image
args.append(None) # len 24

# 24-32: bg props (9 items)
# opacity, blur, size, pos, repeat, width, radius, mask, overlay
args.extend([0.5, 5, "cover", "center", "no-repeat", "300px", 10, 20, False]) # len 33

# 33: src_mode
SYNC_MODE = "現在地と連動 (Sync)"
args.append(SYNC_MODE) # len 34

# 34-42: Sync settings (9 items)
args.extend([0.1, 2, "auto", "center", "no-repeat", "300px", 0, 0, False]) # len 43

print(f"Total Args: {len(args)}") # Expect 43

# Execute
print("Calling handle_save_theme_settings...")
ui_handlers.handle_save_theme_settings(*args)

# Verify
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

saved_mode = data.get("override_settings", {}).get("theme_bg_src_mode")
print(f"Saved Mode (in override_settings): '{saved_mode}'")
print(f"Expected: '{SYNC_MODE}'")

if saved_mode == SYNC_MODE:
    print("SUCCESS")
else:
    print("FAILURE")
