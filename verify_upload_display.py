import os
import shutil
import sys
import uuid # Needed for mocking file copy

# Ensure /app is in sys.path for imports
sys.path.insert(0, '/app')

try:
    from ui_handlers import _process_uploaded_files, _log_user_interaction, ATTACHMENTS_DIR, SUPPORTED_FILE_MAPPINGS
    from utils import format_history_for_gradio, save_message_to_log # save_message_to_log for _log_user_interaction
    print("Successfully imported functions from ui_handlers and utils.")
except ImportError as e:
    print(f"Error importing functions: {e}")
    sys.exit(1)

# Create a dummy FileData-like object for _process_uploaded_files
class MockGradioFile:
    def __init__(self, name, orig_name):
        self.name = name  # Temporary path of the file
        self.orig_name = orig_name # Original filename

# 1. Define paths and content for the dummy file
dummy_file_content_for_test = "This is a test file for upload verification.\nThe content should not appear."
dummy_original_filename = "test_display_verify.txt"

# Create a temporary dummy file that _process_uploaded_files will read
# This temp file simulates the Gradio temp upload
temp_dir = "temp_gradio_uploads_for_test"
os.makedirs(temp_dir, exist_ok=True)
temp_file_path = os.path.join(temp_dir, f"{uuid.uuid4()}.tmp")
with open(temp_file_path, "w", encoding="utf-8") as f:
    f.write(dummy_file_content_for_test)

# 2. Simulate Gradio file object
file_obj = MockGradioFile(name=temp_file_path, orig_name=dummy_original_filename)
file_input_list = [file_obj]

# Ensure ATTACHMENTS_DIR exists (as in ui_handlers.py)
os.makedirs(ATTACHMENTS_DIR, exist_ok=True)

# 3. Call _process_uploaded_files
# text_from_files (consolidated_text) should now be empty for text file uploads
text_from_files, files_for_api, file_processing_errors = _process_uploaded_files(file_input_list)

if file_processing_errors:
    print(f"File processing errors from _process_uploaded_files: {file_processing_errors}")

print(f"Output of _process_uploaded_files:")
print(f"  text_from_files (should be empty): >>>\n{text_from_files}\n<<<")
print(f"  files_for_api (should contain the text file info): {files_for_api}")

# 4. Simulate what _log_user_interaction would save to the log file.
# We need a dummy log file path for this simulation, though we won't actually rely on its content for this test,
# but rather on the string that *would* be saved.
dummy_log_file_for_test = "dummy_chat_log_for_test.md"
user_header_for_test = "## User:"
original_user_text_for_test = "" # Assuming no typed text, only file upload
add_timestamp_for_test = False
user_action_timestamp_str_for_test = ""

# Reconstruct the logic of _log_user_interaction to get the effective logged message string
log_content_parts = []
if original_user_text_for_test.strip():
    log_content_parts.append(original_user_text_for_test.strip())

for file_info in files_for_api: # files_for_api comes from _process_uploaded_files
    log_entry_for_file = ""
    if file_info.get('log_as_filename_stub'):
        log_entry_for_file = f"[添付テキストファイル:{file_info.get('original_filename', '不明なファイル')}]"
    else:
        log_entry_for_file = f"[ファイル添付:{file_info.get('path')};{file_info.get('original_filename', '不明なファイル')};{file_info.get('mime_type', '不明なMIMEタイプ')}]"
    log_content_parts.append(log_entry_for_file)

final_log_message_simulated = "\n".join(log_content_parts)
if add_timestamp_for_test and final_log_message_simulated: # only add if there's content
    final_log_message_simulated += user_action_timestamp_str_for_test

print(f"Simulated final log message for user turn: >>>\n{final_log_message_simulated}\n<<<")

# 5. This final_log_message_simulated is what's saved. Now simulate format_history_for_gradio
messages_for_gradio = [{"role": "user", "content": final_log_message_simulated}]
# Need character_name for format_history_for_gradio, though not strictly used for user message formatting part
# if the content doesn't require stripping thoughts or special AI tags.
# However, the function `format_history_for_gradio` itself doesn't take character_name.
# `load_chat_log` does, but we are directly giving messages to `format_history_for_gradio`.
formatted_history = format_history_for_gradio(messages_for_gradio)

print(f"Formatted history for Gradio: {formatted_history}")

# 6. Inspect the user message part of the tuple
user_display_message = ""
if formatted_history and isinstance(formatted_history, list) and len(formatted_history) > 0:
    user_display_tuple = formatted_history[0]
    if isinstance(user_display_tuple, tuple) and len(user_display_tuple) > 0:
        user_display_message = user_display_tuple[0]

print(f"User display message from Gradio history: >>>\n{user_display_message}\n<<<")

# 7. Assert the result
expected_display = f"添付テキスト: {dummy_original_filename}"

if user_display_message == expected_display:
    print(f"SUCCESS: User display message is '{user_display_message}', which matches the expected filename-only display.")
    # Also verify that original file content is NOT in the display message
    if dummy_file_content_for_test in user_display_message:
        print(f"FAILURE: File content was found in the display message, though prefix matched.")
    else:
        print(f"Further SUCCESS: File content was confirmed NOT to be in the display message.")
else:
    print(f"FAILURE: User display message is '{user_display_message}', but expected '{expected_display}'.")
    if dummy_file_content_for_test in user_display_message:
        print(f"Additionally, file content IS present in the user display message.")

# Clean up
try:
    os.remove(temp_file_path)
    os.rmdir(temp_dir)
    # Clean up files copied to ATTACHMENTS_DIR by _process_uploaded_files
    for file_entry in files_for_api:
        if os.path.exists(file_entry['path']):
            os.remove(file_entry['path'])
    if os.path.exists(dummy_log_file_for_test): # If test were to actually write it
        os.remove(dummy_log_file_for_test)
    print(f"Cleaned up temporary files and directories.")
except OSError as e:
    print(f"Error cleaning up: {e}")
