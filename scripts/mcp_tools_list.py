"""Start the MCP server as an agent would (stdio subprocess), run `tools/list`, and write what it answered.

    .venv/bin/python scripts/mcp_tools_list.py evidence/mcp/tools-list.json
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import anyio
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]


async def main(out: Path) -> None:
    server = StdioServerParameters(command=sys.executable, args=["-m", "jaminan.mcp_server"], cwd=ROOT)
    async with Client(server) as c:
        tools = (await c.list_tools()).tools
    rows = [{"name": t.name, "description": t.description, "input_schema": t.input_schema,
             "annotations": t.annotations.model_dump(exclude_none=True) if t.annotations else None} for t in tools]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                               "transport": "stdio", "command": "python -m jaminan.mcp_server",
                               "count": len(rows), "tools": rows}, indent=2) + "\n")
    print(f"{len(rows)} tools: {', '.join(r['name'] for r in rows)} -> {out}")


if __name__ == "__main__":
    anyio.run(main, Path(sys.argv[1] if len(sys.argv) > 1 else "evidence/mcp/tools-list.json"))
