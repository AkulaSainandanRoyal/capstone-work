"""Local cache for upstream RPC reads, so reruns do not hammer the node.

Only responses that cannot change are cached: reads pinned to a block number or hash, and lookups of
mined transactions and receipts. Anything addressed to 'latest' or 'pending' always goes to the node.

Use this against the upstream (archive) RPC only, never against an anvil fork, whose state changes.
Anvil keeps its own on-disk cache of forked state under ~/.foundry/cache.

Assumption: callers pin finalized blocks. A cached read of a block that is later reorged would be stale.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from web3 import HTTPProvider

BLOCK_TAGS = {"latest", "pending", "earliest", "safe", "finalized"}
ALWAYS_CACHEABLE = {
    "eth_chainId", "eth_getBlockByHash", "eth_getTransactionByHash", "eth_getTransactionReceipt",
}
BLOCK_ARG_INDEX = {  # method -> position of its block argument
    "eth_call": 1,
    "eth_getBalance": 1,
    "eth_getCode": 1,
    "eth_getTransactionCount": 1,
    "eth_getStorageAt": 2,
    "eth_getBlockByNumber": 0,
}


def _pinned(block: Any) -> bool:
    if isinstance(block, int):
        return True
    if isinstance(block, str):
        return block not in BLOCK_TAGS
    if isinstance(block, dict):          # EIP-1898 {"blockHash": ...} or {"blockNumber": ...}
        return "blockHash" in block or _pinned(block.get("blockNumber"))
    return False


def is_cacheable(method: str, params: Any) -> bool:
    params = list(params or [])
    if method in ALWAYS_CACHEABLE:
        return True
    if method in BLOCK_ARG_INDEX:
        i = BLOCK_ARG_INDEX[method]
        return len(params) > i and _pinned(params[i])
    if method == "eth_getLogs" and params and isinstance(params[0], dict):
        f = params[0]
        return "blockHash" in f or (_pinned(f.get("fromBlock")) and _pinned(f.get("toBlock")))
    return False


def cache_key(namespace: str, method: str, params: Any) -> str:
    blob = json.dumps([namespace, method, params], sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


class RpcCache:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("CREATE TABLE IF NOT EXISTS rpc (key TEXT PRIMARY KEY, method TEXT, result TEXT)")
        self._db.commit()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Any | None:
        with self._lock:
            row = self._db.execute("SELECT result FROM rpc WHERE key = ?", (key,)).fetchone()
        return None if row is None else json.loads(row[0])

    def put(self, key: str, method: str, result: Any) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO rpc VALUES (?, ?, ?)", (key, method, json.dumps(result)))
            self._db.commit()

    def close(self) -> None:
        self._db.close()


class CachingHTTPProvider(HTTPProvider):
    """HTTPProvider that serves immutable reads from an RpcCache."""

    def __init__(self, endpoint_uri: str, cache: RpcCache, namespace: str = "eth-mainnet",
                 **kwargs: Any) -> None:
        super().__init__(endpoint_uri, **kwargs)
        self.cache = cache
        self.namespace = namespace

    def make_request(self, method: Any, params: Any) -> Any:
        cacheable = is_cacheable(str(method), params)
        if cacheable:
            key = cache_key(self.namespace, str(method), params)
            hit = self.cache.get(key)
            if hit is not None:
                self.cache.hits += 1
                return {"jsonrpc": "2.0", "id": 0, "result": hit}
            self.cache.misses += 1
        resp = super().make_request(method, params)
        if cacheable and "error" not in resp and resp.get("result") is not None:
            self.cache.put(key, str(method), resp["result"])
        return resp
