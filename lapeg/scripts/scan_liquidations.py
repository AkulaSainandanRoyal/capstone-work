"""Scan Morpho Blue `Liquidate` events in a UTC date window and summarise them per market.

Used to locate (or rule out) the liquidation cascade the spec attributes to Aug 25, 2026. Nothing about the
event is assumed: markets, sizes and timing all come from the logs and from on-chain market params.

Output: data/discovered/<name>.json with the exact query (address, topic0, block range), per-market
summaries and every decoded event.
Usage: python scripts/scan_liquidations.py --start 2026-08-24 --end 2026-08-27 [--name aug25_event]
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from web3 import Web3

from lapeg import PROJECT_ROOT
from lapeg.chain.abi import load_abi
from lapeg.chain.morpho import MorphoBlue, load_morpho_address

DISCOVERED = PROJECT_ROOT / "data" / "discovered"


def retry(fn: Any, *args: Any, attempts: int = 6) -> Any:
    """Call fn(*args), retrying with exponential backoff (free RPC tiers time out and rate-limit)."""
    for i in range(attempts):
        try:
            return fn(*args)
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(2 ** i)


def block_at(w3: Web3, ts: int) -> int:
    head = retry(w3.eth.get_block, "latest")
    lo, hi = max(1, int(head["number"]) - (int(head["timestamp"]) - ts) // 12 - 50_000), int(head["number"])
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if int(retry(w3.eth.get_block, mid)["timestamp"]) <= ts:
            lo = mid
        else:
            hi = mid - 1
    return lo


def get_logs_chunked(w3: Web3, flt: dict[str, Any], start: int, end: int, chunk: int) -> list[Any]:
    logs: list[Any] = []
    b = start
    while b <= end:
        e = min(b + chunk - 1, end)
        logs += retry(w3.eth.get_logs, {**flt, "fromBlock": b, "toBlock": e})
        b = e + 1
    return logs


def token_meta(w3: Web3, address: str) -> dict[str, Any]:
    c = w3.eth.contract(address=Web3.to_checksum_address(address), abi=load_abi("ERC20"))
    return {"address": address, "symbol": c.functions.symbol().call(),
            "decimals": c.functions.decimals().call()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-08-24")
    ap.add_argument("--end", default="2026-08-27", help="exclusive")
    ap.add_argument("--name", default="aug25_event")
    ap.add_argument("--rpc-env", default="ARCHIVE_RPC_URL")
    ap.add_argument("--chunk", type=int, default=100, help="blocks per eth_getLogs (free tiers cap this)")
    ap.add_argument("--rpc-label", help="provider name to record (never put a URL with a key here)")
    a = ap.parse_args()
    url = os.environ.get(a.rpc_env)
    if not url:
        raise SystemExit(f"set {a.rpc_env}: a node that serves historical logs is needed")
    w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 120}))

    t0 = int(datetime.strptime(a.start, "%Y-%m-%d").replace(tzinfo=UTC).timestamp())
    t1 = int(datetime.strptime(a.end, "%Y-%m-%d").replace(tzinfo=UTC).timestamp())
    b0, b1 = block_at(w3, t0) + 1, block_at(w3, t1)

    morpho_addr = load_morpho_address(DISCOVERED / "morpho_blue.json")
    morpho = MorphoBlue(w3, morpho_addr)
    event = morpho.contract.events.Liquidate()
    topic0 = Web3.keccak(text="Liquidate(bytes32,address,address,uint256,uint256,uint256,uint256,uint256)")
    flt = {"address": morpho_addr, "topics": ["0x" + topic0.hex().removeprefix("0x")]}
    raw = get_logs_chunked(w3, flt, b0, b1, a.chunk)

    events, ts_cache = [], {}
    for log in raw:
        ev = event.process_log(log)
        bn = int(log["blockNumber"])
        if bn not in ts_cache:
            ts_cache[bn] = int(retry(w3.eth.get_block, bn)["timestamp"])
        args = ev["args"]
        events.append({"block": bn, "timestamp": ts_cache[bn],
                       "tx": "0x" + log["transactionHash"].hex().removeprefix("0x"),
                       "log_index": int(log["logIndex"]),
                       "market_id": "0x" + args["id"].hex().removeprefix("0x"),
                       "liquidator": args["caller"], "borrower": args["borrower"],
                       "repaid_assets": str(args["repaidAssets"]), "seized_assets": str(args["seizedAssets"]),
                       "bad_debt_assets": str(args["badDebtAssets"])})

    by_market: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in events:
        by_market[e["market_id"]].append(e)
    markets = []
    for mid, evs in sorted(by_market.items(), key=lambda kv: -len(kv[1])):
        p = morpho.market_params(mid)
        loan, coll = token_meta(w3, p.loan_token), token_meta(w3, p.collateral_token)
        ld, cd = 10 ** loan["decimals"], 10 ** coll["decimals"]
        markets.append({
            "market_id": mid, "loan": loan, "collateral": coll, "lltv": p.lltv / 1e18, "oracle": p.oracle,
            "n_liquidations": len(evs), "n_borrowers": len({e["borrower"] for e in evs}),
            "n_liquidators": len({e["liquidator"] for e in evs}),
            "repaid_loan_units": sum(int(e["repaid_assets"]) for e in evs) / ld,
            "seized_collateral_units": sum(int(e["seized_assets"]) for e in evs) / cd,
            "bad_debt_loan_units": sum(int(e["bad_debt_assets"]) for e in evs) / ld,
            "first_block": min(e["block"] for e in evs), "last_block": max(e["block"] for e in evs),
            "first_utc": datetime.fromtimestamp(min(e["timestamp"] for e in evs), UTC).isoformat(),
            "last_utc": datetime.fromtimestamp(max(e["timestamp"] for e in evs), UTC).isoformat(),
        })

    rpc_label = f"{a.rpc_env}: {a.rpc_label}" if a.rpc_label else a.rpc_env
    out = {"scanned_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "rpc": rpc_label,
           "query": {"method": "eth_getLogs", "address": morpho_addr, "topic0": flt["topics"][0],
                     "event": "Liquidate(Id indexed id, address indexed caller, address indexed borrower, "
                              "uint256 repaidAssets, uint256 repaidShares, uint256 seizedAssets, "
                              "uint256 badDebtAssets, uint256 badDebtShares)",
                     "window_utc": [a.start, a.end], "from_block": b0, "to_block": b1, "chunk": a.chunk},
           "n_events": len(events), "markets": markets, "events": events}
    path = DISCOVERED / f"{a.name}.json"
    path.write_text(json.dumps(out, indent=1) + "\n")
    print(f"blocks {b0}..{b1} ({a.start} to {a.end} UTC): "
          f"{len(events)} Liquidate events in {len(markets)} markets")
    for m in markets[:15]:
        print(f"  {m['n_liquidations']:4d}  {m['collateral']['symbol']:>28s}/{m['loan']['symbol']:<6s} "
              f"repaid {m['repaid_loan_units']:>14,.0f}  bad debt {m['bad_debt_loan_units']:>12,.0f}  "
              f"{m['first_utc'][5:16]} .. {m['last_utc'][5:16]}")
    print(f"wrote {path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
