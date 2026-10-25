"""Chunked eth_getLogs with retries, pacing and adaptive chunk size.

Free RPC tiers cap the block range per request (drpc: about 100 blocks) and rate-limit or time out.
Range errors halve the chunk (down to `min_chunk`); transient errors back off and retry. Pass a Web3
built on CachingHTTPProvider to make reruns free (pinned ranges are cacheable).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from web3 import Web3

RANGE_ERROR_HINTS = ("range", "block limit", "too many results", "too many logs", "exceed", "more than",
                     "not supported on free plan", "400 client error", "query timeout", "response size")


def is_range_error(e: Exception) -> bool:
    msg = str(e).lower()
    return any(h in msg for h in RANGE_ERROR_HINTS)


def fetch_logs(w3: Web3, address: str, topics: list[Any], from_block: int, to_block: int, *,
               chunk: int = 10_000, min_chunk: int = 50, pause_s: float = 0.0, retries: int = 6,
               progress: Callable[[int, int, int], None] | None = None) -> list[Any]:
    """All logs for `address`/`topics` in [from_block, to_block], in chain order."""
    logs: list[Any] = []
    b, size = from_block, chunk
    addr = Web3.to_checksum_address(address)
    while b <= to_block:
        failures = 0
        while True:
            e = min(b + size - 1, to_block)
            flt = {"address": addr, "topics": topics, "fromBlock": b, "toBlock": e}
            try:
                got = w3.eth.get_logs(flt)  # type: ignore[arg-type]
                break
            except Exception as err:
                if is_range_error(err) and size > min_chunk:
                    size = max(min_chunk, size // 2)      # shrink the window; does not count as a failure
                    continue
                failures += 1
                if failures >= retries:
                    raise
                time.sleep(min(30, 2 ** (failures - 1)))
        logs += got
        if progress:
            progress(e, to_block, len(logs))
        b = e + 1
        if pause_s and not getattr(w3.provider, "last_was_hit", False):   # no pause after a cache hit
            time.sleep(pause_s)
    return logs
