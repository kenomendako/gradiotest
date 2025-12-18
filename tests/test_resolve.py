
import sys
import os

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import ui_handlers
import config_manager
import utils

room_name = "ルシアン"

print("--- Testing Resolution Logic ---")
config_manager.load_config()
settings = config_manager.get_effective_settings(room_name)

mode = settings.get("theme_bg_src_mode")
print(f"Loaded Mode: {mode}")
print(f"Mode Repr: {repr(mode)}")

print("Calling _resolve_background_image...")
resolved = ui_handlers._resolve_background_image(room_name, settings)
print(f"Resolved Path: {resolved}")

# Check current location
loc = utils.get_current_location(room_name)
print(f"Current Location: {loc}")
# Check if scenery exists
scenery = utils.find_scenery_image(room_name, loc)
print(f"Scenery Found: {scenery}")
