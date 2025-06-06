import os
import sys
import datetime # Required by ui_handlers indirectly
import shutil # Required by ui_handlers
import re # For timestamp checking
import traceback # For printing tracebacks

# Ensure /app is in sys.path
sys.path.insert(0, '/app')

try:
    import config_manager
    from ui_handlers import handle_message_submission, ATTACHMENTS_DIR
    from utils import load_chat_log, format_history_for_gradio
    from character_manager import get_character_files_paths, ensure_character_files # For cleanup and setup
    print("Successfully imported required modules.")
except ImportError as e:
    print(f"Error importing modules: {e}")
    traceback.print_exc()
    sys.exit(1)

# --- Mock Gradio FileData object ---
class MockGradioFile:
    def __init__(self, name, orig_name):
        self.name = name  # Temporary path of the file (simulates Gradio's temp file)
        self.orig_name = orig_name # Original filename

# --- Test Setup ---
# 1. Load config to get defaults, then override API key for test
try:
    config_manager.load_config()
    print(f"Config loaded. Initial character: {config_manager.initial_character_global}, Model: {config_manager.initial_model_global}, Original API Key Name: {config_manager.initial_api_key_name_global}")
except Exception as e:
    print(f"Error loading config_manager: {e}. Setting fallback defaults.")
    traceback.print_exc()
    config_manager.initial_character_global = "Default"
    config_manager.initial_model_global = "gemini-1.5-flash-latest"
    config_manager.AVAILABLE_MODELS_GLOBAL = [config_manager.initial_model_global]
    # Fallback API key setup below will handle API key

# Force a valid dummy API key for the test to bypass placeholder checks
DUMMY_API_KEY_NAME_FOR_TEST = "test_dummy_key_live_verify" # Unique name for this test run
DUMMY_API_KEY_VALUE_FOR_TEST = "dummy_valid_api_key_value_verify"
config_manager.API_KEYS[DUMMY_API_KEY_NAME_FOR_TEST] = DUMMY_API_KEY_VALUE_FOR_TEST
config_manager.initial_api_key_name_global = DUMMY_API_KEY_NAME_FOR_TEST

if not config_manager.initial_character_global:
    config_manager.initial_character_global = "Default"
ensure_character_files(config_manager.initial_character_global) # Ensures Default character files exist
if not config_manager.initial_model_global:
    config_manager.initial_model_global = config_manager.AVAILABLE_MODELS_GLOBAL[0] if hasattr(config_manager, "AVAILABLE_MODELS_GLOBAL") and config_manager.AVAILABLE_MODELS_GLOBAL else "gemini-1.5-flash-latest"

# 2. Dummy text file
dummy_original_filename = "test_final_upload_verify.txt"
dummy_content = "Final test content for live verification.\nThis content should NOT appear in the UI."

temp_upload_dir = "temp_gradio_uploads_for_test_live_verify"
os.makedirs(temp_upload_dir, exist_ok=True)
source_temp_file_path = os.path.join(temp_upload_dir, dummy_original_filename)
with open(source_temp_file_path, "w", encoding="utf-8") as f:
    f.write(dummy_content)

# 3. Arguments for handle_message_submission
user_input_text_arg = ""
chatbot_history_arg = []
character_name_arg = config_manager.initial_character_global
model_name_arg = config_manager.initial_model_global
api_key_name_arg = config_manager.initial_api_key_name_global
add_timestamp_arg = True
send_thoughts_arg = getattr(config_manager, 'initial_send_thoughts_to_api_global', False)
api_history_limit_arg = getattr(config_manager, 'initial_api_history_limit_option_global', "10")

mock_file_obj = MockGradioFile(name=source_temp_file_path, orig_name=dummy_original_filename)
uploaded_files_arg = [mock_file_obj]

os.makedirs(ATTACHMENTS_DIR, exist_ok=True)

# 4. Call handle_message_submission
print(f"Calling handle_message_submission for character: '{character_name_arg}', API key: '{api_key_name_arg}'...")
ui_error_msg_from_submission = ""
try:
    # We are not interested in updated_history from this call when API fails,
    # as it returns the original empty history.
    _, _, _, ui_error_msg_from_submission = handle_message_submission(
        user_input_text_arg,
        chatbot_history_arg,
        character_name_arg,
        model_name_arg,
        api_key_name_arg,
        uploaded_files_arg,
        add_timestamp_arg,
        send_thoughts_arg,
        api_history_limit_arg
    )
    if ui_error_msg_from_submission:
        print(f"UI Error message from handle_message_submission (expected due to dummy API key): {ui_error_msg_from_submission}")
except Exception as e:
    print(f"Exception during handle_message_submission: {e}")
    traceback.print_exc()
    sys.exit(1)

# 5. Load and format the log directly
log_file_path, _, _, _ = get_character_files_paths(character_name_arg)
if not log_file_path or not os.path.exists(log_file_path):
    print(f"ERROR: Log file not found for character '{character_name_arg}' at '{log_file_path}'")
    sys.exit(1)

