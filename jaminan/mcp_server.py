"""Jaminan MCP server: four tools a booking agent can call, over the deployed Jaminan API (stdio).

    claude mcp add jaminan -- python -m jaminan.mcp_server

An agent can look, price and ask; only the renter pays. `start_rental` returns a PayPal approval link for a human:
the renter logs in to PayPal and approves the fee + deposit hold there. No tool approves, accepts or contests a
damage line, captures, voids or refunds, and the API routes these tools call (api/index.py, /api/agent/*) never
hand this process a shop or renter key, so there is nothing to call those actions with. Sandbox only.

Needs only `mcp` and `httpx`; JAMINAN_API_URL points it at another deploy (default: the live one).
"""
from __future__ import annotations

import os
import re
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

API = os.environ.get("JAMINAN_API_URL", "https://jaminan.edycu.dev").rstrip("/")
ID = re.compile(r"^[A-Za-z0-9-]{1,40}$")  # shop, vehicle and rental ids: also keeps a path segment a path segment
READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)
BOOK = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True)

mcp = MCPServer(
    "jaminan", version="1",
    instructions="Book a scooter at a Jaminan shop for a human renter (PayPal sandbox). list_vehicles → quote_rental "
                 "→ start_rental gives a PayPal link: send it to the renter, who approves the fee + refundable deposit "
                 "hold in PayPal. You cannot approve, accept or contest damage, capture, void or refund. get_rental "
                 "reads the state and PayPal's record.")
# status tokens from this session's bookings, so get_rental(rental_id) works without the agent re-sending one
_tokens: dict[str, str] = {}


def _id(value: str, name: str) -> str:
    if not isinstance(value, str) or not ID.match(value):
        raise ToolError(f"{name} must be letters, digits and dashes (got {value!r})")
    return value


def _days(days: int) -> int:
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 28:
        raise ToolError("days must be a whole number from 1 to 28 (a PayPal hold lives 29 days)")
    return days


def _call(method: str, path: str, **kw: Any) -> dict:
    """One request to the Jaminan API. Every refusal becomes a plain one-line tool error, never a trace."""
    try:
        r = httpx.request(method, API + path, timeout=60, headers={"User-Agent": "jaminan-mcp/1"}, **kw)
    except httpx.HTTPError as e:
        raise ToolError(f"the Jaminan API did not answer ({type(e).__name__}); try again") from None
    try:
        body = r.json()
    except ValueError:
        body = None
    if r.status_code >= 400 or not isinstance(body, dict):
        b = body if isinstance(body, dict) else {}
        raise ToolError(f"{b.get('error') or r.status_code}: {b.get('message') or 'the Jaminan API refused this'}")
    return body


@mcp.tool(annotations=READ)
def list_vehicles(shop_id: str = "shop-demo") -> dict:
    """The scooters a shop rents, with the daily fee and the refundable deposit (USD cents)."""
    b = _call("GET", f"/api/shops/{_id(shop_id, 'shop_id')}")
    return {"shop": {k: b["shop"].get(k) for k in ("id", "name", "city")},
            "vehicles": [{k: v.get(k) for k in ("id", "label", "kind", "daily_fee_cents", "deposit_cents")}
                         for v in b["vehicles"]],
            "tariff": {k: b["tariff"].get(k) for k in ("id", "sha256")}}


@mcp.tool(annotations=READ)
def quote_rental(vehicle_id: str, days: int) -> dict:
    """Price a rental before booking: fee + deposit = the PayPal hold, with the tariff version and its SHA-256."""
    return _call("GET", "/api/agent/quote", params={"vehicle_id": _id(vehicle_id, "vehicle_id"), "days": _days(days)})


@mcp.tool(annotations=BOOK)
def start_rental(vehicle_id: str, days: int, renter_email: str) -> dict:
    """Book for a human renter. Returns approve_url, a PayPal link for THE RENTER to open and approve; the rental
    stays DRAFT, and no money is held, until they do. Send them the link; you cannot approve it yourself."""
    email = renter_email.strip() if isinstance(renter_email, str) else ""
    if "@" not in email:
        raise ToolError("renter_email must be the renter's email address")
    b = _call("POST", "/api/agent/rentals",
              json={"vehicle_id": _id(vehicle_id, "vehicle_id"), "days": _days(days), "renter_email": email})
    _tokens[b["rental_id"]] = b["status_token"]
    return {**b, "next": "Send approve_url to the renter. Only they can approve the hold, in PayPal. "
                         "Then get_rental shows the authorization PayPal holds."}


@mcp.tool(annotations=READ)
def get_rental(rental_id: str, status_token: str | None = None) -> dict:
    """Read a rental this agent booked: its state and PayPal's own record (the order before the renter approves,
    the authorization hold after). status_token is only needed in a new session (start_rental returned it)."""
    rid = _id(rental_id, "rental_id")
    token = status_token or _tokens.get(rid)
    if not token:
        raise ToolError(f"no status_token for {rid}: pass the one start_rental returned")
    return _call("GET", f"/api/agent/rentals/{rid}", params={"t": token})


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
