from pathlib import Path
from typing import Any

import pytest
from web3 import HTTPProvider

from lapeg.chain.rpc_cache import CachingHTTPProvider, RpcCache, is_cacheable


@pytest.mark.parametrize("method,params,expected", [
    ("eth_call", [{"to": "0x0"}, "0x10"], True),
    ("eth_call", [{"to": "0x0"}, 16], True),
    ("eth_call", [{"to": "0x0"}, "latest"], False),
    ("eth_call", [{"to": "0x0"}, {"blockHash": "0xab"}], True),
    ("eth_getStorageAt", ["0x0", "0x1", "0x10"], True),
    ("eth_getStorageAt", ["0x0", "0x1", "pending"], False),
    ("eth_getBlockByNumber", ["0x10", False], True),
    ("eth_getBlockByNumber", ["latest", False], False),
    ("eth_getLogs", [{"fromBlock": "0x1", "toBlock": "0x2"}], True),
    ("eth_getLogs", [{"fromBlock": "0x1", "toBlock": "latest"}], False),
    ("eth_getTransactionReceipt", ["0xab"], True),
    ("eth_blockNumber", [], False),
    ("eth_sendTransaction", [{}], False),
])
def test_is_cacheable(method: str, params: Any, expected: bool) -> None:
    assert is_cacheable(method, params) is expected


def test_provider_serves_repeat_reads_from_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_upstream(self: Any, method: str, params: Any) -> dict[str, Any]:
        calls.append(method)
        return {"jsonrpc": "2.0", "id": 1, "result": f"{method}-{len(calls)}"}

    monkeypatch.setattr(HTTPProvider, "make_request", fake_upstream)
    cache = RpcCache(tmp_path / "c.sqlite")
    p = CachingHTTPProvider("http://unused", cache)

    pinned = [{"to": "0x0", "data": "0x"}, "0x10"]
    first = p.make_request("eth_call", pinned)
    second = p.make_request("eth_call", pinned)
    assert first["result"] == second["result"] == "eth_call-1"
    assert calls == ["eth_call"] and (cache.hits, cache.misses) == (1, 1)

    p.make_request("eth_call", [{"to": "0x0", "data": "0x"}, "latest"])
    p.make_request("eth_call", [{"to": "0x0", "data": "0x"}, "latest"])
    assert calls.count("eth_call") == 3          # 'latest' is never cached

    # survives reopening the database
    cache.close()
    p2 = CachingHTTPProvider("http://unused", RpcCache(tmp_path / "c.sqlite"))
    assert p2.make_request("eth_call", pinned)["result"] == "eth_call-1"


def test_errors_and_nulls_are_not_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter([{"error": {"code": -1}}, {"result": None}, {"result": "0x1"}])
    monkeypatch.setattr(HTTPProvider, "make_request", lambda self, m, p: next(responses))
    p = CachingHTTPProvider("http://unused", RpcCache(tmp_path / "c.sqlite"))
    args = ["0xab"]
    assert "error" in p.make_request("eth_getTransactionReceipt", args)
    assert p.make_request("eth_getTransactionReceipt", args)["result"] is None
    assert p.make_request("eth_getTransactionReceipt", args)["result"] == "0x1"
