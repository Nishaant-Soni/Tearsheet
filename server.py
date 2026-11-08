from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

# This is the shared MCP server instance
mcp = MCPServer("tearsheet")

# Tools that only read from Yahoo Finance.
READ_ONLY_REMOTE = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True
)

# Tools that only compute on their inputs, with no external calls.
PURE_COMPUTE = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)
