import pytest
from pydantic import ValidationError

from lapeg.config import ExperimentConfig, ForkConfig, MarketRef, resolve_fork_block, resolve_rpc_url

MID = "0x1e9d614631a7df0ec07fb05b2c8cb2491575fd1a63a33bf187a6afb295a4fc64"


def test_smoke_config_loads(smoke_cfg: ExperimentConfig) -> None:
    assert smoke_cfg.name == "phase0_fork_smoke"
    assert smoke_cfg.market.market_id == MID
    assert smoke_cfg.path(smoke_cfg.morpho_discovery).exists()


@pytest.mark.parametrize("bad", ["1e9d", "0x1234", "0x" + "g" * 64, MID + "00"])
def test_market_id_must_be_bytes32(bad: str) -> None:
    with pytest.raises(ValidationError):
        MarketRef(name="x", market_id=bad)


def test_block_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LAPEG_FORK_BLOCK", raising=False)
    assert resolve_fork_block(ForkConfig(block=100), head=500) == (100, True)
    recent = ForkConfig(allow_recent_block=True, recent_block_lag=8)
    assert resolve_fork_block(recent, head=500) == (492, False)
    with pytest.raises(RuntimeError):
        resolve_fork_block(ForkConfig(), head=500)
    monkeypatch.setenv("LAPEG_FORK_BLOCK", "123")
    assert resolve_fork_block(ForkConfig(block=100), head=500) == (123, True)


def test_rpc_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MY_RPC", raising=False)
    with pytest.raises(RuntimeError):
        resolve_rpc_url(ForkConfig(rpc_url_env="MY_RPC"))
    cfg = ForkConfig(rpc_url_env="MY_RPC", fallback_rpc_url="http://x")
    assert resolve_rpc_url(cfg) == ("http://x", "fallback")
    monkeypatch.setenv("MY_RPC", "http://archive")
    assert resolve_rpc_url(cfg) == ("http://archive", "MY_RPC")
