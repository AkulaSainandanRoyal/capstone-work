import math

import pytest

from lapeg.market import morpho_math as mm


def test_rounding_directions() -> None:
    assert mm.mul_div_down(7, 3, 2) == 10 and mm.mul_div_up(7, 3, 2) == 11
    assert mm.mul_div_up(6, 3, 2) == 9          # exact division does not round up
    assert mm.to_assets_up(10, 100, 1000) >= mm.to_assets_down(10, 100, 1000)


def test_virtual_shares_and_assets() -> None:
    # shares * (assets + 1) / (shares_total + 1e6), rounded up
    assert mm.to_assets_up(10**6, 0, 0) == 1
    assert mm.to_assets_up(10**12, 10**6, 10**12) == math.ceil(10**12 * (10**6 + 1) / (10**12 + 10**6))


def test_max_borrow_matches_hand_computation() -> None:
    # 1,000 PT (6 dec) at oracle 0.98 (scale 1e36 for 6/6 decimals), LLTV 91.5%
    collateral, price, lltv = 1_000 * 10**6, 98 * 10**34, 915 * 10**15
    assert mm.max_borrow(collateral, price, lltv) == 896_700_000      # 896.70 USDC


def test_health_factor() -> None:
    assert mm.health_factor(0, 5) == float("inf")
    assert mm.health_factor(100, 100) == 1.0 and mm.is_healthy(100, 100)
    assert not mm.is_healthy(101, 100)


@pytest.mark.parametrize("lltv,expected", [(915 * 10**15, 1.0261672652642382),
                                           (86 * 10**16, 1.0438413361169103), (5 * 10**17, 1.15)])
def test_liquidation_incentive_factor(lltv: int, expected: float) -> None:
    assert mm.liquidation_incentive_factor(lltv) / mm.WAD == pytest.approx(expected, rel=1e-15)
