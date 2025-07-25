import unittest
import os
import sys
from unittest.mock import MagicMock, patch

# モジュール検索パスにカレントディレクトリを追加
sys.path.append(os.getcwd())

import ui_handlers
import config_manager
import character_manager

class TestTokenCounter(unittest.TestCase):

    def setUp(self):
        # テスト用のキャラクターを作成
        self.character_name = "test_character"
        character_manager.ensure_character_files(self.character_name)

        # テスト用の設定
        config_manager.save_config("last_character", self.character_name)
        config_manager.save_config("last_model", "gemini-1.5-flash")
        config_manager.save_config("last_api_key_name", "default")
        config_manager.API_KEYS["default"] = "test_api_key"

    @patch('gemini_api.get_model_token_limits')
    @patch('gemini_api.count_input_tokens')
    def test_update_token_count(self, mock_count_input_tokens, mock_get_model_token_limits):
        # 依存する関数をモック化
        mock_count_input_tokens.return_value = 123
        mock_get_model_token_limits.return_value = {"input": 10000}

        # update_token_countを呼び出す
        result = ui_handlers.update_token_count(
            textbox_content="こんにちは",
            file_input_list=[],
            current_character_name=self.character_name,
            current_model_name="gemini-1.5-flash",
            current_api_key_name_state="default",
            api_history_limit_state="10",
            send_notepad_state=False,
            notepad_editor_content="",
            use_common_prompt_state=False
        )

        # 想定される返り値
        expected_return = "入力トークン数: 123 / 10000"

        # 結果を検証
        self.assertEqual(expected_return, result)

        # 依存関数が正しく呼び出されたか検証
        mock_count_input_tokens.assert_called_once()
        mock_get_model_token_limits.assert_called_once()


if __name__ == '__main__':
    unittest.main()
