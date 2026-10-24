"""Persistence: Upstash Redis over its REST API. Every key carries the `jaminan:` prefix (the database
is shared — nothing outside the prefix is ever read or written). MemoryStore is the unit-test double."""
from __future__ import annotations

import base64
import fnmatch
import json
import time
from typing import Any, Iterable

import httpx


class Store:
    prefix: str

    # primitive ops implemented by subclasses
    def _cmd(self, *args: Any) -> Any:  # pragma: no cover - interface
        raise NotImplementedError

    def _pipe(self, cmds: list[list[Any]]) -> list[Any]:
        return [self._cmd(*c) for c in cmds]

    def k(self, key: str) -> str:
        return key if key.startswith(self.prefix) else self.prefix + key

    # JSON documents ------------------------------------------------------------------------
    def get_json(self, key: str) -> Any:
        raw = self._cmd("GET", self.k(key))
        return json.loads(raw) if raw else None

    def set_json(self, key: str, value: Any, ex: int | None = None, nx: bool = False) -> bool:
        args: list[Any] = ["SET", self.k(key), json.dumps(value, separators=(",", ":"))]
        if ex:
            args += ["EX", int(ex)]
        if nx:
            args.append("NX")
        return self._cmd(*args) == "OK"

    def mget_json(self, keys: Iterable[str]) -> list[Any]:
        keys = [self.k(x) for x in keys]
        if not keys:
            return []
        return [json.loads(r) if r else None for r in self._cmd("MGET", *keys)]

    def delete(self, *keys: str) -> int:
        return int(self._cmd("DEL", *[self.k(x) for x in keys]) or 0) if keys else 0

    # binary blobs (frames) -----------------------------------------------------------------
    def set_bytes(self, key: str, data: bytes, ex: int | None = None) -> None:
        args: list[Any] = ["SET", self.k(key), base64.b64encode(data).decode()]
        if ex:
            args += ["EX", int(ex)]
        self._cmd(*args)

    def get_bytes(self, key: str) -> bytes | None:
        raw = self._cmd("GET", self.k(key))
        return base64.b64decode(raw) if raw else None

    # indexes -------------------------------------------------------------------------------
    def zadd(self, key: str, score: float, member: str) -> None:
        self._cmd("ZADD", self.k(key), score, member)

    def zrange(self, key: str, start: int = 0, stop: int = -1, rev: bool = False) -> list[str]:
        args: list[Any] = ["ZRANGE", self.k(key), start, stop]
        if rev:
            args.append("REV")
        return list(self._cmd(*args) or [])

    def zrangebyscore(self, key: str, lo: float, hi: float) -> list[str]:
        return list(self._cmd("ZRANGEBYSCORE", self.k(key), lo, hi) or [])

    def zrem(self, key: str, member: str) -> None:
        self._cmd("ZREM", self.k(key), member)

    def rpush_json(self, key: str, value: Any) -> int:
        return int(self._cmd("RPUSH", self.k(key), json.dumps(value, separators=(",", ":"))))

    def lrange_json(self, key: str, start: int = 0, stop: int = -1) -> list[Any]:
        return [json.loads(x) for x in (self._cmd("LRANGE", self.k(key), start, stop) or [])]

    def delete_if(self, key: str, value: Any) -> bool:
        """Delete key only if it still holds `value` (atomic on Redis via EVAL) — a lock owner never
        releases a lock that expired and was taken by another request."""
        raw = json.dumps(value, separators=(",", ":"))
        script = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
        return int(self._cmd("EVAL", script, 1, self.k(key), raw) or 0) == 1

    def ltrim(self, key: str, start: int, stop: int) -> None:
        self._cmd("LTRIM", self.k(key), start, stop)

    def incr(self, key: str, ex: int | None = None, by: int = 1) -> int:
        n = int(self._cmd("INCRBY", self.k(key), int(by)))
        if ex and n == by:
            self._cmd("EXPIRE", self.k(key), int(ex))
        return n


