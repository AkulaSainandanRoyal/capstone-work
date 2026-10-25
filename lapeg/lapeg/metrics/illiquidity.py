"""Illiquidity metrics (Phase 2). Definitions and rationale: lapeg/metrics/README.md.

All sizes are in raw collateral units (PT), because a price shock changes the dollar value of a position
but not the number of tokens a liquidator must sell.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

ORACLE_PRICE_SCALE = 10**36
WAD = 10**18


@dataclass(frozen=True)
class DepthPoint:
    amount_in: int  # raw PT sold
    status: str  # "ok", "reverted" or "refused"
    amount_out: int  # raw loan token received (best route)
    gas_used: int


def oracle_gap(amount_out: int, amount_in: int, oracle_price: int) -> float:
    """G(q) = 1 - P_exec / P_oracle, with P_oracle in raw loan units per raw collateral unit."""
    return 1 - (amount_out * ORACLE_PRICE_SCALE) / (amount_in * oracle_price)


def bonus_threshold(lif_wad: int) -> float:
    """Largest G at which a liquidation still breaks even before gas: 1 - 1/LIF (= 0.3(1-LLTV) uncapped)."""
    return 1 - WAD / lif_wad


def gas_adjusted_threshold(lif_wad: int, value_out_raw: float, gas_cost_raw: float) -> float:
    """Profit > 0 <=> V(1-G) - V/LIF - gas > 0 <=> G < (1 - 1/LIF) - gas/V (V: seized value at oracle)."""
    return bonus_threshold(lif_wad) - gas_cost_raw / value_out_raw


def passes(p: DepthPoint, oracle_price: int, threshold: Callable[[DepthPoint], float]) -> bool:
    return p.status == "ok" and oracle_gap(p.amount_out, p.amount_in, oracle_price) < threshold(p)


def q_max_bracket(
    points: Sequence[DepthPoint], oracle_price: int, threshold: Callable[[DepthPoint], float]
) -> tuple[DepthPoint | None, DepthPoint | None]:
    """(largest passing size below the first failure, first failing size). A failure is a revert, a refusal,
    or G at or above the threshold. (None, x): fails from the smallest size. (x, None): never fails."""
    pts = sorted(points, key=lambda p: p.amount_in)
    first_fail = next((p for p in pts if not passes(p, oracle_price, threshold)), None)
    below = [p for p in pts if first_fail is None or p.amount_in < first_fail.amount_in]
    ok = [p for p in below if passes(p, oracle_price, threshold)]
    return (ok[-1] if ok else None), first_fail


def monotone_violations(
    points: Sequence[DepthPoint], oracle_price: int, tol: float = 1e-4
) -> list[tuple[int, float]]:
    """Executed points where G drops by more than `tol` below a smaller size's G (spec: non-decreasing)."""
    pts = sorted((p for p in points if p.status == "ok"), key=lambda p: p.amount_in)
    out, best = [], float("-inf")
    for p in pts:
        g = oracle_gap(p.amount_out, p.amount_in, oracle_price)
        if g < best - tol:
            out.append((p.amount_in, best - g))
        best = max(best, g)
    return out


def can_clear(q_pt: int, lo: DepthPoint | None, hi: DepthPoint | None) -> bool | None:
    """Can one sale of q_pt be completed profitably? None when q falls inside the bracket (undetermined)."""
    if lo is not None and q_pt <= lo.amount_in:
        return True
    if hi is not None and q_pt >= hi.amount_in:
        return False
    if hi is None and lo is not None:
        return None if q_pt > lo.amount_in else True
    return None


@dataclass(frozen=True)
class ShockRow:
    shock: float
    n_liquidatable: int
    q_total_pt: int
    q_seizable_pt: int
    backlog_ratio: float | None  # q_seizable / q_max (PT); > 1: one block cannot clear it
    clears_in_one_sale: bool | None


def shock_row(
    shock: float, n: int, q_total: int, q_seiz: int, lo: DepthPoint | None, hi: DepthPoint | None
) -> ShockRow:
    ratio = q_seiz / lo.amount_in if lo is not None else None
    return ShockRow(shock, n, q_total, q_seiz, ratio, can_clear(q_seiz, lo, hi) if q_seiz else True)
