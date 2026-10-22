"""Discover the Morpho Blue address on Ethereum and verify it on-chain.

1. Ask Morpho's GraphQL API for the Morpho Blue deployment on chain 1.
2. Check on-chain that the address has code and that idToMarketParams() for each market in the
   capstone dataset returns the same collateral token, oracle and LLTV as the dataset.
3. Write data/discovered/morpho_blue.json and data/discovered/markets.json, including the queries used.

Usage: python scripts/discover_morpho.py [--rpc URL] [--markets ../results/morpho_pt_markets_clean.csv]
"""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests
from web3 import Web3

from lapeg import PROJECT_ROOT
from lapeg.chain.morpho import MorphoBlue

API = "https://api.morpho.org/graphql"
QUERY = "{ morphoBlues(where: {chainId_in: [1]}) { items { address creationBlockNumber chain { id } } } }"
OUT = PROJECT_ROOT / "data" / "discovered"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rpc", default=os.environ.get("ARCHIVE_RPC_URL", "https://ethereum-rpc.publicnode.com"))
    ap.add_argument("--markets", default=str(PROJECT_ROOT.parent / "results" / "morpho_pt_markets_clean.csv"))
    a = ap.parse_args()
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    body = requests.post(API, json={"query": QUERY}, timeout=60).json()
    if body.get("errors"):
        raise SystemExit(f"GraphQL error: {body['errors']}")
    items = body["data"]["morphoBlues"]["items"]
    if len(items) != 1:
        raise SystemExit(f"expected exactly one Morpho Blue deployment on chain 1, got {items}")
    address = Web3.to_checksum_address(items[0]["address"])

    w3 = Web3(Web3.HTTPProvider(a.rpc, request_kwargs={"timeout": 60}))
    block = w3.eth.block_number
    code_len = len(w3.eth.get_code(address, block_identifier=block))
    morpho = MorphoBlue(w3, address)

    markets, checks = [], {"has_code": code_len > 0}
    for _, r in pd.read_csv(a.markets).iterrows():
        p = morpho.market_params(r["market_id"], block)
        match = {
            "collateral_token": p.collateral_token.lower() == r["collateral_token"].lower(),
            "oracle": p.oracle.lower() == r["oracle"].lower(),
            "lltv": p.lltv == round(float(r["lltv"]) * 10**18),
        }
        checks[f"{r['market']}_matches_dataset"] = all(match.values())
        markets.append({"name": r["market"], "market_id": r["market_id"], "loan_token": p.loan_token,
                        "collateral_token": p.collateral_token, "oracle": p.oracle, "irm": p.irm,
                        "lltv_wad": str(p.lltv), "field_matches": match})

    OUT.mkdir(parents=True, exist_ok=True)
    source = {"api": API, "query": QUERY, "retrieved_utc": now,
              "verified_on_chain": {"rpc": "ARCHIVE_RPC_URL" if os.environ.get("ARCHIVE_RPC_URL") else a.rpc,
                                    "block": block, "method": "eth_getCode + idToMarketParams(id)"}}
    (OUT / "morpho_blue.json").write_text(json.dumps(
        {"chain_id": 1, "address": address, "creation_block": items[0]["creationBlockNumber"],
         "checks": checks, **source}, indent=1) + "\n")
    (OUT / "markets.json").write_text(json.dumps(
        {"markets": markets, "dataset": Path(a.markets).name, **source}, indent=1) + "\n")

    print(f"Morpho Blue: {address} (code {code_len} bytes) at block {block}")
    for k, v in checks.items():
        print(f"  {'OK ' if v else 'FAIL'} {k}")
    if not all(checks.values()):
        raise SystemExit("verification failed")


if __name__ == "__main__":
    main()
