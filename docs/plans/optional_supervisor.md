# Implementation Plan - Optional Supervisor Feature

## Goal
Make the "Supervisor" feature optional and toggleable via the UI. It should be **disabled by default** to avoid performance issues and unnecessary API calls.

## User Review Required
> !IMPORTANT
> The Supervisor feature will be OFF by default. You need to enable it in the Group Chat menu to use it.

## Proposed Changes

### Configuration & State
#### [MODIFY] [agent/graph.py](../../agent/graph.py)
- Update `AgentState` to include `enable_supervisor: bool`.
- Update `supervisor_node` to check this flag. If `False`, it should behave as a pass-through (or return `{"next": "state['room_name']"}` effectively skipping orchestration).
- **Correction**: Actually, if Supervisor is the entry point, skipping it means we need to decide where to go.
    - If `enable_supervisor` is False: Immediately return `{"next": state["room_name"]}` (which is the current character) or better yet, we might need a bypass edge, but returning the current room name is the simplest way to "just let the current person talk".
    - Wait, if it's a group chat, "current person" might be ambiguous if we just started.
    - If disabled, we rely on the user manually selecting who they speak to (which is the current `room_to_respond` passed from UI). So `next` should be `state["room_name"]`.

### UI Implementation
#### [MODIFY] [nexus_ark.py](../../nexus_ark.py)
- Add a Checkbox `enable_supervisor_cb` in the Group Chat settings area.
- **Label**: `AI自動進行（司会モード）`
- Default value: `False`.
- Pass this value to the chat submission event handler.

#### [MODIFY] [ui_handlers.py](../../ui_handlers.py)
- Update `_stream_and_handle_response` and `invoke_nexus_agent_stream` to accept `enable_supervisor` argument.
- Pass this flag into the `initial_state` of the graph.

## Verification Plan
### Manual Verification
1.  **Check UI:** Launch the app and verify the "Enable Supervisor" checkbox appears and is unchecked by default.
2.  **Test OFF (Default):**
    - Start a group chat.
    - Send a message to Character A.
    - Verify that Character A responds and the turn ends there (no Supervisor log, no auto-routing to B).
3.  **Test ON:**
    - Enable the checkbox.
    - Send a message.
    - Verify that Supervisor log appears and it attempts to route the conversation.
