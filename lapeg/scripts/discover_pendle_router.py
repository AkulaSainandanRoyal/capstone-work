"""Discover the Pendle router used by Convert API routes and verify it on Sourcify.

The router is the `tx.to` of the API's routes for a small PT -> USDC quote; Sourcify must report a verified
PendleRouter contract at that address. Output: data/discovered/pendle_router.json (with the query used).

Usage: python scripts/discover_pendle_router.py
"""

import json
from datetime import UTC, datetime

import requests
from web3 import Web3

from lapeg import PROJECT_ROOT
from lapeg.liquidity.pendle_api import CONVERT_URL, quote

D = PROJECT_ROOT / "data" / "discovered"


def main() -> None:
    market = next(
        m
        for m in json.loads((D / "markets.json").read_text())["markets"]
        if m["name"] == "PT-reUSD-10DEC2026"
    )
    receiver = Web3.to_checksum_address(Web3.keccak(text="lapeg-router-discovery")[-20:])
    q = quote(market["collateral_token"], market["loan_token"], 1_000 * 10**6, receiver)
    targets = sorted({Web3.to_checksum_address(r.tx_to) for r in q.routes})
    if len(targets) != 1:
        raise SystemExit(f"expected one router across routes, got {targets} (refusal: {q.refusal})")
    router = targets[0]
    meta = requests.get(
        f"https://sourcify.dev/server/v2/contract/1/{router}?fields=compilation", timeout=60
    ).json()
    name = (meta.get("compilation") or {}).get("name")
    if not (name or "").startswith("PendleRouter"):
        raise SystemExit(f"{router}: Sourcify name {name!r}, expected a PendleRouter")
    out = {
        "router": router,
        "verified_name": name,
        "n_routes": len(q.routes),
        "aggregators": [r.aggregator for r in q.routes],
        "retrieved_utc": datetime.now(UTC).isoformat(),
        "query": {
            "api": CONVERT_URL,
            "token_in": market["collateral_token"],
            "token_out": market["loan_token"],
            "amount_in": 1_000 * 10**6,
            "field": "routes[].tx.to",
        },
    }
    (D / "pendle_router.json").write_text(json.dumps(out, indent=1) + "\n")
    print(f"Pendle router: {router} ({name}), from {len(q.routes)} routes")


if __name__ == "__main__":
    main()
