"""Mint saved sandbox wallets for the /judge pool: each is one real sandbox-buyer approval of an AUTHORIZE
order with vault consent (the S1 flow), after which the hold is voided and only the vault token is kept.

Usage: python scripts/mint_judge_pool.py 1 [buyer_email buyer_password]   → prints the vault id
PayPal returns the same vault token for the same buyer + merchant, so each pool token needs its own
sandbox personal account (developer dashboard → Sandbox accounts).
Sandbox only. Never commit the output to the repo; it goes into a Vercel env var."""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jaminan.config import Settings, load_local_env  # noqa: E402
from jaminan.paypal import PayPal, first_authorization, vault_of  # noqa: E402
from scripts.sandbox_buyer import approve  # noqa: E402


def mint(pp: PayPal, label: str, email: str | None = None, password: str | None = None) -> dict:
    ref = f"POOL-{label}-{uuid.uuid4().hex[:6]}"
    o = pp.create_authorize_order(ref, 100, "Jaminan judge wallet: vault consent", "https://example.com/return",
                                  "https://example.com/cancel", nonce=uuid.uuid4().hex)
    link = next(l["href"] for l in o.body["links"] if l["rel"] in ("payer-action", "approve"))
    approve(link, email, password)
    a = pp.authorize_order(o.body["id"])
    auth, v = first_authorization(a.body), vault_of(a.body)
    if auth:
        pp.void(auth["id"])
    return {"vault_id": v.get("id"), "status": v.get("status"), "customer": (v.get("customer") or {}).get("id"),
            "order": o.body["id"], "authorize_debug": a.debug_id}


if __name__ == "__main__":
    load_local_env()
    s = Settings()
    pp = PayPal(s.paypal_base, s.paypal_client_id, s.paypal_client_secret)
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    creds = sys.argv[2:4] if len(sys.argv) >= 4 else [None, None]
    out = [mint(pp, str(i), *creds) for i in range(n)]
    print(json.dumps(out, indent=1))
