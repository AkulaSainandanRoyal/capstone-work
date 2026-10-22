# LAPEG: Liquidity-Aware Pre-Execution Guard

Research prototype for the capstone "Measurement and Mitigation of Illiquidity in Collateral-Based Lending in
DeFi". It simulates pending transactions on a mainnet fork and predicts whether they push positions backed by
illiquid collateral into liquidations the market cannot absorb.

**Status: Phase 0 complete** (fork lifecycle, snapshots, impersonation, balances, storage writes, RPC cache),
plus the addendum's pre-work: archive check, interfaces, oracle sources, Aug 25 event scan. See
[`docs/assumptions.md`](docs/assumptions.md) for findings and open items.

## Setup

Requires Python 3.11+ and Foundry (`anvil`, `forge`, `cast`).

```bash
pip install -e ".[dev]"
forge install foundry-rs/forge-std@v1.10.0 --no-git   # lib/ is not committed
export ARCHIVE_RPC_URL=...                             # archive RPC; see .env.example
```

Without `ARCHIVE_RPC_URL`, tests and the smoke experiment fall back to a public non-archive RPC and fork a recent
block. That works for development, but such runs cannot be replayed.

## Layout

```
experiments/        one YAML per run (RPC env var, block, seed, market, parameters)
data/discovered/    facts found on-chain, each with the query used
data/results/       run outputs (JSON)
data/raw/           local caches (git-ignored)
contracts/vendor/   verified sources, copied unchanged (see SOURCE.md)
docs/               interfaces.md, assumptions.md
lapeg/fork/         anvil lifecycle, snapshots, state overrides, Phase 0 acceptance flow
lapeg/chain/        ABIs (compiled from vendored sources), Morpho Blue adapter, RPC cache
lapeg/...           market, liquidity, oracle, agents, cascade, guard, policy, replay, metrics, viz (later phases)
scripts/            discovery and build scripts
tests/, test/       pytest and forge tests
```

## Commands

| Task | Command |
|---|---|
| Phase 0 acceptance (from config) | `python scripts/run_experiment.py experiments/phase0_fork_smoke.yaml` |
| Python tests (includes fork tests) | `pytest` (skip fork tests: `pytest -m "not fork"`) |
| Solidity fork test | `forge test` |
| Lint and types | `ruff check . && mypy lapeg scripts tests` |
| Rebuild ABIs from vendored sources | `python scripts/build_abis.py` |
| Discover and verify Morpho Blue and markets | `python scripts/discover_morpho.py` |
| Walk each market's oracle to its price sources | `python scripts/inspect_oracles.py` |
| Check archive access at a date | `python scripts/check_archive.py --date 2026-08-25` |
| Scan `Liquidate` events in a date window | `python scripts/scan_liquidations.py --start 2026-08-24 --end 2026-08-27` |

## Fork API (Phase 0)

```python
from lapeg.fork import AnvilFork

with AnvilFork(rpc_url, block) as fork:
    snap = fork.snapshot()                  # consumed by revert
    fork.impersonate(addr); fork.set_eth_balance(addr, 10**18)
    fork.set_storage(token, slot, value)    # anvil_setStorageAt
    with fork.branch():                     # everything inside is undone on exit
        ...
    fork.revert(snap)
```

`lapeg.fork.state.set_erc20_balance(fork, token, holder, amount)` finds the token's balance slot by probing.
`swap(token_in, token_out, amount)` from the agreed fork interface is Phase 2 work.

## Ground rules

From the spec: protocol logic always comes from deployed contracts on a fork; every run is reproducible from a
config; addresses and events are discovered on-chain and recorded with their queries; ABIs come from verified
sources.
