"""Read-only Morpho Blue adapter (views from IMorpho, Morpho Blue v1.0.0).

The Morpho Blue address is not hardcoded: it is read from data/discovered/morpho_blue.json, written by
scripts/discover_morpho.py together with the query and on-chain checks used to find it.
"""

from __future__ import annotations

import json
from dataclasses import astuple, dataclass
from pathlib import Path
from typing import Any

from eth_typing import ChecksumAddress
from hexbytes import HexBytes
from web3 import Web3
from web3.types import BlockIdentifier

from lapeg.chain.abi import load_abi

BlockId = BlockIdentifier


@dataclass(frozen=True)
class MarketParams:
    loan_token: ChecksumAddress
    collateral_token: ChecksumAddress
    oracle: ChecksumAddress
    irm: ChecksumAddress
    lltv: int   # WAD (1e18 = 100%)

    def as_tuple(self) -> tuple[Any, ...]:
        return astuple(self)


@dataclass(frozen=True)
class MarketState:
    total_supply_assets: int
    total_supply_shares: int
    total_borrow_assets: int
    total_borrow_shares: int
    last_update: int
    fee: int


@dataclass(frozen=True)
class Position:
    supply_shares: int
    borrow_shares: int
    collateral: int


def load_morpho_address(discovery_file: str | Path) -> ChecksumAddress:
    with open(discovery_file, encoding="utf-8") as f:
        return Web3.to_checksum_address(json.load(f)["address"])


class MorphoBlue:
    def __init__(self, w3: Web3, address: str) -> None:
        self.w3 = w3
        self.address = Web3.to_checksum_address(address)
        self.contract = w3.eth.contract(address=self.address, abi=load_abi("Morpho"))

    @staticmethod
    def _id(market_id: str) -> HexBytes:
        return HexBytes(market_id)

    def market_params(self, market_id: str, block: BlockId = "latest") -> MarketParams:
        r = self.contract.functions.idToMarketParams(self._id(market_id)).call(block_identifier=block)
        loan, collateral, oracle, irm = (Web3.to_checksum_address(x) for x in r[:4])
        return MarketParams(loan, collateral, oracle, irm, int(r[4]))

    def market(self, market_id: str, block: BlockId = "latest") -> MarketState:
        r = self.contract.functions.market(self._id(market_id)).call(block_identifier=block)
        return MarketState(*(int(x) for x in r))

    def position(self, market_id: str, user: str, block: BlockId = "latest") -> Position:
        r = self.contract.functions.position(self._id(market_id), Web3.to_checksum_address(user)).call(
            block_identifier=block)
        return Position(*(int(x) for x in r))

    def oracle_price(self, oracle: str, block: BlockId = "latest") -> int:
        """Raw IOracle.price(): scaled by 1e(36 + loan decimals - collateral decimals)."""
        c = self.w3.eth.contract(address=Web3.to_checksum_address(oracle), abi=load_abi("Oracle"))
        return int(c.functions.price().call(block_identifier=block))
