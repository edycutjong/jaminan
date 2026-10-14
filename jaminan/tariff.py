"""Published tariff versions. A version is the shop's price list plus the fine ceilings and the pinned
IDR→USD rate; its SHA-256 is shown to the renter at approval, so a price can never change after."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DAMAGE_CLASSES = ("missing_part", "broken_part", "crack", "dent", "scuff")


@dataclass(frozen=True)
class TariffVersion:
    id: str
    shop_id: str
    sha256: str
    published_at: str
    status: str
    lines: dict[tuple[str, str], int]          # (part, damage_class) -> price in USD cents
    fine_ceilings: dict[str, tuple[str, int]]   # violation -> (label, max IDR)
    fx_source: str
    idr_per_usd: float
    admin_fee_cents: int

    def price(self, part: str, damage_class: str) -> int | None:
        return self.lines.get((part, damage_class))

    def damage_lines(self) -> list[dict]:
        return [{"part": p, "damage_class": c, "price_cents": v} for (p, c), v in self.lines.items()
                if c in DAMAGE_CLASSES]

    def public(self) -> dict:
        return {"id": self.id, "sha256": self.sha256, "published_at": self.published_at, "status": self.status,
                "lines": self.damage_lines(), "admin_fee_cents": self.admin_fee_cents,
                "fine_ceilings": [{"violation": k, "label": v[0], "max_idr": v[1]} for k, v in self.fine_ceilings.items()],
                "fx_source": self.fx_source, "idr_per_usd": self.idr_per_usd}


def _canonical(tariff_csv: str, ceilings_csv: str, meta: dict) -> bytes:
    return json.dumps({"tariff": tariff_csv.strip(), "fine_ceilings": ceilings_csv.strip(),
                       "fx": [meta["fx_source"], meta["idr_per_usd"]]}, sort_keys=True).encode()


@lru_cache(maxsize=8)
def load(version: str = "tv1") -> TariffVersion:
    n = version.removeprefix("tv")
    meta = json.loads((FIXTURES / f"tariff_v{n}.meta.json").read_text())
    tcsv = (FIXTURES / f"tariff_v{n}.csv").read_text()
    ccsv = (FIXTURES / f"fine_ceiling_v{n}.csv").read_text()
    lines: dict[tuple[str, str], int] = {}
    admin = 0
    for row in csv.DictReader(io.StringIO(tcsv)):
        if row["part"] == "admin_fee":
            admin = int(row["price_cents"])
            continue
        if row["damage_class"] not in DAMAGE_CLASSES:
            raise ValueError(f"unknown damage class {row['damage_class']}")
        lines[(row["part"], row["damage_class"])] = int(row["price_cents"])
    ceilings = {r["violation"]: (r["label"], int(r["max_idr"])) for r in csv.DictReader(io.StringIO(ccsv))}
    return TariffVersion(id=meta["id"], shop_id=meta["shop_id"], sha256=hashlib.sha256(_canonical(tcsv, ccsv, meta)).hexdigest(),
                         published_at=meta["published_at"], status=meta["status"], lines=lines, fine_ceilings=ceilings,
                         fx_source=meta["fx_source"], idr_per_usd=float(meta["idr_per_usd"]), admin_fee_cents=admin)


@lru_cache(maxsize=1)
def shops() -> dict[str, dict]:
    return {r["id"]: r for r in csv.DictReader((FIXTURES / "shop.csv").open())}


@lru_cache(maxsize=1)
def vehicles() -> dict[str, dict]:
    out = {}
    for r in csv.DictReader((FIXTURES / "vehicle.csv").open()):
        r["daily_fee_cents"], r["deposit_cents"] = int(r["daily_fee_cents"]), int(r["deposit_cents"])
        out[r["id"]] = r
    return out
