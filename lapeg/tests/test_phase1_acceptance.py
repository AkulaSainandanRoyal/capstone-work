"""Phase 1 acceptance on the pinned block. The first run fetches every event of the market (minutes);
later runs read them from the local RPC cache."""

import pytest

from lapeg import PROJECT_ROOT
from lapeg.config import load_experiment
from lapeg.market.experiment import run_position_book

pytestmark = [pytest.mark.fork, pytest.mark.slow]


def test_position_book_matches_morpho() -> None:
    cfg = load_experiment(PROJECT_ROOT / "experiments" / "phase1_position_book.yaml")
    report = run_position_book(cfg, write_results=False)
    assert report["checks"] == {k: True for k in report["checks"]}, report["checks"]
    assert report["max_hf_rel_error"] <= 1e-9
    df = report["_frame"]
    assert list(df.columns[:6]) == ["market_id", "block", "borrower", "collateral", "debt", "health_factor"]
    assert df["borrower"].is_unique
