# mcp_server.py

import uvicorn
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
import json
import rag_manager
import character_manager
import config_manager
import gemini_api

# --- データモデル定義 ---

class McpTool(BaseModel):
    name: str
    description: str
    input_schema: dict

class McpListToolsResponse(BaseModel):
    tools: list[McpTool]

class McpCallToolRequest(BaseModel):
    tool_run_id: str
    tool_name: str
    params: dict

class McpToolResult(BaseModel):
    tool_run_id: str
    output: str
    is_error: bool = False

# --- FastAPIアプリケーションの初期化 ---

app = FastAPI(
    title="Nexus Ark MCP Server for RAG",
    description="Provides RAG context as a tool to the Google CLI.",
    version="1.0.0"
)

# --- MCPエンドポイントの実装 ---

@app.on_event("startup")
async def startup_event():
    """
    サーバー起動時にRAGの初期設定を行う
    """
    print("[MCP Server] Startup sequence initiated.")
    try:
        config_manager.load_config()
        api_key_name = config_manager.initial_api_key_name_global
        if not api_key_name:
            print("[MCP Server] ERROR: No valid API key name found in config. RAG may not function.")
            return

        success, msg = gemini_api.configure_google_api(api_key_name)
        if not success:
            print(f"[MCP Server] ERROR: Failed to configure Gemini API: {msg}")
            return

        print("[MCP Server] Initializing RAG indices for all characters...")
        for char in character_manager.get_character_list():
            print(f"[MCP Server]  - Checking/Updating index for {char}...")
            rag_manager.create_or_update_index(char)
        print("[MCP Server] RAG indices initialization complete.")

    except Exception as e:
        print(f"[MCP Server] Critical error during startup: {e}")

@app.post("/mcp/list_tools", response_model=McpListToolsResponse)
async def list_tools():
    """
    利用可能なツール（今回はRAG検索ツール）の定義を返す。
    """
    rag_tool = McpTool(
        name="get_rag_context",
        description="指定されたキャラクターの記憶とログから、現在の会話に関連する情報を検索して取得します。AI自身の知識にない情報や、過去の特定のやり取りについて答える場合に非常に有効です。",
        input_schema={
            "type": "object",
            "properties": {
                "character_name": {
                    "type": "string",
                    "description": "情報を検索する対象のキャラクター名"
                },
                "query": {
                    "type": "string",
                    "description": "検索に使用するキーワードや質問文"
                },
                "top_k": {
                    "type": "integer",
                    "description": "取得する情報の最大数（デフォルトは5）",
                    "default": 5
                }
            },
            "required": ["character_name", "query"]
        }
    )
    return McpListToolsResponse(tools=[rag_tool])

@app.post("/mcp/call_tool", response_model=McpToolResult)
async def call_tool(request: McpCallToolRequest):
    """
    ツール実行のリクエストに応じて、RAG検索を実行し結果を返す。
    """
    if request.tool_name != "get_rag_context":
        raise HTTPException(status_code=400, detail=f"Unknown tool: {request.tool_name}")

    try:
        char_name = request.params.get("character_name")
        query = request.params.get("query")
        top_k = request.params.get("top_k", 5)

        if not char_name or not query:
            raise HTTPException(status_code=422, detail="Missing required parameters: character_name, query")

        print(f"[MCP Server] Executing RAG search for '{char_name}' with query: '{query[:30]}...'")

        relevant_chunks = rag_manager.search_relevant_chunks(char_name, query, top_k)

        if not relevant_chunks:
            output_text = "関連情報は見つかりませんでした。"
        else:
            output_text = "以下に関連性の高い情報が見つかりました。\n\n" + "\n\n---\n\n".join(relevant_chunks)

        print(f"[MCP Server] RAG search complete. Returning {len(relevant_chunks)} chunk(s).")
        return McpToolResult(tool_run_id=request.tool_run_id, output=output_text)

    except Exception as e:
        print(f"[MCP Server] Error during RAG search: {e}")
        return McpToolResult(
            tool_run_id=request.tool_run_id,
            output=f"RAG検索中にエラーが発生しました: {e}",
            is_error=True
        )

# --- サーバーを直接実行するためのコード ---
if __name__ == "__main__":
    print("Starting Nexus Ark MCP Server...")
    uvicorn.run(f"{__name__}:app", host="127.0.0.1", port=8001)
