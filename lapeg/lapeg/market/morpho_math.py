"""Morpho Blue's integer math, transcribed from MathLib.sol and SharesMathLib.sol (v1.0.0).

This is the independent side of the Phase 1 cross-check: health factors computed here must equal the ones
Morpho's own code produces on the fork (contracts/HealthReader.sol). Protocol behaviour itself always
comes from the fork; nothing here is used to decide what the chain does.
"""

from __future__ import annotations

WAD = 10**18
ORACLE_PRICE_SCALE = 10**36
VIRTUAL_SHARES = 10**6
VIRTUAL_ASSETS = 1
LIQUIDATION_CURSOR = 3 * 10**17          # 0.3e18
MAX_LIQUIDATION_INCENTIVE_FACTOR = 115 * 10**16  # 1.15e18


def mul_div_down(x: int, y: int, d: int) -> int:
    return (x * y) // d


def mul_div_up(x: int, y: int, d: int) -> int:
    return (x * y + (d - 1)) // d


def w_mul_down(x: int, y: int) -> int:
    return mul_div_down(x, y, WAD)


def w_div_down(x: int, y: int) -> int:
    return mul_div_down(x, WAD, y)


def to_assets_up(shares: int, total_assets: int, total_shares: int) -> int:
    return mul_div_up(shares, total_assets + VIRTUAL_ASSETS, total_shares + VIRTUAL_SHARES)


def to_assets_down(shares: int, total_assets: int, total_shares: int) -> int:
    return mul_div_down(shares, total_assets + VIRTUAL_ASSETS, total_shares + VIRTUAL_SHARES)


def borrowed_assets(borrow_shares: int, total_borrow_assets: int, total_borrow_shares: int) -> int:
    """Debt as Morpho._isHealthy sees it (rounded up)."""
    return to_assets_up(borrow_shares, total_borrow_assets, total_borrow_shares)


def max_borrow(collateral: int, price: int, lltv: int) -> int:
    """Largest healthy debt for this collateral, as Morpho._isHealthy computes it (rounded down)."""
    return w_mul_down(mul_div_down(collateral, price, ORACLE_PRICE_SCALE), lltv)


def is_healthy(borrowed: int, max_borrow_: int) -> bool:
    return max_borrow_ >= borrowed


def health_factor(borrowed: int, max_borrow_: int) -> float:
    """maxBorrow / borrowed: >= 1 healthy, < 1 liquidatable. Equals LLTV / LTV up to rounding."""
    return float("inf") if borrowed == 0 else max_borrow_ / borrowed


def liquidation_incentive_factor(lltv: int) -> int:
    """min(1.15, 1 / (1 - 0.3 * (1 - lltv))) in WAD, as in Morpho.liquidate."""
    cursor_term = w_mul_down(LIQUIDATION_CURSOR, WAD - lltv)
    return min(MAX_LIQUIDATION_INCENTIVE_FACTOR, w_div_down(WAD, WAD - cursor_term))
