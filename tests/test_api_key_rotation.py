
import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Mock modules before importing gemini_api
sys.modules["agent.graph"] = MagicMock()
sys.modules["agent.graph"].app = MagicMock()

# Mock config_manager
mock_config_manager = MagicMock()
sys.modules["config_manager"] = mock_config_manager

# Mock other dependencies to avoid side effects
sys.modules["room_manager"] = MagicMock()
sys.modules["utils"] = MagicMock()
sys.modules["signature_manager"] = MagicMock()
sys.modules["episodic_memory_manager"] = MagicMock()
sys.modules["tiktoken"] = MagicMock()
sys.modules["google"] = MagicMock()
sys.modules["google.genai"] = MagicMock()
sys.modules["google.genai.errors"] = MagicMock()
sys.modules["langchain_core"] = MagicMock()
sys.modules["langchain_core.messages"] = MagicMock()
sys.modules["langchain_google_genai"] = MagicMock()
sys.modules["PIL"] = MagicMock()
sys.modules["filetype"] = MagicMock()
sys.modules["httpx"] = MagicMock()

# Define Fake Exceptions and Classes for testing
class ResourceExhausted(Exception):
    pass

class AIMessage:
    def __init__(self, content, **kwargs):
        self.content = content
        self.additional_kwargs = kwargs.get("additional_kwargs", {})
        self.response_metadata = kwargs.get("response_metadata", {})
        self.tool_calls = kwargs.get("tool_calls", [])
    
    def __repr__(self):
        return f"AIMessage(content='{self.content}')"

class HumanMessage:
    def __init__(self, content):
        self.content = content

# Inject Fakes into Mocks
sys.modules["google.api_core"] = MagicMock()
sys.modules["google.api_core.exceptions"] = MagicMock()
sys.modules["google.api_core.exceptions"].ResourceExhausted = ResourceExhausted
sys.modules["google.api_core.exceptions"].ServiceUnavailable = Exception
sys.modules["google.api_core.exceptions"].InternalServerError = Exception

sys.modules["langchain_core.messages"].AIMessage = AIMessage
sys.modules["langchain_core.messages"].HumanMessage = HumanMessage
sys.modules["langchain_core.messages"].SystemMessage = MagicMock()
sys.modules["langchain_core.messages"].ToolMessage = MagicMock()

# Mock google.genai.Client
sys.modules["google.genai"].Client = MagicMock()

# Now import gemini_api
import gemini_api
from google.api_core.exceptions import ResourceExhausted
from langchain_core.messages import AIMessage

