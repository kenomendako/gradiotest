
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

# Prepare 31 arguments
# 0: Room Name
args = [TEST_ROOM]

# 1-19: Settings (19 items)
# enabled, font, line, chat(4)
args.extend([True, 15, 1.6, "Chat"])
# basic(5)
args.extend(["#000"]*5)
# detailed(10)
args.extend(["#111"]*10)
# table(1) - Index 19
# args[19] is "TableBG"
# Wait, if I put "#111" for detailed, that is 10 items.
# Detailed indices: 10..19. 
# Oh wait, detailed in code is lines 6251-6260.
# 6260: "theme_table_bg": args[19].
# My detailed count was correct.
# So args[19] will be the LAST of "detailed" extension if I extend 10?
# No.
# args list so far: [Room] (1)
# extend([True, 15, 1.6, "Chat"]) (4) -> len 5
# extend(["#000"]*5) (5) -> len 10
# extend(["#111"]*10) (10) -> len 20.
# The last item is at index 19.
# So args[19] is one of the "#111".
# BUT table is args[19]. So correct.

# 20: bg_image
args.append("test_image.png") 

# 21-29: bg props (9 items)
# opacity, blur, size, pos, repeat, width, radius, mask, overlay
args.extend([0.5, 5, "cover", "center", "no-repeat", "300px", 10, 20, "OverlayValue"]) 
# args[21]..args[29]
# args[29] is "OverlayValue"

# 30: src_mode
SYNC_MODE = "現在地と連動 (Sync)"
args.append(SYNC_MODE)

print(f"Total Args: {len(args)}") # Expect 31

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
