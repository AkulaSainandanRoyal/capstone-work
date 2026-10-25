"""Guard v0 (Phase 5, shortened scope): PASS or DELAY for pending transactions, with a counterfactual log.

For each pending transaction the fast tier (Phase 4) is run twice on the same state: without the
transaction (what the guard's choice preserves) and with it (the counterfactual if it were included).
The risk of a transaction is what it *adds*: liquidatable debt that the market cannot clear (stuck debt)
plus realised bad debt. Above the policy threshold the transaction is delayed by one block and
re-evaluated; after `max_delays` it is dropped only if the policy allows DROP (off by default, as the spec
requires), otherwise it is released and flagged.

v0 limits (see docs/design_phases4_7.md): the fast tier is not yet validated (Phase 3), there is no exact-tier
confirmation, no REORDER search, and transactions are modelled by their effect (PT sold into the market or an
oracle move), not by their calldata.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from lapeg.cascade.fast import MarketModel, Params, Position, Result, simulate

Action = Literal["PASS", "DELAY", "DROP", "RELEASE"]


@dataclass(frozen=True)
class PendingTx:
    tx_id: str
    kind: Literal["sell_pt", "oracle_move"]
    pt_sold: int = 0  # raw PT the transaction sells into the market (sell_pt)
    oracle_move: float = 0.0  # proportional oracle drop the transaction causes (oracle_move)
    note: str = ""


@dataclass(frozen=True)
class Policy:
    risk_threshold: int = 0  # loan raw units of added stuck debt + bad debt tolerated
    max_delays: int = 3
    allow_drop: bool = False  # spec: keep DROP off by default (censorship)
    params: Params = Params()


@dataclass
class Decision:
    tx_id: str
    block: int
    action: Action
    reason: str
    risk: int
    without_tx: dict[str, Any]
    with_tx: dict[str, Any]
    delays_so_far: int
    latency_ms: float


@dataclass
class GuardLog:
    decisions: list[Decision] = field(default_factory=list)

    def rows(self) -> list[dict[str, Any]]:
        return [asdict(d) for d in self.decisions]


def _risk(r: Result) -> int:
    return r.stuck_debt + r.bad_debt


def assess(
    positions: list[Position],
    model: MarketModel,
    tx: PendingTx,
    params: Params,
    baseline: Result | None = None,
) -> tuple[int, Result, Result]:
    """(added risk, outcome without tx, outcome with tx)."""
    base = baseline or simulate(positions, model, params)
    with_tx = simulate(positions, model, params, shock_pt_sold=tx.pt_sold, oracle_shock=tx.oracle_move)
    return max(0, _risk(with_tx) - _risk(base)), base, with_tx


def run(
    positions: list[Position],
    model: MarketModel,
    pending_by_block: list[list[PendingTx]],
    policy: Policy | None = None,
) -> GuardLog:
    """Sidecar loop over blocks. Delayed transactions re-enter the next block's pending set.

    State is held fixed across blocks in v0 (no market evolution between blocks), so a risky transaction
    stays risky; the loop shows the policy mechanics (DELAY, then DROP or RELEASE), not market recovery."""
    policy = policy or Policy()
    log = GuardLog()
    delays: dict[str, int] = {}
    carry: list[PendingTx] = []
    base = simulate(positions, model, policy.params)
    blocks = len(pending_by_block) + policy.max_delays + 1
    for blk in range(blocks):
        pending = carry + (pending_by_block[blk] if blk < len(pending_by_block) else [])
        carry = []
        for tx in pending:
            t0 = time.perf_counter()
            risk, without, with_tx = assess(positions, model, tx, policy.params, base)
            n = delays.get(tx.tx_id, 0)
            if risk <= policy.risk_threshold:
                action: Action = "PASS"
                reason = "no added unclearable debt"
            elif n < policy.max_delays:
                action, reason = "DELAY", f"adds {risk} raw units of stuck or bad debt; delay {n + 1}"
                delays[tx.tx_id] = n + 1
                carry.append(tx)
            elif policy.allow_drop:
                action, reason = "DROP", f"still risky after {n} delays"
            else:
                action, reason = (
                    "RELEASE",
                    f"still risky after {n} delays; DROP disabled, released and flagged",
                )
            log.decisions.append(
                Decision(
                    tx.tx_id,
                    blk,
                    action,
                    reason,
                    risk,
                    without.summary(),
                    with_tx.summary(),
                    n,
                    1000 * (time.perf_counter() - t0),
                )
            )
    return log
