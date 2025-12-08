
import unittest
import tempfile
import os
import shutil

def is_redundant_log_update(last_log_content: str, new_content: str) -> bool:
    """
    Determines if the new_content is redundant based on the last_log_content.
    Redundant if:
    1. Exact match.
    2. new_content is a suffix of last_log_content (and shorter).
    """
    if not last_log_content or not new_content:
        return False
    
    clean_last = last_log_content.strip()
    clean_new = new_content.strip()

    if not clean_last or not clean_new:
        return False

    # 1. Exact Match
    if clean_last == clean_new:
        return True
    
    # 2. Suffix Overlap (The "Cut off" case)
    # Example: Last="Hello world.", New="world."
    # We only care if the new content is fully contained at the END of the last content.
    if clean_last.endswith(clean_new) and len(clean_new) < len(clean_last):
        return True
        
    return False

class TestLogDeduplication(unittest.TestCase):
    
    def test_exact_match(self):
        self.assertTrue(is_redundant_log_update("Hello world.", "Hello world."))
        self.assertTrue(is_redundant_log_update("Test", "Test"))

    def test_suffix_overlap(self):
        # The reported bug case
        self.assertTrue(is_redundant_log_update("Hello world.", "world."))
        self.assertTrue(is_redundant_log_update("Hello world.", "ld."))
        self.assertTrue(is_redundant_log_update("This is a test.", "test."))

    def test_no_overlap(self):
        self.assertFalse(is_redundant_log_update("Hello world.", "Goodbye."))
        self.assertFalse(is_redundant_log_update("Hello world.", "Hello")) # Prefix is NOT redundant (it might be a correction or new start?) 
        # Actually, if it's a prefix, it might be a partial stream restart? 
        # But the bug report says "second instance is often slightly truncated", implying it's a suffix or substring.
        # If I have "Hello world" and I try to append "Hello", that would look like "Hello worldHello".
        # If the bug is "Hello world" -> "world", that's a suffix.
        
    def test_new_content_longer(self):
        self.assertFalse(is_redundant_log_update("Hello", "Hello world"))

    def test_empty(self):
        self.assertFalse(is_redundant_log_update("", "New"))
        self.assertFalse(is_redundant_log_update("Old", ""))

if __name__ == '__main__':
    unittest.main()
