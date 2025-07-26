# gemini_api.py を修正
def invoke_nexus_agent(*args: Any) -> dict:
    # ...
    try:
        # ...
        return {
            "response": final_response_text,
            "scenery": latest_scenery
        }
    except Exception as e:
        # ...
        return {"response": f"[エージェント実行エラー: {e}]", "scenery": "（エラー）"}
