import re # Ensure re is imported at the very top
from typing import List, Dict, Optional, Any, Tuple, Union # Added for type hints
import urllib.parse # Added for URL encoding
# --- Custom Wrapper for format_history_for_gradio ---
FILE_CONTENT_HEADER_PATTERN = r"--- 添付ファイル「(.*?)」の内容 ---.*"
ATTACHED_IMAGE_PATTERN = r"\[ファイル添付: (.*?);(.*?);(image/(?:png|jpeg|gif|webp))\]"
GENERATED_IMAGE_PATTERN = r"\[Generated Image: (.*?(?:png|jpeg|gif|webp))\]"
# Define thought log patterns locally for this function's scope
TH_PAT_LOCAL = re.compile(r"【Thoughts】.*?【/Thoughts】\s*", re.DOTALL | re.IGNORECASE)
HTML_TH_PAT_LOCAL = re.compile(r"<div class='thoughts'>\s*<pre>\s*<code>.*?</code>\s*</pre>\s*</div>\s*", re.DOTALL | re.IGNORECASE)

def format_history_for_gradio_wrapper(chat_log_from_utils: List[Dict[str, str]]) -> List[List[Optional[str]]]:
    """
    utils.format_history_for_gradio のラッパー関数。
    メッセージ内容のファイルコンテンツヘッダーを短い形式に置換し、
    画像添付・生成ログをMarkdown画像表示に変換し、思考ログを除去します。
    """
    formatted_history_input = original_format_history_for_gradio(chat_log_from_utils)
    print(f"DEBUG_FORMAT_WRAPPER: Starting. Input (last 3 pairs): {formatted_history_input[-3:]}")

    processed_history_output = []
    for i, message_pair in enumerate(formatted_history_input):
        user_message = message_pair[0]
        assistant_message_initial = message_pair[1]

        processed_assistant_message = assistant_message_initial

        if isinstance(assistant_message_initial, str) and assistant_message_initial.strip():
            print(f"DEBUG_FORMAT_WRAPPER: Entry {i} - Initial assistant_message: '{assistant_message_initial[:200]}...'")

            current_processing_for_assistant = assistant_message_initial

            # アシスタントメッセージに対する思考ログ除去 (TH_PAT_LOCAL)
            temp_message_after_th = TH_PAT_LOCAL.sub("", current_processing_for_assistant).strip()
            if current_processing_for_assistant.strip() and not temp_message_after_th.strip() and "【Thoughts】" in current_processing_for_assistant:
                print(f"DEBUG_FORMAT_WRAPPER: WARNING! Entry {i} - Assistant message BECAME EMPTY after TH_PAT_LOCAL removal.")
            print(f"DEBUG_FORMAT_WRAPPER: Entry {i} - After TH_PAT_LOCAL removal: '{temp_message_after_th[:200]}...'")
            current_processing_for_assistant = temp_message_after_th

            # アシスタントメッセージに対するHTML形式の思考ログ除去 (HTML_TH_PAT_LOCAL)
            temp_message_after_html_th = HTML_TH_PAT_LOCAL.sub("", current_processing_for_assistant).strip()
            if current_processing_for_assistant.strip() and not temp_message_after_html_th.strip() and "<div class='thoughts'>" in current_processing_for_assistant:
                print(f"DEBUG_FORMAT_WRAPPER: WARNING! Entry {i} - Assistant message BECAME EMPTY after HTML_TH_PAT_LOCAL removal.")
            print(f"DEBUG_FORMAT_WRAPPER: Entry {i} - After HTML_TH_PAT_LOCAL removal: '{temp_message_after_html_th[:200]}...'")
            processed_assistant_message = temp_message_after_html_th # 思考ログ除去後の最終結果

            print(f"DEBUG_FORMAT_WRAPPER: Entry {i} - Assistant message after all thought removals: '{processed_assistant_message[:200]}...'")

        final_pair_for_output = []
        # j=0: user_message, j=1: processed_assistant_message (思考ログ除去済み)
        for j, message_content_segment in enumerate([user_message, processed_assistant_message]):
            role_for_debug = "User" if j == 0 else "Assistant"

            if isinstance(message_content_segment, str):
                original_segment_for_warning_check = message_content_segment
                current_processing_segment = message_content_segment

                # デバッグ: このセグメントの初期値
                print(f"DEBUG_FORMAT_WRAPPER: Entry {i} ({role_for_debug}) - Segment initial value for common processing: '{current_processing_segment[:200]}...'")

                # 1. テキストファイル内容ヘッダーの置換
                modified_segment_step1 = re.sub(FILE_CONTENT_HEADER_PATTERN, r"添付ファイル: \1", current_processing_segment, flags=re.DOTALL)
                if current_processing_segment != modified_segment_step1 or ("--- 添付ファイル「" in current_processing_segment): # 変更があったか、パターンが含まれていた場合のみログ出力
                    print(f"DEBUG_FORMAT_WRAPPER: Entry {i} ({role_for_debug}) - After FILE_CONTENT_HEADER_PATTERN: '{modified_segment_step1[:200]}...'")
                if original_segment_for_warning_check.strip() and not modified_segment_step1.strip() and "--- 添付ファイル「" in original_segment_for_warning_check :
                     print(f"DEBUG_FORMAT_WRAPPER: WARNING! Entry {i} ({role_for_debug}) - Segment became EMPTY after FILE_CONTENT_HEADER_PATTERN.")
                current_processing_segment = modified_segment_step1

                # 2. 添付画像の置換
                def replace_attached_image_debug(match):
                    file_path = match.group(1)
                    original_filename = match.group(2)
                    alt_text = re.sub(r"[\[\]()]", "", original_filename) # Sanitize alt text
                    encoded_file_path = urllib.parse.quote(file_path, safe=' /')
                    url_path = f"/file={encoded_file_path}"
                    return f"![{alt_text}]({url_path})"
                modified_segment_step2 = re.sub(ATTACHED_IMAGE_PATTERN, replace_attached_image_debug, current_processing_segment)
                if current_processing_segment != modified_segment_step2 or ("[ファイル添付:" in current_processing_segment):
                    print(f"DEBUG_FORMAT_WRAPPER: Entry {i} ({role_for_debug}) - After ATTACHED_IMAGE_PATTERN: '{modified_segment_step2[:200]}...'")
                if current_processing_segment.strip() and not modified_segment_step2.strip() and "[ファイル添付:" in current_processing_segment :
                     print(f"DEBUG_FORMAT_WRAPPER: WARNING! Entry {i} ({role_for_debug}) - Segment became EMPTY after ATTACHED_IMAGE_PATTERN.")
                current_processing_segment = modified_segment_step2

                # 3. 生成画像の置換
                def replace_generated_image_debug(match):
                    image_path = match.group(1)
                    encoded_image_path = urllib.parse.quote(image_path, safe=' /')
                    url_path = f"/file={encoded_image_path}"
                    return f"![generated_image]({url_path})"
                modified_segment_step3 = re.sub(GENERATED_IMAGE_PATTERN, replace_generated_image_debug, current_processing_segment)
                if current_processing_segment != modified_segment_step3 or ("[Generated Image:" in current_processing_segment):
                    print(f"DEBUG_FORMAT_WRAPPER: Entry {i} ({role_for_debug}) - After GENERATED_IMAGE_PATTERN: '{modified_segment_step3[:200]}...'")
                if current_processing_segment.strip() and not modified_segment_step3.strip() and "[Generated Image:" in current_processing_segment:
                     print(f"DEBUG_FORMAT_WRAPPER: WARNING! Entry {i} ({role_for_debug}) - Segment became EMPTY after GENERATED_IMAGE_PATTERN.")
                current_processing_segment = modified_segment_step3

                print(f"DEBUG_FORMAT_WRAPPER: Entry {i} ({role_for_debug}) - Final value for segment: '{current_processing_segment[:200]}...'")
                final_pair_for_output.append(current_processing_segment)
            else: # message_content_segment is None
                final_pair_for_output.append(None)

        processed_history_output.append(final_pair_for_output)

    print(f"Debug: format_history_for_gradio_wrapper processed_history_output (last 3 pairs): {processed_history_output[-3:]}")
    return processed_history_output
