"""Check whether the RPC serves historical state at a target date (default 2026-08-25 00:00 UTC).

Probes, in order of what they need from the node:
  history: eth_getBlockByNumber and eth_getLogs at the target block (any full node with that history)
  state:   eth_getBalance and a Morpho Blue eth_call at the target block (needs archive state)
  fork:    start anvil forked at the target block and read the market (what Phase 3 needs)

Output: data/discovered/archive_check.json (the RPC is recorded by env var name, never by URL).
Usage: python scripts/check_archive.py [--date 2026-08-25] [--rpc-env ARCHIVE_RPC_URL]
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from typing import Any

from web3 import Web3

from lapeg import PROJECT_ROOT
from lapeg.chain.morpho import MorphoBlue, load_morpho_address
from lapeg.fork.anvil import AnvilFork

PUBLIC_FALLBACK = "https://ethereum-rpc.publicnode.com"
DISCOVERED = PROJECT_ROOT / "data" / "discovered"


def block_at(w3: Web3, ts: int) -> int:
    """Last block with timestamp <= ts (binary search on timestamps, starting near the estimate)."""
    head = w3.eth.get_block("latest")
    est = int(head["number"]) - (int(head["timestamp"]) - ts) // 12
    lo, hi = max(1, est - 50_000), min(int(head["number"]), est + 50_000)
    if int(w3.eth.get_block(lo)["timestamp"]) > ts or int(w3.eth.get_block(hi)["timestamp"]) < ts:
        raise RuntimeError("target timestamp outside the search window")
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if int(w3.eth.get_block(mid)["timestamp"]) <= ts:
            lo = mid
        else:
            hi = mid - 1
    return lo


def probe(name: str, fn: Any) -> dict[str, Any]:
    try:
        return {"probe": name, "ok": True, "result": fn()}
    except Exception as e:
        return {"probe": name, "ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-08-25")
    ap.add_argument("--rpc-env", default="ARCHIVE_RPC_URL")
    ap.add_argument("--no-fork", action="store_true")
    ap.add_argument("--rpc-label", help="provider name to record (never put a URL with a key here)")
    a = ap.parse_args()

    url = os.environ.get(a.rpc_env)
    source = a.rpc_env if url else "public fallback (ethereum-rpc.publicnode.com)"
    if a.rpc_label:
        source = f"{source}: {a.rpc_label}"
    url = url or PUBLIC_FALLBACK
    w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 60}))
    ts = int(datetime.strptime(a.date, "%Y-%m-%d").replace(tzinfo=UTC).timestamp())
    block = block_at(w3, ts)

    morpho_addr = load_morpho_address(DISCOVERED / "morpho_blue.json")
    market_id = json.loads((DISCOVERED / "markets.json").read_text())["markets"][0]["market_id"]
    morpho = MorphoBlue(w3, morpho_addr)

    probes = [
        probe("history: eth_getBlockByNumber", lambda: int(w3.eth.get_block(block)["timestamp"])),
        probe("history: eth_getLogs (Morpho, 10 blocks)", lambda: len(w3.eth.get_logs(
            {"address": morpho_addr, "fromBlock": block, "toBlock": block + 9}))),
        probe("state: eth_getBalance", lambda: int(w3.eth.get_balance(morpho_addr, block))),
        probe("state: Morpho.market(id) eth_call", lambda: morpho.market(market_id, block).last_update),
    ]
    if not a.no_fork:
        def fork_read() -> int:
            with AnvilFork(url, block) as f:
                assert f.w3 is not None
                return MorphoBlue(f.w3, morpho_addr).market(market_id).last_update
        probes.append(probe("fork: anvil at block + Morpho.market(id)", fork_read))

    archive = all(p["ok"] for p in probes if not p["probe"].startswith("history"))
    out = {"checked_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "rpc": source,
           "target_date": a.date, "target_block": block, "archive_state_available": archive, "probes": probes}
    (DISCOVERED / "archive_check.json").write_text(json.dumps(out, indent=1) + "\n")
    print(f"RPC: {source}\ntarget {a.date} -> block {block}")
    for p in probes:
        detail = "" if p["ok"] else f"  ({p['error'][:90]})"
        print(f"  {'OK  ' if p['ok'] else 'FAIL'} {p['probe']}{detail}")
    print(f"archive state available: {archive}")


if __name__ == "__main__":
    main()
