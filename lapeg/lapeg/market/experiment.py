"""Phase 1 experiment: build the position book for one market at block N and check it against Morpho.

Acceptance (spec, Phase 1): every position's health factor matches the protocol's own computation to
within `hf_rel_tol` (default 1e-9) relative error. Checks:
  1. positions:    collateral and borrow shares replayed from events == Morpho's storage at block N (exact)
  2. totals:       sum of replayed borrow shares == market.totalBorrowShares (exact)
  3. health:       own integer math == HealthReader (Morpho's libraries) for every borrower, rel err <= tol
  4. liquidation:  for every borrower, Morpho's own `liquidate` agrees: it reverts with "position is healthy"
                   exactly when the computed health factor is >= 1
Outputs: data/results/position_book_<market>_<block>.parquet and a JSON report.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

import pandas as pd
import requests
from web3 import Web3

from lapeg.chain.abi import load_abi
from lapeg.chain.health_reader import HealthSnapshot, read_health
from lapeg.chain.indexer import fetch_logs
from lapeg.chain.morpho import MorphoBlue, load_morpho_address
from lapeg.chain.rpc_cache import CachingHTTPProvider, RpcCache
from lapeg.config import ExperimentConfig, resolve_fork_block, resolve_rpc_url
from lapeg.fork.anvil import AnvilFork
from lapeg.market import morpho_math as mm
from lapeg.market.position_book import apply_events, decode_position_events, event_topics

MORPHO_API = "https://api.morpho.org/graphql"
CREATION_QUERY = "query($id: String!) { marketById(marketId: $id, chainId: 1) { creationBlockNumber } }"
HEALTHY_REVERT = "position is healthy"


def discover_creation_block(w3: Web3, morpho: MorphoBlue, market_id: str) -> dict[str, Any]:
    """Creation block: hint from the Morpho API, confirmed by the CreateMarket log at that block."""
    body = requests.post(MORPHO_API, json={"query": CREATION_QUERY, "variables": {"id": market_id}},
                         timeout=60).json()
    hint = int(body["data"]["marketById"]["creationBlockNumber"])
    sig = "CreateMarket(bytes32,(address,address,address,address,uint256))"   # EventsLib.CreateMarket
    topic0 = "0x" + Web3.keccak(text=sig).hex().removeprefix("0x")
    logs = w3.eth.get_logs({"address": morpho.address, "topics": [topic0, market_id],  # type: ignore[typeddict-item]
                            "fromBlock": hint, "toBlock": hint})
    if len(logs) != 1:
        raise RuntimeError(f"CreateMarket log not found at API hint block {hint}")
    return {"creation_block": hint, "source": "Morpho API creationBlockNumber", "api_query": CREATION_QUERY,
            "verified_by": {"method": "eth_getLogs", "topic0": topic0, "topic1": market_id, "block": hint}}


def liquidation_reverts_healthy(w3: Web3, morpho: MorphoBlue, params_tuple: tuple[Any, ...],
                                borrower: str, caller: str) -> bool:
    """Does Morpho's own liquidate() refuse this borrower as healthy? (eth_call, nothing is executed)"""
    try:
        morpho.contract.functions.liquidate(params_tuple, borrower, 1, 0, b"").call({"from": caller})
    except Exception as e:
        return HEALTHY_REVERT in str(e)
    return False


