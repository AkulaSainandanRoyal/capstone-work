"""Phase 0 acceptance flow: fork, read a Morpho Blue market, snapshot, mutate, revert, confirm restored.

The mutation is a real `accrueInterest` call from an impersonated account after advancing time, so it
changes `lastUpdate` and the borrow totals through Morpho's own code (no storage layout assumptions).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from eth_utils import keccak
from web3 import Web3

from lapeg.chain.morpho import MorphoBlue, load_morpho_address
from lapeg.config import ExperimentConfig, resolve_fork_block, resolve_rpc_url
from lapeg.fork.anvil import AnvilFork

ADVANCE_SECONDS = 3600


def caller_for_seed(seed: int) -> str:
    """Deterministic throwaway EOA for a given seed."""
    return Web3.to_checksum_address(keccak(f"lapeg-caller-{seed}".encode())[-20:])


def run_fork_smoke(cfg: ExperimentConfig, write_results: bool = True) -> dict[str, Any]:
    url, rpc_source = resolve_rpc_url(cfg.fork)
    upstream = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 60}))
    block, pinned = resolve_fork_block(cfg.fork, upstream.eth.block_number)
    morpho_address = load_morpho_address(cfg.path(cfg.morpho_discovery))
    market_id = cfg.market.market_id

    with AnvilFork(url, block, port=cfg.fork.port, extra_args=cfg.fork.anvil_args,
                   startup_timeout_s=cfg.fork.startup_timeout_s) as fork:
        assert fork.w3 is not None
        morpho = MorphoBlue(fork.w3, morpho_address)
        params = morpho.market_params(market_id)
        before = morpho.market(market_id)

        snap = fork.snapshot()
        caller = caller_for_seed(cfg.seed)
        fork.set_eth_balance(caller, 10**18)
        fork.increase_time(ADVANCE_SECONDS)
        with fork.impersonated(caller):
            tx = morpho.contract.functions.accrueInterest(params.as_tuple()).transact({"from": caller})
            receipt = fork.w3.eth.wait_for_transaction_receipt(tx)
        mutated = morpho.market(market_id)

        fork.revert(snap)
        restored = morpho.market(market_id)
        block_after_revert = fork.block_number()

    checks = {
        "fork_at_requested_block": block_after_revert == block,
        "mutation_changed_state": mutated != before and mutated.last_update > before.last_update,
        "revert_restored_state": restored == before,
    }
    result = {
        "experiment": cfg.name,
        "run_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ"),
        "rpc_source": rpc_source,
        "fork_block": block,
        "block_pinned": pinned,
        "seed": cfg.seed,
        "morpho_blue": morpho_address,
        "market": {"name": cfg.market.name, "id": market_id, "params": asdict(params)},
        "mutation": {"call": "accrueInterest", "advance_seconds": ADVANCE_SECONDS, "caller": caller,
                     "tx_status": int(receipt["status"]), "gas_used": int(receipt["gasUsed"])},
        "state_before": asdict(before),
        "state_mutated": asdict(mutated),
        "state_after_revert": asdict(restored),
        "checks": checks,
        "passed": all(checks.values()),
    }
    if write_results:
        out_dir = cfg.path(cfg.results_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{cfg.name}_{result['run_utc']}.json").write_text(json.dumps(result, indent=1))
    return result
