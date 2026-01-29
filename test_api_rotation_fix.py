import unittest
from unittest.mock import MagicMock, patch
import os
import sys

# Add current dir to path
sys.path.append(os.getcwd())

import gemini_api
import config_manager
from google.api_core.exceptions import ResourceExhausted
from langchain_core.messages import AIMessage

class TestApiRotation(unittest.TestCase):
    
    @patch('config_manager.GEMINI_API_KEYS', {"key1": "AIza1", "key2": "AIza2"})
    @patch('config_manager.CONFIG_GLOBAL', {"enable_api_key_rotation": True})
    @patch('config_manager.mark_key_as_exhausted')
    @patch('config_manager.get_next_available_gemini_key')
    @patch('agent.graph.app.stream')
    @patch('config_manager.get_effective_settings')
    @patch('room_manager.get_room_files_paths')
    @patch('utils.load_chat_log')
    def test_rotation_on_429(self, mock_load_log, mock_paths, mock_settings, mock_stream, mock_get_next, mock_mark):
        # Setup
        mock_paths.return_value = (None, None, None, None, None, None)
        mock_load_log.return_value = []
        mock_settings.return_value = {"model_name": "gemini-1.5-flash", "display_thoughts": True, "enable_api_key_rotation": True}
        
        # Simulating 429
        error_429 = ResourceExhausted("429 RESOURCE_EXHAUSTED")
        
        def stream_side_effect(*args, **kwargs):
            if mock_mark.call_count == 0:
                raise error_429
            else:
                yield ("values", {"messages": [AIMessage(content="Success with key2")]})
                
        mock_stream.side_effect = stream_side_effect
        
        # Setup rotation
        mock_get_next.side_effect = ["key2", None]
        
        # Arguments for invoke_nexus_agent_stream
        agent_args = {
            "room_to_respond": "test_room",
            "api_key_name": "key1",
            "api_history_limit": "all",
            "debug_mode": False,
            "history_log_path": None,
            "user_prompt_parts": [],
            "soul_vessel_room": "test_room",
            "active_participants": [],
            "active_attachments": [],
            "shared_location_name": "Test",
            "shared_scenery_text": "Test Scenery",
            "season_en": "winter",
            "time_of_day_en": "night"
        }
        
        # Execute
        results = list(gemini_api.invoke_nexus_agent_stream(agent_args))
        
        # Verify
        mock_mark.assert_called_with("key1")
        print("Verification: mark_key_as_exhausted called for key1")
        
        success_found = False
        for r in results:
            if r[0] == "values" and isinstance(r[1].get("messages", [None])[0], AIMessage):
                if "Success with key2" in r[1]["messages"][0].content:
                    success_found = True
        
        self.assertTrue(success_found, "Should have rotated and succeeded with key2")
        print("Verification: Rotated and succeeded with key2")

if __name__ == "__main__":
    unittest.main()
