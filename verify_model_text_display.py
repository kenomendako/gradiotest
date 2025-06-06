import os
import sys
import shutil # For cleaning up character logs if needed

# Ensure /app is in sys.path
sys.path.insert(0, '/app')

try:
    import config_manager
    from utils import load_chat_log, format_history_for_gradio, save_message_to_log
    from character_manager import get_character_files_paths, ensure_character_files, CHARACTERS_DIR
    print("Successfully imported required modules.")
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)

# --- Test Setup ---
# 1. Character and Log File
try:
    config_manager.load_config() # To get default character name, though we'll use a specific one for test
except Exception as e:
    print(f"Warning: config_manager.load_config() failed: {e}. Using hardcoded 'TestCharacterForModelDisplay'.")
    # Fallback if config loading has issues, though ensure_character_files should handle creation

character_name = "TestCharacter_ModelText"
ensure_character_files(character_name) # Creates Default character files and directory
log_file_path, _, _, _ = get_character_files_paths(character_name)

if not log_file_path:
    print(f"FAILURE: Could not get log_file_path for character '{character_name}'.")
    sys.exit(1)

# Optional: Clear existing log file for a clean test
if os.path.exists(log_file_path):
    os.remove(log_file_path)
    print(f"Cleared existing log file: {log_file_path}")
ensure_character_files(character_name) # Re-ensure files after potential clear

# 2. Manually create and save chat history
user_message_content = "Hi"
model_response_content = "Hello, this is a test response."
ZWSP = "\u200B" # Zero-Width Space

# Save user message
user_header = "## UserTest:" # Using a distinct header for clarity if needed
save_message_to_log(log_file_path, user_header, user_message_content)
print(f"Saved user message to log: '{user_message_content}'")

# Save model response (as it would be if it came from the model, without ZWSP initially)
model_header = f"## {character_name}:"
save_message_to_log(log_file_path, model_header, model_response_content)
print(f"Saved model message to log: '{model_response_content}'")

# 3. Load and Format the Log
chat_log_from_file = load_chat_log(log_file_path, character_name)
print(f"Loaded chat log from file: {chat_log_from_file}")

# This is where the ZWSP prefixing happens for model's plain text responses
formatted_display_history = format_history_for_gradio(chat_log_from_file)
print(f"Formatted display history: {formatted_display_history}")

# 4. Inspect the last model message
actual_model_display_message = None
if formatted_display_history and len(formatted_display_history) > 0:
    last_turn = formatted_display_history[-1] # Should be (user_display, model_display)
    if len(last_turn) == 2:
        actual_model_display_message = last_turn[1]

print(f"Actual model display message from Gradio history: >>>\n{actual_model_display_message}\n<<<")

# 5. Assert results
success = False
final_report_messages = []

expected_model_text_in_ui = model_response_content # Visually, it should be the same
# Internally, it should be ZWSP + model_response_content if it's a simple string.
# If model_response_content is empty, it should be just ZWSP.
expected_internal_representation = ZWSP + model_response_content if model_response_content else ZWSP

if actual_model_display_message is not None:
    final_report_messages.append(f"Actual display: '{actual_model_display_message}'")
    final_report_messages.append(f"Expected visual display: '{expected_model_text_in_ui}'")
    final_report_messages.append(f"Expected internal representation (with ZWSP): '{expected_internal_representation}'")

    # Check visual appearance (should be the same as original, ZWSP is invisible)
    if actual_model_display_message == expected_internal_representation:
        # This also implies that if model_response_content was "", actual_model_display_message is ZWSP
        if model_response_content == "": # Special case: empty model response
            if actual_model_display_message == ZWSP:
                success = True
                final_report_messages.insert(0, "SUCCESS: Empty model response correctly represented as ZWSP internally and displays as effectively empty.")
            else:
                final_report_messages.insert(0, "FAILURE: Empty model response not correctly represented as ZWSP.")
        else: # Non-empty model response
            success = True
            final_report_messages.insert(0, f"SUCCESS: Model's plain text response is displayed as expected ('{expected_model_text_in_ui}') and internal representation is correct.")
            # Verify ZWSP prefix for non-empty simple text
            if not actual_model_display_message.startswith(ZWSP):
                 final_report_messages.append("WARNING: Expected ZWSP prefix was not found, though visual match was okay. This might be an issue if the string was empty.")
                 # For this test, if it visually matches, it might be acceptable depending on strictness of "verify ZWSP"
                 # The core requirement is "displayed correctly".
    else:
        final_report_messages.insert(0, "FAILURE: Model's plain text response display does not match expected internal representation.")
        if actual_model_display_message.lstrip(ZWSP) == model_response_content:
             final_report_messages.append("INFO: Text content matches after stripping potential ZWSP, but full string representation differs.")
        else:
             final_report_messages.append(f"Visual content also differs or ZWSP handling is unexpected.")

else:
    final_report_messages.insert(0, "FAILURE: No model display message found in the formatted history.")

# 6. Clean up
print("\n--- Cleanup ---")
character_path_to_clean = os.path.join(CHARACTERS_DIR, character_name)
if os.path.exists(character_path_to_clean):
    try:
        shutil.rmtree(character_path_to_clean)
        print(f"Cleaned up character directory: '{character_path_to_clean}'")
    except OSError as e:
        print(f"Error cleaning up character directory '{character_path_to_clean}': {e}")

print("\n--- Final Report ---")
for msg in final_report_messages:
    print(msg)

if success:
    print("Overall test result: SUCCESS")
else:
    print("Overall test result: FAILURE")
    sys.exit(1) # Ensure script exits with error if test failed.
