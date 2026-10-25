"""Shared fixtures. Fork tests (marker `fork`) start one anvil process per session.

Fork tests are skipped, not failed, when anvil is not installed or the RPC is unreachable.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator

import pytest
from web3 import Web3

from lapeg import PROJECT_ROOT
from lapeg.chain.morpho import MorphoBlue, load_morpho_address
from lapeg.config import ExperimentConfig, load_experiment, resolve_fork_block, resolve_rpc_url
from lapeg.fork.anvil import AnvilFork

SMOKE_CONFIG = PROJECT_ROOT / "experiments" / "phase0_fork_smoke.yaml"


@pytest.fixture(scope="session")
def smoke_cfg() -> ExperimentConfig:
    return load_experiment(SMOKE_CONFIG)


@pytest.fixture(scope="session")
def upstream(smoke_cfg: ExperimentConfig) -> tuple[str, int]:
    """(rpc_url, fork_block) for the session, or skip if the RPC is unreachable."""
    url, _ = resolve_rpc_url(smoke_cfg.fork)
    try:
        head = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 20})).eth.block_number
    except Exception as e:  # network down, bad key, ...
        pytest.skip(f"RPC unreachable: {e}")
    block, _ = resolve_fork_block(smoke_cfg.fork, head)
    return url, block


@pytest.fixture(scope="session")
def fork(upstream: tuple[str, int], smoke_cfg: ExperimentConfig) -> Iterator[AnvilFork]:
    if shutil.which("anvil") is None:
        pytest.skip("anvil not installed")
    url, block = upstream
    f = AnvilFork(url, block, extra_args=smoke_cfg.fork.anvil_args).start()
    try:
        yield f
    finally:
        f.stop()


@pytest.fixture(scope="session")
def morpho(fork: AnvilFork, smoke_cfg: ExperimentConfig) -> MorphoBlue:
    assert fork.w3 is not None
    return MorphoBlue(fork.w3, load_morpho_address(smoke_cfg.path(smoke_cfg.morpho_discovery)))