chat_log_from_file = load_chat_log(log_file_path, character_name_arg)
formatted_display_history_from_log = format_history_for_gradio(chat_log_from_file)

print(f"Formatted display history (from log): {formatted_display_history_from_log}")

# 6. Inspect the last user message from the log
last_user_display_message = None
if formatted_display_history_from_log:
    # The user message we submitted should be the user part of the last turn in the log.
    # If the API call failed, there might not be an AI response part, or it might be an error.
    # We are interested in the *user's* logged message.
    # format_history_for_gradio returns a list of (user_msg, ai_msg) tuples.
    # The last logged event by handle_message_submission for the user's turn is what we need.

    # Find the last turn that has a non-None user message.
    # The log is chronological. The last entry added by `handle_message_submission` for the user's action
    # will be the last entry in `chat_log_from_file` if it was a user role.
    # `format_history_for_gradio` converts this.

    # Assuming the user's message is the last thing logged before a potential AI response.
    # If an API error occurs, the AI response might not be logged or might be an error message.
    # We need to ensure we are looking at the user's submission.

    found_user_turn = False
    for i in range(len(formatted_display_history_from_log) - 1, -1, -1):
        turn = formatted_display_history_from_log[i]
        # The user message (turn[0]) for a file upload should be the "[添付テキストファイル:..." string
        # after formatting by format_history_for_gradio.
        # We are looking for the display of the user's action (file upload).
        if turn[0] is not None and dummy_original_filename in turn[0]: # Heuristic: our file was part of this user turn
            last_user_display_message = turn[0]
            found_user_turn = True
            break
    if not found_user_turn and formatted_display_history_from_log: # Fallback if heuristic fails
         # This might happen if the user message is empty after formatting (e.g. only an image was processed differently)
         # For our case, it should contain the text file stub.
         print("Warning: Could not definitively find the user turn by filename heuristic, taking the user part of the very last turn.")
         last_turn_in_log = formatted_display_history_from_log[-1]
         last_user_display_message = last_turn_in_log[0]


print(f"Last user display message (from log): >>>\n{last_user_display_message}\n<<<")

# 7. Assert results
success = False
final_report_messages = []

if last_user_display_message:
    expected_filename_part = f"添付テキスト: {dummy_original_filename}"
    final_report_messages.append(f"Actual display: '{last_user_display_message}'")
    final_report_messages.append(f"Expected to contain: '{expected_filename_part}'")

    contains_filename = expected_filename_part in last_user_display_message
    contains_content = dummy_content in last_user_display_message

    timestamp_pattern = r"\d{4}-\d{2}-\d{2} \([A-Za-z]{3}\) \d{2}:\d{2}:\d{2}"
    contains_timestamp = False
    if add_timestamp_arg:
        if re.search(timestamp_pattern, last_user_display_message):
            contains_timestamp = True
            final_report_messages.append(f"Timestamp found (pattern: {timestamp_pattern}).")
        else:
            final_report_messages.append(f"ERROR: Timestamp was expected (pattern: {timestamp_pattern}) but not found.")
    else:
        contains_timestamp = True

    if contains_filename and not contains_content and contains_timestamp:
        success = True
        final_report_messages.insert(0, "SUCCESS: Display string contains filename, correct timestamp presence, and no file content.")
    else:
        final_report_messages.insert(0, "FAILURE: Display string validation failed.")
        if not contains_filename:
            final_report_messages.append(f"  - ERROR: Does not contain expected filename part: '{expected_filename_part}'")
        if contains_content:
            final_report_messages.append(f"  - ERROR: Contains forbidden file content (starts with: '{dummy_content[:50]}...')")
        if add_timestamp_arg and not contains_timestamp:
            final_report_messages.append(f"  - ERROR: Does not contain expected timestamp.")
else:
    final_report_messages.insert(0, "FAILURE: No user display message found in the processed history from log.")

# 8. Clean up
print("\n--- Cleanup ---")
if log_file_path and os.path.exists(log_file_path):
    print(f"Note: Log file '{log_file_path}' was modified by this test.")

if os.path.exists(source_temp_file_path):
    os.remove(source_temp_file_path)
    print(f"Cleaned up source temp file: '{source_temp_file_path}'")
if os.path.exists(temp_upload_dir):
    try:
        shutil.rmtree(temp_upload_dir)
        print(f"Cleaned up temp directory: '{temp_upload_dir}'")
    except OSError as e:
        print(f"Error removing temp directory '{temp_upload_dir}': {e}")

print(f"Note: {ATTACHMENTS_DIR} may contain files copied during the test. Manual cleanup may be needed.")


print("\n--- Final Report ---")
for msg in final_report_messages:
    print(msg)

if success:
    print("Overall test result: SUCCESS")
else:
    print("Overall test result: FAILURE")
    sys.exit(1) # Ensure script exits with error if test failed.