class RedisStore(Store):
    def __init__(self, url: str, token: str, prefix: str = "jaminan:") -> None:
        if not prefix.startswith("jaminan:"):
            raise ValueError("every key must live under the jaminan: prefix (shared database)")
        self.url, self.prefix = url.rstrip("/"), prefix
        self.http = httpx.Client(headers={"Authorization": f"Bearer {token}"}, timeout=15)

    def _cmd(self, *args: Any) -> Any:
        r = self.http.post(self.url, json=[str(a) if not isinstance(a, str) else a for a in args])
        r.raise_for_status()
        body = r.json()
        if "error" in body:
            raise RuntimeError(f"redis: {body['error']}")
        return body.get("result")

    def _pipe(self, cmds: list[list[Any]]) -> list[Any]:
        r = self.http.post(f"{self.url}/pipeline", json=[[str(a) for a in c] for c in cmds])
        r.raise_for_status()
        return [x.get("result") for x in r.json()]

    def mget_json(self, keys: Iterable[str]) -> list[Any]:
        keys = list(keys)
        out: list[Any] = []
        for i in range(0, len(keys), 100):
            out += super().mget_json(keys[i:i + 100])
        return out


class MemoryStore(Store):
    """In-process double with the same semantics as the subset of Redis used here."""

    def __init__(self, prefix: str = "jaminan:test:") -> None:
        self.prefix = prefix
        self.data: dict[str, Any] = {}
        self.exp: dict[str, float] = {}

    def _alive(self, key: str) -> bool:
        if key in self.exp and self.exp[key] < time.time():
            self.data.pop(key, None)
            self.exp.pop(key, None)
        return key in self.data

    def _cmd(self, *args: Any) -> Any:
        op, rest = args[0].upper(), list(args[1:])
        if op == "GET":
            return self.data.get(rest[0]) if self._alive(rest[0]) else None
        if op == "MGET":
            return [self.data.get(x) if self._alive(x) else None for x in rest]
        if op == "SET":
            key, val, opts = rest[0], rest[1], [str(o).upper() for o in rest[2:]]
            if "NX" in opts and self._alive(key):
                return None
            self.data[key] = val
            self.exp.pop(key, None)
            if "EX" in opts:
                self.exp[key] = time.time() + int(rest[2 + opts.index("EX") + 1])
            return "OK"
        if op == "DEL":
            n = sum(1 for x in rest if self._alive(x))
            for x in rest:
                self.data.pop(x, None)
            return n
        if op == "EXPIRE":
            self.exp[rest[0]] = time.time() + int(rest[1])
            return 1
        if op in ("INCR", "INCRBY"):
            v = int(self.data.get(rest[0], 0) if self._alive(rest[0]) else 0) + (int(rest[1]) if op == "INCRBY" else 1)
            self.data[rest[0]] = str(v)
            return v
        if op == "ZADD":
            z = self.data.setdefault(rest[0], {})
            z[rest[2]] = float(rest[1])
            return 1
        if op == "ZREM":
            self.data.get(rest[0], {}).pop(rest[1], None)
            return 1
        if op in ("ZRANGE", "ZRANGEBYSCORE"):
            z = self.data.get(rest[0], {})
            items = sorted(z.items(), key=lambda kv: (kv[1], kv[0]))
            if op == "ZRANGEBYSCORE":
                return [m for m, s in items if float(rest[1]) <= s <= float(rest[2])]
            if len(rest) > 3 and str(rest[3]).upper() == "REV":
                items = items[::-1]
            members = [m for m, _ in items]
            start, stop = int(rest[1]), int(rest[2])
            return members[start:] if stop == -1 else members[start:stop + 1]
        if op == "RPUSH":
            lst = self.data.setdefault(rest[0], [])
            lst.extend(rest[1:])
            return len(lst)
        if op == "LRANGE":
            lst = self.data.get(rest[0], [])
            start, stop = int(rest[1]), int(rest[2])
            return lst[start:] if stop == -1 else lst[start:stop + 1]
        if op == "EVAL":  # only the compare-and-delete script used by delete_if
            key, val = rest[2], rest[3]
            if self._alive(key) and self.data[key] == val:
                del self.data[key]
                return 1
            return 0
        if op == "LTRIM":
            lst = self.data.get(rest[0], [])
            start, stop = int(rest[1]), int(rest[2])
            n = len(lst)
            start = start + n if start < 0 else start
            stop = stop + n if stop < 0 else stop
            self.data[rest[0]] = lst[max(start, 0):stop + 1]
            return "OK"
        if op == "KEYS":
            return [x for x in self.data if fnmatch.fnmatch(x, rest[0])]
        raise NotImplementedError(op)


def from_settings(s) -> Store:
    if s.redis_url and s.redis_token:
        return RedisStore(s.redis_url, s.redis_token, s.key_prefix)
    return MemoryStore(prefix=s.key_prefix)