class TestApiKeyRotation(unittest.TestCase):
    def setUp(self):
        # Reset mocks
        mock_config_manager.reset_mock()
        sys.modules["agent.graph"].app.reset_mock()
        
        # Configure room_manager mock to return a tuple for unpacking
        sys.modules["room_manager"].get_room_files_paths.return_value = (None, None, None, None, None, None)
        
        # Setup initial keys
        self.api_keys = {
            "key1": "fake_key_1",
            "key2": "fake_key_2",
            "key3": "fake_key_3"
        }
        mock_config_manager.GEMINI_API_KEYS = self.api_keys
        
        # Setup exhaustion tracking
        self.exhausted_keys = set()
        
        def mark_exhausted(key_name):
            self.exhausted_keys.add(key_name)
            
        def get_next_key(current_exhausted_key=None):
            # Simple simulation of get_next_available_gemini_key
            available = [k for k in self.api_keys.keys() if k not in self.exhausted_keys]
            if not available:
                return None
            return available[0]
            
        mock_config_manager.mark_key_as_exhausted.side_effect = mark_exhausted
        mock_config_manager.get_next_available_gemini_key.side_effect = get_next_key
        mock_config_manager.get_effective_settings.return_value = {
            "model_name": "gemini-1.5-pro",
            "enable_api_key_rotation": True,
            "api_key_name": "key1"
        }
        mock_config_manager.is_tool_use_enabled.return_value = True

    def test_rotation_success(self):
        """Test that rotation occurs when ResourceExhausted is raised"""
        
        # Setup app.invoke to fail once then succeed (simulating stream failure too if compatible)
        # Note: calling invoke_nexus_agent_stream calls app.stream or app.invoke
        # Let's say model is NOT gemini-3-flash so it calls app.stream
        
        # Mock app.stream
        # First call raises ResourceExhausted
        # Second call yields success
        
        # We need to simulate the iterator behavior of app.stream
        # It's tricky with side_effect being an iterator vs raising exception.
        
        # We can implement a generator for side_effect
        call_count = 0
        def stream_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ResourceExhausted("Quota exceeded")
            else:
                yield ("values", {"messages": [AIMessage(content="Success")]})
        
        sys.modules["agent.graph"].app.stream.side_effect = stream_side_effect
        
        agent_args = {
            "room_to_respond": "test_room",
            "api_key_name": "key1",
            "api_history_limit": "10",
            "debug_mode": False,
            "history_log_path": None,
            "user_prompt_parts": [],
            "soul_vessel_room": "soul",
            "active_participants": [],
            "active_attachments": [],
            "shared_location_name": "",
            "shared_scenery_text": "",
            "season_en": "spring",
            "time_of_day_en": "day",
        }
        
        # Run generator
        generator = gemini_api.invoke_nexus_agent_stream(agent_args)
        
        # Iterate
        results = list(generator)
        
        # Verify
        # 1. ResourceExhausted happened (implied by rotation)
        # 2. mark_key_as_exhausted called for key1
        mock_config_manager.mark_key_as_exhausted.assert_called_with("key1")
        
        # 3. get_next_available_gemini_key called
        mock_config_manager.get_next_available_gemini_key.assert_called()
        
        # 4. Success message received
        self.assertTrue(any("Success" in str(r) for r in results))

    def test_rotation_failure_all_exhausted(self):
        """Test failure when all keys are exhausted"""
        
        # All keys fail
        def stream_side_effect(*args, **kwargs):
             raise ResourceExhausted("Quota exceeded")
             
        sys.modules["agent.graph"].app.stream.side_effect = stream_side_effect
        
        agent_args = {
            "room_to_respond": "test_room",
            "api_key_name": "key1",
            "api_history_limit": "10",
            "debug_mode": False,
            "history_log_path": None,
            "user_prompt_parts": [],
            "soul_vessel_room": "soul",
            "active_participants": [],
            "active_attachments": [],
            "shared_location_name": "",
            "shared_scenery_text": "",
            "season_en": "spring",
            "time_of_day_en": "day",
        }
        
        generator = gemini_api.invoke_nexus_agent_stream(agent_args)
        results = list(generator)
        
        # Check that we got an error message about all keys exhausted
        final_error = results[-1]
        self.assertIn("すべてのAPIキーが使い果たされました", str(final_error))
        
        # Verify exhaustion of multiple keys
        # We start with key1, then key2, then key3. All should be marked exhausted.
        # calls to mark_exhausted should be for key1, key2, key3
        
        # Note: since get_next_key returns available keys, and we mark them exhausted one by one,
        # we should see calls for all of them.
        self.assertIn("key1", self.exhausted_keys)
        self.assertIn("key2", self.exhausted_keys)
        self.assertIn("key3", self.exhausted_keys)

    def test_rotation_disabled(self):
        """Test that rotation does not happen if disabled"""
        mock_config_manager.get_effective_settings.return_value = {
            "model_name": "gemini-1.5-pro",
            "enable_api_key_rotation": False, # Disabled
            "api_key_name": "key1"
        }
        
        # Fail
        sys.modules["agent.graph"].app.stream.side_effect = ResourceExhausted("Quota exceeded")
        
        agent_args = {
             "room_to_respond": "test_room",
             "api_key_name": "key1",
             "api_history_limit": "10",
            "debug_mode": False,
            "history_log_path": None,
            "user_prompt_parts": [],
            "soul_vessel_room": "soul",
            "active_participants": [],
            "active_attachments": [],
            "shared_location_name": "",
            "shared_scenery_text": "",
            "season_en": "spring",
            "time_of_day_en": "day",
        }
        
        generator = gemini_api.invoke_nexus_agent_stream(agent_args)
        results = list(generator)
        
        # Should return rotation disabled error
        final_error = results[-1]
        self.assertIn("APIキーローテーションは無効です", str(final_error))
        
        # Should NOT mark key as exhausted (or maybe we don't care, but strictly speaking we might not mark it if rotation is OFF? 
        # Actually logic is catch -> print -> check enabled. If not enabled, return.
        # So mark_key_as_exhausted is NOT called.)
        mock_config_manager.mark_key_as_exhausted.assert_not_called()

if __name__ == '__main__':
    unittest.main()