def run_position_book(cfg: ExperimentConfig, write_results: bool = True) -> dict[str, Any]:
    t_start = time.monotonic()
    tol = float(cfg.params.get("hf_rel_tol", 1e-9))
    url, rpc_source = resolve_rpc_url(cfg.fork)
    upstream = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 60}))
    block, pinned = resolve_fork_block(cfg.fork, upstream.eth.block_number)
    market_id = cfg.market.market_id
    morpho_address = load_morpho_address(cfg.path(cfg.morpho_discovery))

    # 1. events, from a cached logs endpoint
    if cfg.logs is None:
        raise RuntimeError("experiment needs a `logs` section")
    logs_url, logs_source = resolve_rpc_url(cfg.logs)
    cache = RpcCache(cfg.path(cfg.cache_path))
    logs_w3 = Web3(CachingHTTPProvider(logs_url, cache, request_kwargs={"timeout": 120}))
    morpho_logs = MorphoBlue(logs_w3, morpho_address)
    creation = discover_creation_block(logs_w3, morpho_logs, market_id)

    def progress(done: int, end: int, n: int) -> None:
        span = end - creation["creation_block"] + 1
        pct = 100 * (done - creation["creation_block"] + 1) / span
        print(f"\r  logs: {pct:5.1f}% (block {done}), {n} events", end="", flush=True)

    topics = event_topics(morpho_logs.contract)
    raw = fetch_logs(logs_w3, morpho_address, [list(topics), market_id], creation["creation_block"], block,
                     chunk=cfg.logs.chunk, min_chunk=cfg.logs.min_chunk, pause_s=cfg.logs.pause_s,
                     progress=progress)
    print()
    events = decode_position_events(morpho_logs.contract, raw)
    book = apply_events(events)
    accounts = sorted(a for a, s in book.items() if s.collateral or s.borrow_shares)

    # 2. Morpho's own view at block N, on a fork
    with AnvilFork(url, block, extra_args=cfg.fork.anvil_args,
                   startup_timeout_s=cfg.fork.startup_timeout_s) as fork:
        assert fork.w3 is not None
        morpho = MorphoBlue(fork.w3, morpho_address)
        params = morpho.market_params(market_id)
        stored = morpho.market(market_id)
        snap: HealthSnapshot = read_health(fork.w3, morpho_address, market_id, accounts, accrue=True)
        snap_stored = read_health(fork.w3, morpho_address, market_id, accounts[:1], accrue=False)
        erc20 = load_abi("ERC20")
        def decimals(token: Any) -> int:
            assert fork.w3 is not None
            return int(fork.w3.eth.contract(address=token, abi=erc20).functions.decimals().call())

        loan_dec, coll_dec = decimals(params.loan_token), decimals(params.collateral_token)
        block_ts = int(fork.w3.eth.get_block(block)["timestamp"])

        rows, pos_mismatch, hf_errors = [], [], []
        for acct in accounts:
            mine, chain = book[acct], snap.accounts[acct]
            if (mine.collateral, mine.borrow_shares) != (chain.collateral, chain.borrow_shares):
                pos_mismatch.append(acct)
            borrowed = mm.borrowed_assets(mine.borrow_shares, snap.total_borrow_assets,
                                          snap.total_borrow_shares)
            max_b = mm.max_borrow(mine.collateral, snap.price, snap.lltv)
            hf_mine = mm.health_factor(borrowed, max_b)
            hf_chain = mm.health_factor(chain.borrowed, chain.max_borrow)
            if mine.borrow_shares:
                rel = abs(hf_mine - hf_chain) / hf_chain if hf_chain else abs(hf_mine)
                hf_errors.append(rel)
            rows.append({
                "market_id": market_id, "block": block, "borrower": acct,
                "collateral": mine.collateral / 10**coll_dec, "debt": borrowed / 10**loan_dec,
                "health_factor": hf_mine, "health_factor_morpho": hf_chain,
                "ltv": (borrowed * mm.ORACLE_PRICE_SCALE / (mine.collateral * snap.price))
                if mine.collateral else None,
                "collateral_raw": str(mine.collateral), "borrow_shares_raw": str(mine.borrow_shares),
                "debt_raw": str(borrowed), "max_borrow_raw": str(max_b),
            })

        borrowers = [r for r in rows if int(r["borrow_shares_raw"]) > 0]
        caller = Web3.to_checksum_address(Web3.keccak(text="lapeg-liquidation-probe")[-20:])
        disagree = []
        for r in borrowers:
            refused = liquidation_reverts_healthy(fork.w3, morpho, params.as_tuple(), r["borrower"], caller)
            if refused != (r["health_factor"] >= 1):
                disagree.append(r["borrower"])

    df = pd.DataFrame(rows)
    hf_borrowers = df.loc[df.borrow_shares_raw != "0", "health_factor"] if len(df) else pd.Series(dtype=float)
    checks = {
        "positions_match_morpho_storage": not pos_mismatch,
        "borrow_shares_sum_equals_market_total": sum(s.borrow_shares for s in book.values())
        == stored.total_borrow_shares,
        "stored_totals_match_market_view": (snap_stored.total_borrow_assets, snap_stored.total_borrow_shares)
        == (stored.total_borrow_assets, stored.total_borrow_shares),
        "health_factors_within_tol": bool(hf_errors) and max(hf_errors) <= tol,
        "liquidate_agrees_for_every_borrower": not disagree,
        "helper_read_at_fork_block": snap.block_number == block,
    }
    counts: dict[str, int] = {}
    for e in events:
        counts[e.kind] = counts.get(e.kind, 0) + 1
    report: dict[str, Any] = {
        "experiment": cfg.name, "run_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ"),
        "rpc_source": rpc_source, "logs_rpc_source": logs_source, "fork_block": block, "block_pinned": pinned,
        "block_timestamp": block_ts, "helper_timestamp": snap.timestamp,
        "market": {"name": cfg.market.name, "id": market_id}, "creation": creation,
        "log_query": {"address": morpho_address, "topic0": list(topics), "topic1": market_id,
                      "from_block": creation["creation_block"], "to_block": block},
        "n_events": len(events), "events_by_kind": counts, "n_accounts": len(accounts),
        "n_borrowers": len(borrowers), "max_hf_rel_error": max(hf_errors) if hf_errors else None,
        "hf_rel_tol": tol, "position_mismatches": pos_mismatch, "liquidate_disagreements": disagree,
        "min_health_factor": float(hf_borrowers.min()) if borrowers else None,
        "n_liquidatable": int((hf_borrowers < 1).sum()),
        "accrual_since_last_update": {"stored_total_borrow_assets": stored.total_borrow_assets,
                                      "expected_total_borrow_assets": snap.total_borrow_assets},
        "price_raw": str(snap.price), "lltv_raw": str(snap.lltv),
        "rpc_cache": {"hits": cache.hits, "misses": cache.misses},
        "seconds": round(time.monotonic() - t_start, 1), "checks": checks, "passed": all(checks.values()),
    }
    if write_results:
        out = cfg.path(cfg.results_dir)
        out.mkdir(parents=True, exist_ok=True)
        stem = f"position_book_{cfg.market.name}_{block}"
        df.to_parquet(out / f"{stem}.parquet", index=False)
        report["parquet"] = f"{stem}.parquet"
        (out / f"{cfg.name}_{report['run_utc']}.json").write_text(json.dumps(report, indent=1, default=str))
    report["_frame"] = df
    return report
