# cognee_manager.py (Phase 1 Temporary Stub)

class CogneeStub:
    """
    This is a temporary stub class to stand in for the real Cognee client.
    It provides an `add` method so that other parts of the application
    can call it without causing a runtime error.
    """
    def add(self, messages):
        print(f"--- [Cognee Stub] Received {len(messages)} messages to add to memory. This is a stub and does nothing. ---")
        pass

_cognee_instance = None

def get_cognee_instance():
    """
    Initializes and returns the Cognee instance.
    This is a temporary stub that returns an object with a no-op `add` method.
    """
    global _cognee_instance
    if _cognee_instance is None:
        print("--- [情報] Cognee Managerが初期化されました (スタブ) ---")
        _cognee_instance = CogneeStub()
    return _cognee_instance
