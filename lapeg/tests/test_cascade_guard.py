"""Fast tier (Phase 4) and guard v0 (Phase 5) on synthetic markets."""

from lapeg.cascade.fast import DepthCurve, MarketModel, Params, Position, simulate
from lapeg.guard.guard import PendingTx, Policy, run

WAD, SCALE = 10**18, 10**36
LLTV = 915 * 10**15
PRICE = SCALE  # oracle = market = 1 raw loan unit per raw PT


def flat_depth(capacity: int) -> DepthCurve:
    """Sell at exactly the oracle price up to `capacity`, refused beyond."""
    return DepthCurve([capacity // 2, capacity], [capacity // 2, capacity])


def sloped_depth(k: float = 0.25) -> DepthCurve:
    """Marginal price falls linearly from 1.0 to 1 - 2k over 1,000,000 PT."""
    xs = [10_000 * i for i in range(1, 101)]
    return DepthCurve(xs, [int(x - k * x * x / 1_000_000) for x in xs])


def pos(name: str, collateral: int, ltv: float) -> Position:
    return Position(name, collateral, int(collateral * ltv))


def test_depth_curve_interpolation_and_limits() -> None:
    d = flat_depth(1000)
    assert d.proceeds(250) == 250 and d.sale(250, 500) == 500
    assert d.sale(800, 300) is None  # beyond capacity: cannot be sold
    s = sloped_depth()
    assert s.marginal_price(0) > s.marginal_price(900_000)


def test_no_shock_no_liquidation_and_fixed_point() -> None:
    model = MarketModel(LLTV, PRICE, flat_depth(10**9))
    r = simulate([pos("a", 1000, 0.80)], model, Params(twap_blocks=1))
    assert r.n_liquidations == 0 and r.fixed_point and not r.stuck


def test_oracle_shock_liquidates_profitably_within_capacity() -> None:
    model = MarketModel(LLTV, PRICE, flat_depth(10**9))
    r = simulate([pos("a", 10_000, 0.90)], model, Params(twap_blocks=1, latency_blocks=0), oracle_shock=0.05)
    assert r.n_liquidations == 1 and r.liquidations[0].profit > 0 and not r.stuck


def test_beyond_capacity_is_stuck() -> None:
    model = MarketModel(LLTV, PRICE, flat_depth(5_000))
    r = simulate(
        [pos("big", 100_000, 0.90)], model, Params(twap_blocks=1, latency_blocks=0), oracle_shock=0.05
    )
    assert r.n_liquidations == 0 and "big" in r.stuck and r.stuck_debt > 0


def test_twap_lag_delays_liquidations() -> None:
    model = MarketModel(LLTV, PRICE, sloped_depth())
    people = [pos("a", 50_000, 0.90)]
    lagged = simulate(people, model, Params(twap_blocks=20, latency_blocks=0), shock_pt_sold=400_000)
    instant = simulate(people, model, Params(twap_blocks=1, latency_blocks=0), shock_pt_sold=400_000)
    assert instant.n_liquidations == 1 and instant.liquidations[0].block == 0
    assert lagged.n_liquidations == 1 and lagged.liquidations[0].block > 0


def test_cascade_feedback_liquidates_more_than_one_step() -> None:
    # A 2% oracle shock makes only "a" liquidatable. Selling a's seized PT (~1.4% slippage, profitable)
    # moves the market about 2.8% lower, the oracle follows, and "b" becomes liquidatable a block later.
    model = MarketModel(LLTV, PRICE, sloped_depth(0.05))
    people = [pos("a", 300_000, 0.905), pos("b", 200_000, 0.875)]
    one_step = simulate(
        people, model, Params(twap_blocks=1, latency_blocks=0, horizon_blocks=1), oracle_shock=0.02
    )
    assert {x.account for x in one_step.liquidations} == {"a"}
    r = simulate(people, model, Params(twap_blocks=1, latency_blocks=0), oracle_shock=0.02)
    assert [x.account for x in r.liquidations] == ["a", "b"]
    assert r.liquidations[1].block > r.liquidations[0].block and r.fixed_point


def test_unprofitable_sale_is_not_executed() -> None:
    # steep curve: selling a's seized PT would lose more than the 2.55% bonus, so nobody liquidates
    model = MarketModel(LLTV, PRICE, sloped_depth(0.25))
    r = simulate(
        [pos("a", 300_000, 0.905)], model, Params(twap_blocks=1, latency_blocks=0), oracle_shock=0.02
    )
    assert r.n_liquidations == 0 and "a" in r.stuck


def test_guard_passes_safe_and_delays_risky() -> None:
    model = MarketModel(LLTV, PRICE, flat_depth(50_000))
    people = [pos("big", 100_000, 0.90)]
    safe = PendingTx("safe", "oracle_move", oracle_move=0.0)
    risky = PendingTx("risky", "oracle_move", oracle_move=0.05)
    log = run(
        people, model, [[safe, risky]], Policy(max_delays=2, params=Params(twap_blocks=1, latency_blocks=0))
    )
    actions = [(d.tx_id, d.action) for d in log.decisions]
    assert ("safe", "PASS") in actions
    assert [a for t, a in actions if t == "risky"] == ["DELAY", "DELAY", "RELEASE"]  # DROP off by default
    risky_decision = next(d for d in log.decisions if d.tx_id == "risky")
    assert risky_decision.with_tx["stuck_debt"] > risky_decision.without_tx["stuck_debt"]


def test_guard_drops_only_when_allowed() -> None:
    model = MarketModel(LLTV, PRICE, flat_depth(50_000))
    log = run(
        [pos("big", 100_000, 0.90)],
        model,
        [[PendingTx("r", "oracle_move", oracle_move=0.05)]],
        Policy(max_delays=1, allow_drop=True, params=Params(twap_blocks=1, latency_blocks=0)),
    )
    assert [d.action for d in log.decisions] == ["DELAY", "DROP"]
