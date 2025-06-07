# VERSION 2
import unittest
from unittest.mock import patch
from utils import format_history_for_gradio # Assuming utils.py is in the same directory or accessible via PYTHONPATH
import os

# Helper to compare lists of model parts when order might be flexible for different types
# For this set of tests, the order is quite fixed by the implementation, so direct comparison is mostly used.
def assertModelPartsEqual(test_case, result_parts, expected_parts):
    if isinstance(result_parts, str) and isinstance(expected_parts, str):
        test_case.assertEqual(result_parts, expected_parts)
    elif isinstance(result_parts, list) and isinstance(expected_parts, list):
        test_case.assertEqual(len(result_parts), len(expected_parts), "Number of model parts differ")
        # For more complex scenarios with varying order, a more sophisticated check would be needed.
        # However, the current function has a predictable order of appends.
        for i in range(len(result_parts)):
            test_case.assertEqual(result_parts[i], expected_parts[i], f"Part {i} differs")
    elif isinstance(result_parts, tuple) and isinstance(expected_parts, tuple): # For single image case
        test_case.assertEqual(result_parts, expected_parts)
    else:
        test_case.fail(f"Result parts type ({type(result_parts)}) and expected parts type ({type(expected_parts)}) mismatch or unhandled combination.")


class TestFormatHistoryForGradio(unittest.TestCase):

    def test_empty_input(self):
        messages = []
        expected_output = []
        result = format_history_for_gradio(messages)
        self.assertEqual(result, expected_output)

    def test_user_message_only(self):
        messages = [{'role': 'user', 'content': 'Hello AI!'}]
        expected_output = [('Hello AI!', None)]
        result = format_history_for_gradio(messages)
        self.assertEqual(result, expected_output)

    def test_only_main_text(self):
        messages = [{'role': 'model', 'content': 'This is the main response.'}]
        expected_output = [(None, 'This is the main response.')]
        result = format_history_for_gradio(messages)
        self.assertEqual(result, expected_output)

    def test_main_text_with_thought_logs_suffix(self):
        messages = [{'role': 'model', 'content': '【Thoughts】Thinking...【/Thoughts】This is the main response after thoughts.'}]
        expected_output = [(None, ["<div class='thoughts'><pre><code>Thinking...</code></pre></div>", 'This is the main response after thoughts.'])]
        result = format_history_for_gradio(messages)
        self.assertEqual(result, expected_output)

    def test_main_text_with_thought_logs_mixed(self):
        messages = [{'role': 'model', 'content': 'This is before thoughts. 【Thoughts】Thinking...【/Thoughts】This is after thoughts.'}]
        # Expected: Thoughts block first, then the combined remaining text.
        expected_output = [(None, ["<div class='thoughts'><pre><code>Thinking...</code></pre></div>", 'This is before thoughts. This is after thoughts.'])]
        result = format_history_for_gradio(messages)
        self.assertEqual(result, expected_output)

    @patch('os.path.exists')
    def test_main_text_with_image_tag_prefix(self, mock_exists):
        mock_exists.return_value = True
        messages = [{'role': 'model', 'content': 'Look at this: [Generated Image: /path/to/image.png]'}]
        # Expected: Image tuple, then the text part. The current code appends main_text last.
        # The text "Look at this:" should be part of the main_text.
        expected_output = [(None, [('/path/to/image.png', 'image.png'), 'Look at this:'])]
        result = format_history_for_gradio(messages)
        self.assertEqual(result, expected_output)


    @patch('os.path.exists')
    def test_main_text_with_image_tag_suffix(self, mock_exists):
        mock_exists.return_value = True
        messages = [{'role': 'model', 'content': '[Generated Image: /path/to/image.png] Look at this after image.'}]
        # Expected: Image tuple, then the text part.
        expected_output = [(None, [('/path/to/image.png', 'image.png'), 'Look at this after image.'])]
        result = format_history_for_gradio(messages)
        self.assertEqual(result, expected_output)

    @patch('os.path.exists')
    def test_image_tag_not_found(self, mock_exists):
        mock_exists.return_value = False # Simulate image file NOT existing
        messages = [{'role': 'model', 'content': 'Image here: [Generated Image: /path/to/nonexistent.png] and text.'}]
        # Expected: Error message for image, then text part. Ensuring single space.
        expected_output = [(None, ['*[表示エラー: 画像ファイルが見つかりません (nonexistent.png)]*', 'Image here: and text.'])]
        result = format_history_for_gradio(messages)
        self.assertEqual(result, expected_output)


    @patch('os.path.exists')
    def test_main_text_with_thought_logs_and_image_tag(self, mock_exists):
        mock_exists.return_value = True
        messages = [{'role': 'model', 'content': '【Thoughts】Thinking...【/Thoughts】Here is an image [Generated Image: /path/to/image.png] and some text.'}]
        # Order: Thoughts, Image, Main Text. Ensuring single space.
        expected_output = [(None, [
            "<div class='thoughts'><pre><code>Thinking...</code></pre></div>",
            ('/path/to/image.png', 'image.png'),
            'Here is an image and some text.'
        ])]
        result = format_history_for_gradio(messages)
        self.assertEqual(result, expected_output)

    def test_main_text_with_model_text_response_tag(self):
        messages = [{'role': 'model', 'content': '[画像モデルからのテキスト]: This is a text from the image model. And this is the main response.'}]
        # Order: Image Model Text, Main Text
        expected_output = [(None, [
            'This is a text from the image model.',
            'And this is the main response.'
        ])]
        result = format_history_for_gradio(messages)
        self.assertEqual(result, expected_output)

    def test_main_text_with_error_tag(self):
        messages = [{'role': 'model', 'content': '[ERROR]: An error occurred. But this is still some main text.'}]
        # Order: Error Text, Main Text
        expected_output = [(None, [
            'An error occurred.',
            'But this is still some main text.'
        ])]
        result = format_history_for_gradio(messages)
        self.assertEqual(result, expected_output)

    @patch('os.path.exists')
    def test_complex_scenario_mixed_content(self, mock_exists):
        mock_exists.return_value = True
        messages = [{
            'role': 'model',
            'content': 'Preamble. 【Thoughts】Detailed thoughts.【/Thoughts】 Intermediary text. [Generated Image: /path/to/image.png] Text after image. [画像モデルからのテキスト]: Img model says hi. Post-image-model text.'
        }]
        # Expected order: Thoughts, Img Model Text, Image, Main Text
        # Main text combines: 'Preamble. Intermediary text. Text after image. Post-image-model text.' Ensuring single spaces.
        expected_output = [(None, [
            "<div class='thoughts'><pre><code>Detailed thoughts.</code></pre></div>",
            'Img model says hi.',
            ('/path/to/image.png', 'image.png'),
            'Preamble. Intermediary text. Text after image. Post-image-model text.'
        ])]
        result = format_history_for_gradio(messages)
        self.assertEqual(result, expected_output)

    def test_user_then_model_message(self):
        messages = [
            {'role': 'user', 'content': 'Hello AI!'},
            {'role': 'model', 'content': '【Thoughts】Thinking...【/Thoughts】Hello User!'}
        ]
        expected_output = [
            ('Hello AI!', [
                "<div class='thoughts'><pre><code>Thinking...</code></pre></div>",
                'Hello User!'
            ])
        ]
        result = format_history_for_gradio(messages)
        self.assertEqual(result, expected_output)

    def test_content_only_thoughts(self):
        messages = [{'role': 'model', 'content': '【Thoughts】Only thoughts.【/Thoughts】'}]
        # When only one part, it's not a list
        expected_output = [(None, "<div class='thoughts'><pre><code>Only thoughts.</code></pre></div>")]
        result = format_history_for_gradio(messages)
        self.assertEqual(result, expected_output)

    @patch('os.path.exists')
    def test_content_only_image(self, mock_exists):
        mock_exists.return_value = True
        messages = [{'role': 'model', 'content': '[Generated Image: /path/to/image.png]'}]
        # When only one part, it's not a list
        expected_output = [(None, ('/path/to/image.png', 'image.png'))]
        result = format_history_for_gradio(messages)
        self.assertEqual(result, expected_output)

    def test_content_only_model_text_response(self):
        messages = [{'role': 'model', 'content': '[画像モデルからのテキスト]: Just image model text.'}]
        expected_output = [(None, 'Just image model text.')]
        result = format_history_for_gradio(messages)
        self.assertEqual(result, expected_output)

    def test_content_only_error(self):
        messages = [{'role': 'model', 'content': '[ERROR]: Just an error.'}]
        expected_output = [(None, 'Just an error.')]
        result = format_history_for_gradio(messages)
        self.assertEqual(result, expected_output)

    def test_content_with_image_prompt_tag(self):
        messages = [{'role': 'model', 'content': '[画像生成に使用されたプロンプト]: A cat. This is the actual response.'}]
        expected_output = [(None, 'This is the actual response.')]
        result = format_history_for_gradio(messages)
        self.assertEqual(result, expected_output)

    def test_content_with_image_prompt_tag_and_thoughts(self):
        messages = [{'role': 'model', 'content': '【Thoughts】A thought.【/Thoughts】[画像生成に使用されたプロンプト]: A cat. This is the actual response.'}]
        expected_output = [(None, ["<div class='thoughts'><pre><code>A thought.</code></pre></div>", 'This is the actual response.'])]
        result = format_history_for_gradio(messages)
        self.assertEqual(result, expected_output)

    @patch('os.path.exists')
    def test_content_with_image_prompt_tag_and_image(self, mock_exists):
        mock_exists.return_value = True
        messages = [{'role': 'model', 'content': '[Generated Image: /path/to/img.png][画像生成に使用されたプロンプト]: A cat. This is the actual response.'}]
        # Image, then main text. Prompt is removed.
        expected_output = [(None, [('/path/to/img.png', 'img.png'), 'This is the actual response.'])]
        result = format_history_for_gradio(messages)
        self.assertEqual(result, expected_output)

    def test_thoughts_identical_to_main_text_scenario(self):
        # Scenario where main_text after stripping other tags might be identical to thoughts_content
        messages = [{'role': 'model', 'content': '【Thoughts】This is a thought.【/Thoughts】This is a thought.'}]
        # The duplicate "This is a thought." should be appended as main_text because the check is
        # `if processed_main_text == thoughts_content_original`. If `main_text` becomes identical to `thoughts_content`
        # *after* other tags are removed, it should still be appended if it's not the *exact same segment*
        # that was parsed as thoughts.
        # The current deduplication logic `if processed_main_text == thoughts_content_original:` where `thoughts_content_original`
        # is `thought_match.group(1).strip()` means if the *remaining* text is identical to the *original* thought content,
        # it will be skipped.
        # Let's test the implemented behavior:
        # Original: "【Thoughts】T【/Thoughts】T" -> thoughts_content="T", main_text="T" -> processed_main_text="T"
        # Comparison: "T" == "T" is true. So, main_text part is skipped.
        expected_output = [(None, "<div class='thoughts'><pre><code>This is a thought.</code></pre></div>")]
        result = format_history_for_gradio(messages)
        self.assertEqual(result, expected_output)

        messages = [{'role': 'model', 'content': '【Thoughts】Thought A.【/Thoughts】Main text. Thought A.'}]
        # Here, "Main text. Thought A." is the main_text. It's not identical to "Thought A."
        expected_output = [(None, ["<div class='thoughts'><pre><code>Thought A.</code></pre></div>", 'Main text. Thought A.'])]
        result = format_history_for_gradio(messages)
        self.assertEqual(result, expected_output)

    def test_user_message_with_attachment_and_newline_timestamp(self):
        messages = [{'role': 'user', 'content': '[file_attachment:/tmp/file.txt;file.txt;text/plain]\n2023-01-01 10:00:00'}]
        expected_output = [('添付ファイル: file.txt\n2023-01-01 10:00:00', None)]
        result = format_history_for_gradio(messages)
        self.assertEqual(result, expected_output)

    def test_user_message_with_attachment_and_inline_timestamp(self):
        messages = [{'role': 'user', 'content': '[file_attachment:/tmp/file.txt;file.txt;text/plain] 2023-01-01 10:00:00'}]
        # The space before timestamp means it's considered part of the "timestamp_str" by the regex if not starting with newline
        # The logic is `display_text_for_user_turn += f" ({timestamp_str})" if not display_text_for_user_turn.endswith(timestamp_str) else ""`
        # So it becomes "添付ファイル: file.txt (2023-01-01 10:00:00)"
        expected_output = [('添付ファイル: file.txt (2023-01-01 10:00:00)', None)]
        result = format_history_for_gradio(messages)
        self.assertEqual(result, expected_output)

    def test_consecutive_user_messages(self):
        messages = [
            {'role': 'user', 'content': 'User message 1'},
            {'role': 'user', 'content': 'User message 2'}
        ]
        # The implementation should handle this by pairing the first user message with None,
        # and the second one will be in the accumulator, then also paired with None at the end.
        expected_output = [
            ('User message 1', None),
            ('User message 2', None)
        ]
        result = format_history_for_gradio(messages)
        self.assertEqual(result, expected_output)


if __name__ == '__main__':
    unittest.main()
