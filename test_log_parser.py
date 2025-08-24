import unittest
import os
import sys

# Add the root directory to the Python path to allow importing 'utils'
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from utils import load_chat_log

class TestLogParser(unittest.TestCase):

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
