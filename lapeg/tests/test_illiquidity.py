import pytest

from lapeg.market import morpho_math as mm
from lapeg.metrics import illiquidity as il

PRICE = 10**36   # 1 raw loan unit per raw collateral unit


def pt(amount: int, out: int, status: str = "ok", gas: int = 0) -> il.DepthPoint:
    return il.DepthPoint(amount, status, out, gas)


def test_oracle_gap() -> None:
    assert il.oracle_gap(980, 1000, PRICE) == pytest.approx(0.02)
    assert il.oracle_gap(1010, 1000, PRICE) == pytest.approx(-0.01)     # market pays above the oracle
    assert il.oracle_gap(490, 1000, PRICE // 2) == pytest.approx(0.02)  # oracle at 0.5


def test_thresholds() -> None:
    lif = mm.liquidation_incentive_factor(915 * 10**15)
    assert il.bonus_threshold(lif) == pytest.approx(0.0255, abs=1e-12)
    # $1M seized, $1k gas: threshold drops by 0.1 percentage point
    assert il.gas_adjusted_threshold(lif, 1e6, 1e3) == pytest.approx(0.0255 - 0.001, abs=1e-12)


def test_q_max_bracket_slippage_and_refusal() -> None:
    thr = lambda _: 0.025  # noqa: E731
    pts = [pt(100, 99), pt(200, 197), pt(400, 380), pt(800, 0, "refused")]
    lo, hi = il.q_max_bracket(pts, PRICE, thr)
    assert lo is not None and hi is not None and (lo.amount_in, hi.amount_in) == (200, 400)   # 400: G = 5%
    lo, hi = il.q_max_bracket([pt(100, 99), pt(200, 198), pt(400, 0, "refused")], PRICE, thr)
    assert lo is not None and hi is not None and (lo.amount_in, hi.amount_in) == (200, 400)   # refusal fails
    lo, hi = il.q_max_bracket([pt(100, 99), pt(200, 198)], PRICE, thr)
    assert lo is not None and lo.amount_in == 200 and hi is None                              # never fails
    lo, hi = il.q_max_bracket([pt(100, 90)], PRICE, thr)
    assert lo is None and hi is not None                                                       # fails at once


def test_monotone_violations() -> None:
    assert il.monotone_violations([pt(100, 99), pt(200, 197), pt(400, 390)], PRICE) == []
    v = il.monotone_violations([pt(100, 99), pt(200, 190), pt(400, 396)], PRICE)
    assert len(v) == 1 and v[0][0] == 400


def test_can_clear_and_backlog() -> None:
    lo, hi = pt(200, 198), pt(400, 380)
    assert il.can_clear(150, lo, hi) is True
    assert il.can_clear(500, lo, hi) is False
    assert il.can_clear(300, lo, hi) is None     # inside the bracket: undetermined
    row = il.shock_row(0.05, 3, 1_000, 600, lo, hi)
    assert row.backlog_ratio == pytest.approx(3.0) and row.clears_in_one_sale is False
