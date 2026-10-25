"""Fork tests: anvil lifecycle, snapshots, impersonation, balances, storage writes, RPC cache, acceptance."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from eth_typing import ChecksumAddress
from eth_utils import keccak
from web3 import Web3
from web3.exceptions import Web3RPCError
from web3.types import Wei

from lapeg import PROJECT_ROOT
from lapeg.chain.morpho import MorphoBlue
from lapeg.chain.rpc_cache import CachingHTTPProvider, RpcCache
from lapeg.config import ExperimentConfig
from lapeg.fork.anvil import AnvilFork, SnapshotError
from lapeg.fork.smoke import run_fork_smoke
from lapeg.fork.state import balance_of, find_balance_slot, set_erc20_balance

pytestmark = pytest.mark.fork

MARKETS = json.loads((PROJECT_ROOT / "data" / "discovered" / "markets.json").read_text())["markets"]
REUSD = next(m for m in MARKETS if m["name"] == "PT-reUSD-10DEC2026")


def eoa(tag: str) -> ChecksumAddress:
    return Web3.to_checksum_address(keccak(tag.encode())[-20:])


def test_fork_starts_at_requested_block(fork: AnvilFork, upstream: tuple[str, int]) -> None:
    assert fork.running
    assert fork.block_number() == upstream[1]
    assert int(fork.rpc("eth_chainId"), 16) == 1


def test_snapshot_revert_restores_and_consumes(fork: AnvilFork) -> None:
    assert fork.w3 is not None
    who = eoa("snapshot-test")
    original = fork.w3.eth.get_balance(who)
    snap = fork.snapshot()
    fork.set_eth_balance(who, original + 12345)
    assert fork.w3.eth.get_balance(who) == original + 12345
    fork.revert(snap)
    assert fork.w3.eth.get_balance(who) == original
    with pytest.raises(SnapshotError):      # anvil consumes a snapshot on revert
        fork.revert(snap)


def test_branch_undoes_everything(fork: AnvilFork) -> None:
    assert fork.w3 is not None
    who = eoa("branch-test")
    before = fork.w3.eth.get_balance(who)
    with fork.branch():
        fork.set_eth_balance(who, 10**20)
        with fork.branch():                 # nested branches work
            fork.set_eth_balance(who, 1)
        assert fork.w3.eth.get_balance(who) == 10**20
    assert fork.w3.eth.get_balance(who) == before


def test_impersonation_sends_transactions(fork: AnvilFork) -> None:
    assert fork.w3 is not None
    sender, receiver = eoa("sender"), eoa("receiver")
    with fork.branch():
        fork.set_eth_balance(sender, 10**18)
        start = fork.w3.eth.get_balance(receiver)
        with fork.impersonated(sender):
            tx = fork.w3.eth.send_transaction({"from": sender, "to": receiver, "value": Wei(777)})
            assert fork.w3.eth.wait_for_transaction_receipt(tx)["status"] == 1
        assert fork.w3.eth.get_balance(receiver) == start + 777
        with pytest.raises(Web3RPCError):  # no longer impersonated: anvil refuses to sign
            fork.w3.eth.send_transaction({"from": sender, "to": receiver, "value": Wei(1)})


def test_storage_write_roundtrip(fork: AnvilFork) -> None:
    token, slot = REUSD["loan_token"], 123456789
    original = fork.get_storage(token, slot)
    with fork.branch():
        fork.set_storage(token, slot, 42)
        assert fork.get_storage(token, slot) == 42
    assert fork.get_storage(token, slot) == original


@pytest.mark.parametrize("which", ["loan_token", "collateral_token"])
def test_set_erc20_balance(fork: AnvilFork, which: str) -> None:
    token, holder = REUSD[which], eoa(f"holder-{which}")
    original = balance_of(fork, token, holder)
    with fork.branch():
        slot = find_balance_slot(fork, token)
        set_erc20_balance(fork, token, holder, 5 * 10**12, slot)
        assert balance_of(fork, token, holder) == 5 * 10**12
    assert balance_of(fork, token, holder) == original


def test_market_params_match_discovery(morpho: MorphoBlue) -> None:
    p = morpho.market_params(REUSD["market_id"])
    assert (p.loan_token, p.collateral_token, p.oracle, p.irm, str(p.lltv)) == (
        REUSD["loan_token"], REUSD["collateral_token"], REUSD["oracle"], REUSD["irm"], REUSD["lltv_wad"])
    assert morpho.oracle_price(p.oracle) > 0


def test_rpc_cache_against_upstream(upstream: tuple[str, int], tmp_path: Path) -> None:
    url, block = upstream
    cache = RpcCache(tmp_path / "rpc.sqlite")
    w3 = Web3(CachingHTTPProvider(url, cache, request_kwargs={"timeout": 30}))
    first = w3.eth.get_block(block)
    second = w3.eth.get_block(block)
    assert first["hash"] == second["hash"]
    assert (cache.hits, cache.misses) == (1, 1)


def test_phase0_acceptance(smoke_cfg: ExperimentConfig, upstream: tuple[str, int],
                           monkeypatch: pytest.MonkeyPatch) -> None:
    """Fork at a block, read a Morpho Blue market, snapshot, mutate, revert, confirm restored."""
    monkeypatch.setenv("LAPEG_FORK_BLOCK", str(upstream[1]))
    result: dict[str, Any] = run_fork_smoke(smoke_cfg, write_results=False)
    assert result["mutation"]["tx_status"] == 1
    assert result["checks"] == {"fork_at_requested_block": True, "mutation_changed_state": True,
                                "revert_restored_state": True}
    assert result["state_after_revert"] == result["state_before"]
