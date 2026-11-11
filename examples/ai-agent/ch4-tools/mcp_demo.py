"""Pinned MCP 2025-11-25 stdio demo; synthetic data, fixed local identity."""
import asyncio
import json
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp import FastMCP

server = FastMCP("chapter4-task-demo")


@server.tool()
def get_task_status(task_id: str) -> str:
    """Read the task visible to the fixed local demo principal."""
    # This fixed identity is a test fixture, not authentication for a real user.
    if task_id != "task-42":
        raise PermissionError("task access denied")
    return json.dumps({"task_id": task_id, "status": "RUNNING"})


async def client():
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(Path(__file__).resolve()), "--server"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            initialized = await session.initialize()
            assert initialized.protocolVersion == "2025-11-25"
            print("protocol:", initialized.protocolVersion)
            catalog = await session.list_tools()
            assert [tool.name for tool in catalog.tools] == ["get_task_status"]
            print("tools:", catalog.tools[0].name)
            result = await session.call_tool("get_task_status", {"task_id": "task-42"})
            assert not result.isError
            data = json.loads(result.content[0].text)
            assert data == {"task_id": "task-42", "status": "RUNNING"}
            print("task-42:", data["status"])
            denied = await session.call_tool("get_task_status", {"task_id": "task-99"})
            assert denied.isError
            print("task-99: isError=true")


if __name__ == "__main__":
    if "--server" in sys.argv:
        # stdio stdout is reserved for protocol messages.
        server.run(transport="stdio")
    else:
        asyncio.run(client())
