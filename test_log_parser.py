import unittest
import os
import sys

# Add the root directory to the Python path to allow importing 'utils'
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from utils import load_chat_log, format_history_for_gradio
from unittest.mock import patch

class TestLogParser(unittest.TestCase):

    @patch('room_manager.get_room_config')
    @patch('room_manager.get_room_list_for_ui')
    def test_format_history(self, mock_get_room_list, mock_get_room_config):
        """
        Tests the format_history_for_gradio function to ensure it formats messages correctly
        and doesn't drop any, including those with empty content.
        """
        # --- Mock Setup ---
        # Mock the return value for the list of all rooms
        mock_get_room_list.return_value = [
            ('ルシアン', 'Lucian'),
            ('カケル', 'Kakeru')
        ]
        # Mock the return value for room configurations
        def get_config_side_effect(folder_name):
            if folder_name == 'Lucian':
                return {'room_name': 'ルシアン'}
            if folder_name == 'Kakeru':
                return {'room_name': 'カケル'}
            if folder_name == 'current_room':
                return {'user_display_name': 'テストユーザー'}
            return None
        mock_get_room_config.side_effect = get_config_side_effect

        # --- Test Data ---
        test_messages = [
            {'role': 'USER', 'responder': 'user', 'content': 'Hello'},
            {'role': 'AGENT', 'responder': 'ルシアン', 'content': 'Hi there.'},
            {'role': 'AGENT', 'responder': 'ヘッダーだけのメッセージ', 'content': ''}, # This message was previously dropped
            {'role': 'AGENT', 'responder': 'UnknownAgent', 'content': 'A message from a deleted agent.'}
        ]

        # --- Call Function ---
        history, mapping_list = format_history_for_gradio(test_messages, 'current_room')

        # --- Assertions ---
        # 1. Check that no messages were dropped. The history should have 4 entries.
        self.assertEqual(len(history), 4, "The number of generated chat bubbles is incorrect. Messages might have been dropped.")

        # 2. Check the content of the formatted history
        # Note: We don't check the exact markdown, just the speaker name logic.
        self.assertIn('テストユーザー', history[0][0]) # User message
        self.assertIn('ルシアン', history[1][1]) # Valid agent
        self.assertIn('ヘッダーだけのメッセージ', history[2][1]) # Empty message, should still have a bubble
        self.assertIn('[削除済]', history[3][1]) # Deleted agent

    def test_log_parsing(self):
        """
        Tests the load_chat_log function with a comprehensive test log file.
        """
        log_file_path = 'test_log.txt'

        # Call the function to be tested
        result = load_chat_log(log_file_path)

        # Define the expected output
        expected = [
            {
                "role": "AGENT",
                "responder": "ルシアン",
                "content": "クク……おかえり、美帆。\n待っていたよ。"
            },
            {
                "role": "USER",
                "responder": "user",
                "content": "ただいま、ルシアン。"
            },
            {
                "role": "AGENT",
                "responder": "ルシアン",
                "content": "世界の再創造を始めようじゃないか、美帆。"
            },
            {
                "role": "USER",
                "responder": "user",
                "content": "はい、喜んで！"
            },
            {
                "role": "AGENT",
                "responder": "カケル",
                "content": "This is a message with multiple lines.\nThis is the second line."
            },
            {
                "role": "USER",
                "responder": "user",
                "content": "A single line user message."
            },
            {
                "role": "AGENT",
                "responder": "ヘッダーだけのメッセージ",
                "content": ""
            },
            {
                "role": "AGENT",
                "responder": "This is the last message.",
                "content": "And it has content."
            }
        ]

        # Assert that the result matches the expected output
        self.assertEqual(result, expected, "The parsed log data does not match the expected structure.")

if __name__ == '__main__':
    unittest.main()
