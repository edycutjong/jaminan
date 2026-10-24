"""Booking agents: the MCP server's four tools, the /api/agent/* routes under them, and the permission boundary —
an agent can look, price and ask; it cannot approve, accept or contest a line, capture, void or refund."""
import json
import runpy

import anyio
import httpx
import pytest
import respx
from fastapi.testclient import TestClient

import api.index as api_index
from jaminan import mcp_server as m
from jaminan.paypal import Resp
from jaminan.service import now
from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from tests.fakes import frame_bytes
from tests.test_cov_service_a import code
from tests.test_service_flow import make

API = m.API
TOOLS = {"list_vehicles", "quote_rental", "start_rental", "get_rental"}
# every request the tools may send: three reads and the one booking write
ALLOWED = {("GET", "/api/shops/"), ("GET", "/api/agent/quote"), ("POST", "/api/agent/rentals"),
           ("GET", "/api/agent/rentals/")}


@pytest.fixture
def api_client():
    """The real FastAPI app on fakes, behind respx: the MCP tools talk to it exactly as they talk to the deploy."""
    svc = make()
    api_index._svc = svc
    tc = TestClient(api_index.app, raise_server_exceptions=False)
    sent: list[httpx.Request] = []

    def forward(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        r = tc.request(request.method, request.url.raw_path.decode(), content=request.content,
                       headers={"content-type": request.headers.get("content-type", "application/json")})
        return httpx.Response(r.status_code, content=r.content, headers={"content-type": r.headers["content-type"]})

    with respx.mock(assert_all_called=False) as mock:
        mock.route(url__startswith=API).mock(side_effect=forward)
        yield svc, tc, sent
    api_index._svc = None
    m._tokens.clear()


def _tools(server=m.mcp):
    async def go():
        async with Client(server) as c:
            return await c.list_tools()
    return anyio.run(go).tools


def test_tools_list_is_exactly_the_four_and_only_start_rental_writes():
    tools = {t.name: t for t in _tools()}
    assert set(tools) == TOOLS
    for name in ("list_vehicles", "quote_rental", "get_rental"):
        assert tools[name].annotations.read_only_hint is True
    assert tools["start_rental"].annotations.read_only_hint is False
    assert tools["start_rental"].annotations.destructive_hint is False


def test_a_tool_that_is_not_there_cannot_be_called(api_client):
    async def go(name):
        async with Client(m.mcp) as c:
            return await c.call_tool(name, {"rental_id": "R-1"})
    for name in ("capture", "approve", "accept_line", "settle", "void", "refund", "release"):
        assert anyio.run(go, name).is_error, name


def test_list_and_quote_read_the_same_tariff_the_counter_uses(api_client):
    svc, _, _ = api_client
    v = m.list_vehicles("shop-demo")
    assert {x["id"] for x in v["vehicles"]} >= {"veh-01", "veh-02"} and v["tariff"]["id"] == "tv1"
    q = m.quote_rental("veh-01", 3)
    r = svc.create_rental("shop-demo", "veh-01", 3)
    assert (q["fee_cents"], q["deposit_cents"], q["authorized_cents"]) == \
        (r["fee_cents"], r["deposit_cents"], r["authorized_cents"]) == (4500, 10000, 14500)
    assert q["tariff_sha256"] == r["tariff_sha256"] == v["tariff"]["sha256"]


def test_book_then_read_back_the_order_then_the_hold(api_client):
    svc, _, sent = api_client
    b = m.start_rental("veh-02", 2, "  renter@example.com ")
    assert b["state"] == "DRAFT" and b["approve_url"].startswith("https://www.sandbox.paypal.com/")
    assert b["booked_by"] == "agent" and b["authorized_cents"] == 13000
    first = m.get_rental(b["rental_id"])  # this session's token
    assert first["paypal"]["object"] == "order" and first["paypal"]["id"] == b["order_id"]
    svc.authorize(b["rental_id"])  # what the renter's PayPal return page does after THEY approve
    m._tokens.clear()
    after = m.get_rental(b["rental_id"], b["status_token"])  # a new session passes the token
    assert after["state"] == "APPROVED" and after["paypal"]["object"] == "authorization"
    assert after["paypal"]["status"] == "CREATED" and after["paypal"]["id"] == after["authorization_id"]
    assert svc.get(b["rental_id"])["renter_email"] == "renter@example.com"
    # the boundary on the wire: only the four allowed requests, never a key
    for req in sent:
        assert any(req.method == meth and req.url.path.startswith(p) for meth, p in ALLOWED), req.url
        assert "x-jaminan-key" not in req.headers and "k" not in req.url.params


def test_the_agent_never_receives_a_key(api_client):
    svc, tc, _ = api_client
    b = m.start_rental("veh-01", 1, "renter@example.com")
    keys = svc.get(b["rental_id"])["keys"]
    seen = json.dumps([b, m.get_rental(b["rental_id"]), m.quote_rental("veh-01", 1), m.list_vehicles()])
    assert keys["shop"] not in seen and keys["renter"] not in seen
    assert "shop_key" not in seen and "renter_link" not in seen and "renter_key" not in seen


def test_the_status_token_opens_no_write_route(api_client):
    """Each write path checks its caller: the only capability an agent holds is refused by every one of them."""
    svc, tc, _ = api_client
    b = m.start_rental("veh-01", 1, "renter@example.com")
    rid, t = b["rental_id"], b["status_token"]
    svc.authorize(rid)
    before = svc.get(rid)["state"]
    h = {"X-Jaminan-Key": t}
    writes = [("post", f"/api/rentals/{rid}/approve", {}), ("post", f"/api/rentals/{rid}/authorize", {}),
              ("post", f"/api/rentals/{rid}/baseline/premark", {}), ("post", f"/api/rentals/{rid}/baseline/confirm", {}),
              ("post", f"/api/rentals/{rid}/baseline/retake", {"json": {"angle": 1}}),
              ("post", f"/api/rentals/{rid}/return/complete", {}), ("post", f"/api/rentals/{rid}/return/suggest", {}),
              ("post", f"/api/rentals/{rid}/claims", {"json": {"angle": 1, "bbox": [0.1, 0.1, 0.1, 0.1],
                                                               "part": "panel_left", "damage_class": "scratch"}}),
              ("post", f"/api/rentals/{rid}/propose", {}),
              ("post", f"/api/rentals/{rid}/baseline/marks", {"json": {"action": "add", "mark": {"angle": 1}}}),
              ("post", f"/api/rentals/{rid}/suggestions/S1/dismiss", {}),
              ("post", f"/api/rentals/{rid}/lines/L1/decision", {"json": {"decision": "accepted"}}),
              ("post", f"/api/rentals/{rid}/lines/L1/decision", {"json": {"decision": "contested"}}),
              ("post", f"/api/rentals/{rid}/settle", {}), ("post", f"/api/rentals/{rid}/release", {}),
              ("post", f"/api/rentals/{rid}/fines/F1/contest", {}), ("delete", f"/api/rentals/{rid}/vault", {}),
              ("post", f"/api/rentals/{rid}/photos", {"data": {"phase": "pickup", "angle": "1"},
                                                      "files": {"file": ("f.jpg", frame_bytes(1))}}),
              ("post", f"/api/rentals/{rid}/fines", {"data": {"ticket_amount_idr": "250000"},
                                                     "files": {"file": ("t.jpg", frame_bytes(2))}})]
    for meth, path, kw in writes:
        for creds in ({"headers": h}, {"params": {"k": t}}, {}):
            r = getattr(tc, meth)(path, **creds, **kw)
            assert r.status_code == 403 and r.json()["error"] == "FORBIDDEN", (path, creds, r.status_code, r.text)
    assert tc.get(f"/api/rentals/{rid}", headers=h).status_code == 403  # nor the parties' full view
    assert tc.get(f"/api/rentals/{rid}/evidence", params={"t": t}).status_code == 403  # nor the evidence pack
    assert svc.get(rid)["state"] == before == "APPROVED"


def test_input_errors_are_plain_tool_errors(api_client):
    svc, _, _ = api_client
    cases = [(m.quote_rental, ("veh-01", 0)), (m.quote_rental, ("veh-01", 29)), (m.quote_rental, ("veh-01", True)),
             (m.quote_rental, ("veh-01", 2.5)), (m.quote_rental, ("../admin", 1)), (m.list_vehicles, ("shop/x",)),
             (m.start_rental, ("veh-01", 1, "not-an-email")), (m.start_rental, ("veh-01", 1, None)),
             (m.get_rental, ("R-0000-NOPE",)), (m.get_rental, (123,))]
    for fn, args in cases:
        with pytest.raises(ToolError):
            fn(*args)
    with pytest.raises(ToolError, match="UNKNOWN_VEHICLE"):
        m.quote_rental("veh-99", 1)
    with pytest.raises(ToolError, match="NO_SHOP"):
        m.list_vehicles("shop-nope")
    with pytest.raises(ToolError, match="BAD_EMAIL"):
        m.start_rental("veh-01", 1, "a@b")  # past the tool's check, refused by the service
    with pytest.raises(ToolError, match="RENTAL_NOT_FOUND"):
        m.get_rental("R-0000-NOPE", "tok")
    b = m.start_rental("veh-01", 1, "renter@example.com")
    with pytest.raises(ToolError, match="FORBIDDEN"):
        m.get_rental(b["rental_id"], "wrong-token")


@pytest.mark.parametrize("resp,want", [
    (httpx.Response(502, text="Bad gateway"), "502: the Jaminan API refused this"),
    (httpx.Response(200, json=["not", "a", "dict"]), "200: the Jaminan API refused this"),
    (httpx.Response(500, json={"detail": "x"}), "500: the Jaminan API refused this"),
])
def test_a_broken_or_odd_api_answer_is_a_one_line_error(resp, want):
    with respx.mock() as mock:
        mock.get(f"{API}/api/shops/shop-demo").mock(return_value=resp)
        with pytest.raises(ToolError) as e:
            m.list_vehicles()
    assert str(e.value) == want


def test_an_unreachable_api_is_a_one_line_error():
    with respx.mock() as mock:
        mock.get(f"{API}/api/agent/quote").mock(side_effect=httpx.ConnectError("boom"))
        with pytest.raises(ToolError, match="did not answer"):
            m.quote_rental("veh-01", 1)


@pytest.mark.filterwarnings("ignore::RuntimeWarning")  # runpy re-runs an imported module, on purpose
def test_main_runs_stdio(monkeypatch):
    calls = []
    monkeypatch.setattr(MCPServer, "run", lambda self, transport: calls.append((self.name, transport)))
    m.main()
    runpy.run_module("jaminan.mcp_server", run_name="__main__")
    assert calls == [("jaminan", "stdio")] * 2


# --- the service and routes under the tools -------------------------------------------------------------------
def test_agent_booking_prefills_paypal_with_the_renter_email_only_for_agents():
    svc = make()
    bodies = []
    orig = svc.pp._send
    svc.pp._send = lambda meth, path, content, headers, params: (
        bodies.append(json.loads(content) if content else {}), orig(meth, path, content, headers, params))[1]
    svc.agent_book("1.2.3.4", "veh-01", 1, "renter@example.com")
    svc.approve(svc.create_rental("shop-demo", "veh-01", 1)["id"])
    orders = [b for b in bodies if b.get("intent") == "AUTHORIZE"]
    assert orders[0]["payment_source"]["paypal"]["email_address"] == "renter@example.com"
    assert "email_address" not in orders[1]["payment_source"]["paypal"]


def test_the_paypal_cancel_link_carries_no_key():
    """PayPal's login page shows the cancel link to anyone holding approve_url (read on the sandbox 2026-10-25), so an
    agent could open the link it was given and read the renter's key off it. Only the return URL, which PayPal sends
    the renter to after they log in and approve, may carry the key."""
    svc = make()
    bodies = []
    orig = svc.pp._send
    svc.pp._send = lambda meth, path, content, headers, params: (
        bodies.append(json.loads(content) if content else {}), orig(meth, path, content, headers, params))[1]
    rids = [svc.agent_book("1.2.3.4", "veh-01", 1, "renter@example.com")["rental_id"]]
    rids.append(svc.create_rental("shop-demo", "veh-01", 1)["id"])
    svc.approve(rids[1])
    orders = [b["payment_source"]["paypal"]["experience_context"] for b in bodies if b.get("intent") == "AUTHORIZE"]
    for rid, ctx in zip(rids, orders, strict=True):
        key = svc.get(rid)["keys"]["renter"]
        assert key not in ctx["cancel_url"] and "k=" not in ctx["cancel_url"]
        assert ctx["return_url"].endswith(f"/r/{rid}/approved?k={key}")


def test_bad_input_spends_no_budget_and_the_13th_booking_an_hour_is_refused():
    svc = make()
    # the two addresses PayPal's sandbox refused with 400 INVALID_PARAMETER_SYNTAX (2026-10-25), and a 65-char local part
    emails = ["nope", "a,b@example.com", "a..b@example.com", ".a@example.com", "a@-x.com", "a" * 65 + "@example.com"]
    for bad in [("veh-99", 1, "a@example.com"), ("veh-01", 0, "a@example.com")] + [("veh-01", 1, e) for e in emails]:
        code(svc.agent_book, "9.9.9.9", *bad)
    assert all(code(svc.agent_book, "9.9.9.9", "veh-01", 1, e) == "BAD_EMAIL" for e in emails)
    assert svc.db.zrangebyscore("shop:shop-demo:rentals", 0, 1e12) == []  # no rental was created for any of them
    assert svc.agent_book("8.8.8.8", "veh-01", 1, "first.last+jaminan@mail.example.co.id")["state"] == "DRAFT"
    for i in range(12):
        svc.agent_book("9.9.9.9", "veh-01", 1, f"a{i}@example.com")
    assert code(svc.agent_book, "9.9.9.9", "veh-01", 1, "a@example.com") == "RATE_LIMITED"
    assert code(svc.agent_book, "9.9.9.9", "veh-01", 1, "") == "BAD_EMAIL"


def test_a_retried_booking_gets_the_first_one_back_and_spends_nothing(monkeypatch):
    """start_rental's client may give up at 60 s while the server finishes; "try again" must not book twice."""
    svc = make()
    orders = []
    orig = svc.pp.create_authorize_order
    monkeypatch.setattr(svc.pp, "create_authorize_order", lambda *a, **k: (orders.append(a[0]), orig(*a, **k))[1])
    a = svc.agent_book("9.9.9.9", "veh-01", 1, "Renter@example.com")
    b = svc.agent_book("9.9.9.9", "veh-01", 1, "renter@example.com")
    assert (b["rental_id"], b["approve_url"], b["status_token"]) == (a["rental_id"], a["approve_url"], a["status_token"])
    assert orders == [a["rental_id"]] and len(svc.shop_rentals("shop-demo")) == 1
    assert svc.agent_book("9.9.9.9", "veh-01", 2, "renter@example.com")["rental_id"] != a["rental_id"]  # another booking
    # the first PayPal call failed: the retry finishes the same rental, on the budget it already spent
    monkeypatch.setattr(svc.pp, "create_authorize_order", lambda *a, **k: Resp(503, {"name": "SERVICE_UNAVAILABLE"}, "d", "x"))
    assert code(svc.agent_book, "9.9.9.9", "veh-02", 1, "renter@example.com") == "PAYPAL_ORDER_FAILED"
    monkeypatch.setattr(svc.pp, "create_authorize_order", orig)
    c = svc.agent_book("9.9.9.9", "veh-02", 1, "renter@example.com")
    assert c["approve_url"] and c["state"] == "DRAFT" and len(svc.shop_rentals("shop-demo")) == 3
    assert svc.db.incr(f"rl:agent:all:{now():%Y%m%d}", by=0) == 3  # three bookings counted, not five calls
    # two identical requests at once: the one that loses the reservation is told to call again
    monkeypatch.setattr(svc.db, "set_json", lambda *a, **k: False if a[0].startswith("agent:booking:") else True)
    assert code(svc.agent_book, "9.9.9.9", "veh-01", 3, "renter@example.com") == "BOOKING_IN_PROGRESS"


def test_status_reads_paypal_without_changing_anything_and_has_a_budget(monkeypatch):
    svc = make()
    r = svc.create_rental("shop-demo", "veh-01", 1, kind="agent")
    t = r["agent_token"] = "agent-status-token"
    svc.db.set_json(f"rental:{r['id']}", r)
    assert code(svc.agent_status, r["id"], None) == "FORBIDDEN"
    assert code(svc.agent_status, r["id"], r["evidence_token"]) == "FORBIDDEN"  # the evidence link's token is not it
    counter = svc.create_rental("shop-demo", "veh-01", 1)  # booked at the counter: no agent token to read it with
    assert code(svc.agent_status, counter["id"], counter["evidence_token"]) == "FORBIDDEN"
    assert svc.agent_status(r["id"], t)["paypal"] is None  # no order yet: nothing to read back
    svc.approve(r["id"])
    before, ledger = svc.get(r["id"]), len(svc.calls(r["id"]))
    assert svc.agent_status(r["id"], t)["paypal"]["status"] == "APPROVED"
    assert len(svc.calls(r["id"])) == ledger  # a polling agent never grows the rental's PayPal ledger
    monkeypatch.setattr(svc.pp, "get_order", lambda *a, **k: Resp(503, {"name": "SERVICE_UNAVAILABLE"}, "d", "x"))
    assert svc.agent_status(r["id"], t)["paypal"]["status"] == "APPROVED"  # PayPal's answer is cached 10 s
    svc.db.delete(f"agentread:{svc.get(r['id'])['order_id']}")  # ...then asked again
    down = svc.agent_status(r["id"], t)["paypal"]
    assert down["object"] == "order" and down["status"] is None and down["error"] == "SERVICE_UNAVAILABLE"
    assert svc.get(r["id"]) == before and before["state"] == "DRAFT"  # reads write nothing to the rental
    hour = now().strftime("%Y%m%d%H")
    svc.db.incr(f"budget:{r['id']}:status:{hour}", by=120)
    assert code(svc.agent_status, r["id"], t) == "BUDGET"
    svc.db.delete(f"budget:{r['id']}:status:{hour}")  # the allowance is per hour, not for the rental's life
    assert svc.agent_status(r["id"], t)["paypal"]["object"] == "order"


def test_quote_routes_validate_like_the_counter():
    svc = make()
    api_index._svc = svc
    try:
        c = TestClient(api_index.app, raise_server_exceptions=False)
        assert c.get("/api/agent/quote", params={"vehicle_id": "veh-01", "days": 2}).json()["fee_cents"] == 3000
        assert c.get("/api/agent/quote", params={"vehicle_id": "veh-01", "days": 29}).json()["error"] == "BAD_DAYS"
        assert c.get("/api/agent/quote", params={"vehicle_id": "veh-01", "days": "x"}).json()["error"] == "BAD_REQUEST"
        assert c.post("/api/agent/rentals", json={"vehicle_id": "veh-01"}).json()["error"] == "BAD_REQUEST"
        assert c.get("/api/agent/rentals/R-0000-NOPE").status_code == 404
    finally:
        api_index._svc = None
