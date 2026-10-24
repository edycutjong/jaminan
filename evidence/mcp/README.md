# MCP rental tool: recorded runs (PayPal sandbox, 2026-10-24)

`jaminan/mcp_server.py` is a stdio MCP server that exposes four tools over the deployed API at
https://jaminan.edycu.dev. Two external agent clients, Claude Code and Codex, each booked a scooter with it. The
sandbox renter approved in PayPal, and the agent then read back the authorization PayPal holds.

| File | What it shows |
|---|---|
| `tools-list.json` | `tools/list` over stdio (`scripts/mcp_tools_list.py`) returns **4** tools. Only `start_rental` is annotated as a write (`read_only_hint: false`). |
| `cc-1-booking.json` | Claude Code (`claude -p`, Sonnet 5.5) runs `list_vehicles → quote_rental → start_rental → get_rental`. It books **R-1024-FA0400AA** (veh-01, 2 days, $30 + $100 = $130). The read-back shows order `2AM99761A5518700K` as `PAYER_ACTION_REQUIRED`. |
| `codex-0-write-gated.json` | Codex with no tool approved (`approval_policy=never`). It ran `list_vehicles` and `quote_rental`. Its policy then blocked `start_rental` ("MCP tool call requires approval, but approval policy is never"). `start_rental` is the only tool not annotated read-only. |
| `codex-1-booking.json` | Codex (`codex exec`) after the operator approves that one tool. It runs `quote_rental → start_rental → get_rental` and books **R-1024-B54EE295** (veh-02, 3 days, $45 + $100 = $145), with order `77H944659E772632G`. |
| `renter-approvals.txt` | The human step: the sandbox buyer opens each `approve_url`, approves, and Jaminan's return page answers `/authorize` with HTTP 200. |
| `cc-2-readback.json`, `codex-2-readback.json` | A new session of each client calls `get_rental` and gets back `APPROVED`. PayPal's record shows authorization **8S39497205940830X** (CREATED, USD 130.00) and **4V462197H4984864E** (CREATED, USD 145.00). |
| `paypal-readback.json` | The same two read-backs from the live route. |
| `cancel-link.txt` | Where the renter's key travels: PayPal's cancel link carried it until the 2026-10-25 fix (anyone holding `approve_url` could read it); live after the fix, no key on PayPal's page before or after the renter approves, and the status token no longer opens the evidence pack |
| `live-boundary.txt` | On the live deploy, the agent's `status_token` is sent as the key to the authorize, line-decision, claims, propose, settle, release, vault-delete and fine-contest routes. All 8 return **403 FORBIDDEN**. |

The transcripts are condensed from each client's own JSON event stream. Only the jaminan tool calls, their results
and the final message are kept. The client's start-up event, which lists local paths and tooling, is dropped. The
sandbox buyer's email is replaced with `<sandbox-buyer-email>`. The status tokens are left in on purpose. They are
read-only and open only this status read, not the rental's evidence pack (a token of their own since 2026-10-25;
until then the status token was the evidence link's token), so anyone can repeat the read-back:

```bash
curl -s "https://jaminan.edycu.dev/api/agent/rentals/R-1024-FA0400AA?t=vG8cd6f18tPt"
```

## What an agent cannot do, and why

- **There are no tools for it.** The tool list is exactly `list_vehicles`, `quote_rental`, `start_rental` and
  `get_rental` (`tests/test_mcp.py::test_tools_list_is_exactly_the_four_and_only_start_rental_writes`).
- **There is no key to do it with.** `/api/agent/*` never returns the shop or renter key
  (`Service.agent_book`, `Service.agent_view`). The renter key reaches the renter only through PayPal's return
  redirect, after they log in and approve. PayPal's cancel link carries no key: its login page shows that link to
  anyone holding the approval link (read on the sandbox 2026-10-25), so it may not
  (`test_the_paypal_cancel_link_carries_no_key`; until 2026-10-25 it did carry the key). Every per-rental write route checks its caller's key. Offline, the status
  token is refused on all 18 write routes under `/api/rentals/{id}`, whether sent as a header, as a query parameter or not at all
  (`test_the_status_token_opens_no_write_route`). Live, it is refused on the 8 routes in `live-boundary.txt`.
- **There is no PayPal hold until a human approves.** `start_rental` creates a PayPal order and nothing else. The
  hold exists only after the renter logs in to PayPal and approves.

The two holds were left open so the read-backs stay checkable. They are sandbox authorizations, and PayPal lists
their expiry as 2026-11-22: after that, the same read-back is expected to show PayPal's `EXPIRED`. Status reads are limited to
120 a rental an hour, and PayPal's answer is cached 10 s.

## Reproduce

```bash
.venv/bin/python scripts/mcp_tools_list.py evidence/mcp/tools-list.json          # tools/list over stdio
claude mcp add jaminan -e PYTHONPATH="$PWD" -- "$PWD/.venv/bin/python" -m jaminan.mcp_server   # then ask Claude Code to book
.venv/bin/python scripts/mcp_renter_approves.py '<approve_url>'                  # the renter's approval, sandbox buyer
```
