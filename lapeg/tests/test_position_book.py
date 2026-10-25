import pytest

from lapeg.market.position_book import PositionBookError, PositionEvent, apply_events

A, B = "0x000000000000000000000000000000000000000A", "0x000000000000000000000000000000000000000B"


def ev(block: int, idx: int, kind: str, acct: str, dc: int = 0, ds: int = 0) -> PositionEvent:
    return PositionEvent(block, idx, "0x", kind, acct, dc, ds)


def test_replay_in_chain_order_regardless_of_input_order() -> None:
    events = [
        ev(2, 0, "Borrow", A, ds=50),
        ev(1, 5, "SupplyCollateral", A, dc=100),
        ev(3, 1, "Repay", A, ds=-20),
        ev(3, 0, "WithdrawCollateral", A, dc=-10),
    ]
    book = apply_events(events)
    assert (book[A].collateral, book[A].borrow_shares) == (90, 30)


def test_liquidation_with_bad_debt_clears_all_shares() -> None:
    # seized all collateral; repaidShares=30 plus badDebtShares=20 removes the remaining 50 shares
    events = [ev(1, 0, "SupplyCollateral", B, dc=100), ev(1, 1, "Borrow", B, ds=50),
              ev(2, 0, "Liquidate", B, dc=-100, ds=-(30 + 20))]
    book = apply_events(events)
    assert (book[B].collateral, book[B].borrow_shares) == (0, 0)


def test_missed_event_is_detected() -> None:
    with pytest.raises(PositionBookError):
        apply_events([ev(1, 0, "WithdrawCollateral", A, dc=-1)])
