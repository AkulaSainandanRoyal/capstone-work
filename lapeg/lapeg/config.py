"""Experiment configuration: one YAML file per run under experiments/.

Every run is reproducible from its config: RPC (by env var name, never the URL itself, so keys stay out of
the repo), block, seed and parameters. When no archive RPC is available, `allow_recent_block` lets a run
fork a recent block instead; the block actually used is recorded in the run output, but that run can only
be replayed on an archive RPC.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from lapeg import PROJECT_ROOT


class ForkConfig(BaseModel):
    rpc_url_env: str = "ARCHIVE_RPC_URL"
    fallback_rpc_url: str | None = None      # used only when rpc_url_env is unset; may be non-archive
    block: int | None = None                 # pinned fork block (required for reproducible runs)
    allow_recent_block: bool = False         # if block is None: fork at head - recent_block_lag
    recent_block_lag: int = Field(default=8, ge=0)
    port: int | None = None                  # None: pick a free port
    anvil_args: list[str] = Field(default_factory=list)
    startup_timeout_s: float = 90.0


class MarketRef(BaseModel):
    name: str
    market_id: str

    @field_validator("market_id")
    @classmethod
    def _bytes32(cls, v: str) -> str:
        v = v.lower()
        if not (v.startswith("0x") and len(v) == 66 and all(c in "0123456789abcdef" for c in v[2:])):
            raise ValueError("market_id must be a 0x-prefixed 32-byte hex string")
        return v


class ExperimentConfig(BaseModel):
    name: str
    seed: int = 0
    fork: ForkConfig
    morpho_discovery: Path = Path("data/discovered/morpho_blue.json")
    market: MarketRef
    cache_path: Path = Path("data/raw/rpc_cache.sqlite")
    results_dir: Path = Path("data/results")
    params: dict[str, Any] = Field(default_factory=dict)

    def path(self, p: Path) -> Path:
        """Resolve a config path relative to the project root."""
        return p if p.is_absolute() else PROJECT_ROOT / p


def load_experiment(path: str | Path) -> ExperimentConfig:
    with open(path, encoding="utf-8") as f:
        return ExperimentConfig.model_validate(yaml.safe_load(f))


def resolve_rpc_url(fork: ForkConfig) -> tuple[str, str]:
    """Return (url, source). source is the env var name, or 'fallback' for the non-archive default."""
    url = os.environ.get(fork.rpc_url_env)
    if url:
        return url, fork.rpc_url_env
    if fork.fallback_rpc_url:
        return fork.fallback_rpc_url, "fallback"
    raise RuntimeError(f"set {fork.rpc_url_env} (an archive RPC URL) or give fork.fallback_rpc_url")


def resolve_fork_block(fork: ForkConfig, head: int) -> tuple[int, bool]:
    """Return (block, pinned). LAPEG_FORK_BLOCK in the environment overrides the config."""
    env_block = os.environ.get("LAPEG_FORK_BLOCK")
    if env_block:
        return int(env_block), True
    if fork.block is not None:
        return fork.block, True
    if fork.allow_recent_block:
        return head - fork.recent_block_lag, False
    raise RuntimeError("fork.block is not set and allow_recent_block is false")
