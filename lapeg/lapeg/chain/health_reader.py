"""Call contracts/HealthReader.sol (Morpho's own health computation) through an eth_call state override.

The helper is never deployed: its runtime bytecode is placed at a fixed throwaway address for the duration
of the call, so reads at the fork block see exactly that block's state.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from importlib import resources

from eth_utils import keccak
from hexbytes import HexBytes
from web3 import Web3
from web3.types import BlockIdentifier

from lapeg.chain.abi import load_abi

READER_ADDRESS = Web3.to_checksum_address(keccak(b"lapeg.HealthReader")[-20:])


@cache
def runtime_code() -> str:
    return resources.files("lapeg.chain").joinpath("bytecode", "HealthReader.hex").read_text().strip()


@dataclass(frozen=True)
class AccountHealth:
    collateral: int
    borrow_shares: int
    borrowed: int
    max_borrow: int


@dataclass(frozen=True)
class HealthSnapshot:
    block_number: int
    timestamp: int
    price: int
    lltv: int
    total_borrow_assets: int
    total_borrow_shares: int
    accounts: dict[str, AccountHealth]


def read_health(w3: Web3, morpho: str, market_id: str, users: list[str], *, accrue: bool = True,
                block: BlockIdentifier = "latest", batch: int = 200) -> HealthSnapshot:
    reader = w3.eth.contract(address=READER_ADDRESS, abi=load_abi("HealthReader"))
    override = {READER_ADDRESS: {"code": runtime_code()}}
    header: tuple[int, ...] | None = None
    accounts: dict[str, AccountHealth] = {}
    users = [Web3.to_checksum_address(u) for u in users]
    for i in range(0, max(len(users), 1), batch):
        part = users[i:i + batch]
        r = reader.functions.read(Web3.to_checksum_address(morpho), HexBytes(market_id), part, accrue).call(
            block_identifier=block, state_override=override)  # type: ignore[arg-type]
        h = tuple(int(x) for x in r[:6])
        if header is not None and h != header:
            raise RuntimeError("market totals or price changed between batches; pin the block")
        header = h
        for u, a in zip(part, r[6], strict=True):
            accounts[u] = AccountHealth(*(int(x) for x in a))
    assert header is not None
    bn, ts, price, lltv, tba, tbs = header
    return HealthSnapshot(bn, ts, price, lltv, tba, tbs, accounts)
