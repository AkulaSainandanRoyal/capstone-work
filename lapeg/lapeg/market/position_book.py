"""Position book: every account's collateral and borrow shares in one Morpho Blue market, rebuilt from events.

Accounting follows Morpho.sol (v1.0.0) exactly:
    SupplyCollateral(onBehalf, assets)    collateral += assets
    WithdrawCollateral(onBehalf, assets)  collateral -= assets
    Borrow(onBehalf, shares)              borrowShares += shares
    Repay(onBehalf, shares)               borrowShares -= shares
    Liquidate(borrower, ...)              collateral -= seizedAssets
                                          borrowShares -= repaidShares + badDebtShares
(badDebtShares is the remainder written off when a liquidation leaves zero collateral.)
Borrow shares do not change with interest; debt in assets is derived from them with the market totals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from web3 import Web3
from web3.contract import Contract

POSITION_EVENTS = ("SupplyCollateral", "WithdrawCollateral", "Borrow", "Repay", "Liquidate")


class PositionBookError(RuntimeError):
    pass


@dataclass(frozen=True)
class PositionEvent:
    block: int
    log_index: int
    tx_hash: str
    kind: str
    account: str
    collateral_delta: int
    borrow_shares_delta: int


@dataclass
class AccountState:
    collateral: int = 0
    borrow_shares: int = 0


def event_topics(contract: Contract) -> dict[str, str]:
    """topic0 -> event name for the position-changing events."""
    out = {}
    for name in POSITION_EVENTS:
        abi = next(e for e in cast(list[dict[str, Any]], contract.abi)
                   if e.get("type") == "event" and e.get("name") == name)
        sig = f"{name}({','.join(i['type'] for i in abi['inputs'])})"
        out["0x" + Web3.keccak(text=sig).hex().removeprefix("0x")] = name
    return out


def decode_position_events(contract: Contract, logs: list[Any]) -> list[PositionEvent]:
    topics = event_topics(contract)
    events = []
    for log in logs:
        t0 = log["topics"][0]
        name = topics.get("0x" + (t0.hex() if isinstance(t0, bytes) else t0).removeprefix("0x"))
        if name is None:
            continue
        a = getattr(contract.events, name)().process_log(log)["args"]
        if name == "SupplyCollateral":
            acct, dc, ds = a["onBehalf"], int(a["assets"]), 0
        elif name == "WithdrawCollateral":
            acct, dc, ds = a["onBehalf"], -int(a["assets"]), 0
        elif name == "Borrow":
            acct, dc, ds = a["onBehalf"], 0, int(a["shares"])
        elif name == "Repay":
            acct, dc, ds = a["onBehalf"], 0, -int(a["shares"])
        else:  # Liquidate
            acct, dc = a["borrower"], -int(a["seizedAssets"])
            ds = -(int(a["repaidShares"]) + int(a["badDebtShares"]))
        tx = log["transactionHash"]
        events.append(PositionEvent(int(log["blockNumber"]), int(log["logIndex"]),
                                    "0x" + (tx.hex() if isinstance(tx, bytes) else tx).removeprefix("0x"),
                                    name, Web3.to_checksum_address(acct), dc, ds))
    return events


def apply_events(events: list[PositionEvent]) -> dict[str, AccountState]:
    """Replay events in chain order. Raises if any balance would go negative (a missed event)."""
    book: dict[str, AccountState] = {}
    for e in sorted(events, key=lambda e: (e.block, e.log_index)):
        s = book.setdefault(e.account, AccountState())
        s.collateral += e.collateral_delta
        s.borrow_shares += e.borrow_shares_delta
        if s.collateral < 0 or s.borrow_shares < 0:
            raise PositionBookError(
                f"negative balance for {e.account} at block {e.block} log {e.log_index}: "
                f"collateral={s.collateral}, borrowShares={s.borrow_shares} (missed event?)")
    return book
