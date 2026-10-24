"""Store behaviour: MemoryStore semantics (the double must match Redis) and RedisStore's REST transport."""
import json
import time

import httpx
import pytest
import respx

from jaminan import config, store
from jaminan.store import MemoryStore, RedisStore

URL = "https://redis.example"


def test_default_pipe_runs_each_command_in_order():
    m = MemoryStore()
    out = m._pipe([["SET", m.k("a"), "1"], ["GET", m.k("a")]])
    assert out == ["OK", "1"]


def test_set_nx_refuses_a_live_key_and_ex_sets_an_expiry_that_lapses():
    m = MemoryStore()
    assert m.set_json("k", 1, ex=100, nx=True) is True
    assert m.set_json("k", 2, nx=True) is False and m.get_json("k") == 1
    m.exp[m.k("k")] = time.time() - 1
    assert m.get_json("k") is None and m.k("k") not in m.data
    m.set_bytes("b", b"\x00\x01", ex=50)
    assert m.get_bytes("b") == b"\x00\x01" and m.k("b") in m.exp
    assert m.get_bytes("missing") is None
    m.set_bytes("nb", b"z")
    assert m.get_bytes("nb") == b"z" and m.k("nb") not in m.exp


def test_mget_delete_and_incr_with_expiry():
    m = MemoryStore()
    assert m.mget_json([]) == [] and m.delete() == 0
    m.set_json("a", {"x": 1})
    assert m.mget_json(["a", "nope"]) == [{"x": 1}, None]
    assert m.delete("a", "nope") == 1
    assert m.incr("n", ex=30) == 1 and m.k("n") in m.exp
    assert m.incr("n", ex=30, by=4) == 5
    m.exp[m.k("n")] = time.time() - 1
    assert m.incr("n") == 1


def test_sorted_set_list_and_lock_operations():
    m = MemoryStore()
    for score, member in ((3, "c"), (1, "a"), (2, "b")):
        m.zadd("z", score, member)
    assert m.zrange("z") == ["a", "b", "c"] and m.zrange("z", 0, 1) == ["a", "b"]
    assert m.zrange("z", rev=True) == ["c", "b", "a"]
    assert m.zrangebyscore("z", 2, 3) == ["b", "c"]
    m.zrem("z", "a")
    assert m.zrange("z") == ["b", "c"] and m.zrange("empty") == []
    for i in range(5):
        m.rpush_json("l", {"i": i})
    assert [x["i"] for x in m.lrange_json("l")] == [0, 1, 2, 3, 4]
    assert [x["i"] for x in m.lrange_json("l", 1, 2)] == [1, 2] and m.lrange_json("nolist") == []
    m.ltrim("l", -2, -1)
    assert [x["i"] for x in m.lrange_json("l")] == [3, 4]
    m.ltrim("l", 0, 0)
    assert [x["i"] for x in m.lrange_json("l")] == [3]
    m.set_json("lock", "me")
    assert m.delete_if("lock", "other") is False and m.delete_if("lock", "me") is True
    assert m.delete_if("lock", "me") is False


def test_keys_pattern_and_unsupported_commands():
    m = MemoryStore()
    m.set_json("rental:1", 1)
    m.set_json("frame:1", 1)
    assert m._cmd("KEYS", m.k("rental:*")) == [m.k("rental:1")]
    assert m._cmd("EXPIRE", m.k("rental:1"), 10) == 1
    with pytest.raises(NotImplementedError):
        m._cmd("FLUSHALL")


def test_from_settings_picks_redis_only_when_both_credentials_exist():
    mem = store.from_settings(config.Settings(redis_url="", redis_token="", key_prefix="jaminan:t:"))
    assert isinstance(mem, MemoryStore) and mem.prefix == "jaminan:t:"
    red = store.from_settings(config.Settings(redis_url=URL, redis_token="t", key_prefix="jaminan:"))
    assert isinstance(red, RedisStore)


def test_redis_refuses_a_prefix_outside_the_shared_namespace():
    with pytest.raises(ValueError, match="jaminan:"):
        RedisStore(URL, "t", prefix="other:")


@respx.mock
def test_redis_commands_post_stringified_args_and_unwrap_the_result():
    route = respx.post(URL).mock(return_value=httpx.Response(200, json={"result": "OK"}))
    r = RedisStore(URL + "/", "tok")
    assert r.set_json("k", {"a": 1}, ex=5) is True
    sent = json.loads(route.calls[0].request.content)
    assert sent[:2] == ["SET", "jaminan:k"] and sent[3:] == ["EX", "5"]
    assert route.calls[0].request.headers["Authorization"] == "Bearer tok"


@respx.mock
def test_redis_error_bodies_and_http_errors_raise():
    r = RedisStore(URL, "tok")
    respx.post(URL).mock(return_value=httpx.Response(200, json={"error": "WRONGTYPE"}))
    with pytest.raises(RuntimeError, match="WRONGTYPE"):
        r.get_json("k")
    respx.post(URL).mock(return_value=httpx.Response(500, json={}))
    with pytest.raises(httpx.HTTPStatusError):
        r.get_json("k")


@respx.mock
def test_redis_pipeline_and_chunked_mget():
    r = RedisStore(URL, "tok")
    pipe = respx.post(f"{URL}/pipeline").mock(return_value=httpx.Response(200, json=[{"result": 1}, {"result": 2}]))
    assert r._pipe([["INCR", "a"], ["INCR", "b"]]) == [1, 2]
    assert json.loads(pipe.calls[0].request.content) == [["INCR", "a"], ["INCR", "b"]]
    respx.post(f"{URL}/pipeline").mock(return_value=httpx.Response(500, json={}))
    with pytest.raises(httpx.HTTPStatusError):
        r._pipe([["GET", "a"]])

    def answer(request):
        n = len(json.loads(request.content)) - 1  # MGET key...
        return httpx.Response(200, json={"result": [json.dumps(i) for i in range(n)]})

    mget = respx.post(URL).mock(side_effect=answer)
    out = r.mget_json([f"k{i}" for i in range(250)])
    assert mget.call_count == 3 and len(out) == 250
