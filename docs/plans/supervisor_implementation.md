# Implementation Plan - LangGraph Supervisor

## Goal
Implement a "Supervisor" node in the LangGraph workflow to manage multi-agent orchestration and turn-taking. This supervisor will decide which agent (or user) speaks next.

## User Review Required
> !IMPORTANT
> The Supervisor will use `gemma-3-12b-it` by default. Ensure this model is available in your Google AI Studio account/API key.

## Proposed Changes

### Configuration
#### [MODIFY] [constants.py](file:///c:/Users/baken/OneDrive/デスクトップ/gradio_github/gradiotest/constants.py)
- Add `SUPERVISOR_MODEL` constant defaulting to `"gemma-3-12b-it"`.

### Agent Graph
#### [MODIFY] [agent/graph.py](file:///c:/Users/baken/OneDrive/デスクトップ/gradio_github/gradiotest/agent/graph.py)
- **Import Changes:** Import `SUPERVISOR_MODEL` from constants.
- **Supervisor Node:** Implement `supervisor_node` function.
    - Uses `SUPERVISOR_MODEL`.
    - Accepts `AgentState`.
    - Outputs a routing decision (next speaker or FINISH).
    - Uses structured output (JSON) to guarantee valid decisions.
- **Graph Structure:**
    - Insert `supervisor_node` into the workflow.
    - Update edges to route from Supervisor -> Agent -> Supervisor.

## Verification Plan
### Manual Verification
1.  **Start a Group Chat:** Create a room with multiple participants (if supported) or simulate it.
2.  **Observe Turn-Taking:** Verify that after an agent speaks, the Supervisor decides the next step (another agent or return to user).
3.  **Check Logs:** Confirm `gemma-3-12b-it` is being queried for routing decisions.
