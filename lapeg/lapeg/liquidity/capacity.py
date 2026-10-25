"""Liquidator constraints: gas cost in loan-token terms, flash-loan liquidity, and capacity per block.

- Gas: gasUsed (measured on the fork) x base fee, priced with the Chainlink ETH/USD feed. The feed address is
  resolved on-chain through ENS (`eth-usd.data.eth`), not hardcoded.
- Capital: Morpho's `liquidate` sends the seized collateral before pulling the repayment (callback), so a
  liquidator can sell inside the callback and needs no upfront capital. Morpho's own fee-free flash loans
  (its whole token balance) are reported as an additional bound.
- Capacity per block: liquidators in the same block sell into the same depth, which does not replenish within
  the block, so capacity per block = the largest single sale that is still profitable after gas.
"""

from __future__ import annotations

from dataclasses import dataclass

from web3 import Web3
from web3.types import BlockIdentifier

from lapeg.chain.abi import load_abi

ETH_USD_ENS = "eth-usd.data.eth"


@dataclass(frozen=True)
class GasPrice:
    base_fee_wei: int
    eth_usd: float
    feed: str


def namehash(name: str) -> bytes:
    """EIP-137 namehash for a plain ASCII name (no normalisation needed for these names)."""
    node = b"\x00" * 32
    for label in reversed(name.split(".")):
        node = Web3.keccak(node + Web3.keccak(text=label))
    return node


def resolve_ens(w3: Web3, name: str, block: BlockIdentifier = "latest") -> str:
    """Registry -> resolver -> addr, with the registry address and ABIs shipped in web3's ens package."""
    from ens import abis
    from ens.constants import ENS_MAINNET_ADDR

    node = namehash(name)
    registry = w3.eth.contract(address=ENS_MAINNET_ADDR, abi=abis.ENS)
    resolver = registry.functions.resolver(node).call(block_identifier=block)
    if int(resolver, 16) == 0:
        raise RuntimeError(f"ENS name {name} has no resolver")
    res = w3.eth.contract(address=resolver, abi=abis.PUBLIC_RESOLVER_2)
    addr = res.functions.addr(node).call(block_identifier=block)
    if int(addr, 16) == 0:
        raise RuntimeError(f"ENS name {name} did not resolve")
    return str(Web3.to_checksum_address(addr))


def eth_usd(w3: Web3, block: BlockIdentifier = "latest") -> tuple[float, str]:
    feed = resolve_ens(w3, ETH_USD_ENS, block)
    agg = w3.eth.contract(
        address=Web3.to_checksum_address(feed), abi=load_abi("MockAggregator")
    )  # AggregatorV3 subset
    answer = agg.functions.latestRoundData().call(block_identifier=block)[1]
    return answer / 10 ** agg.functions.decimals().call(block_identifier=block), feed


def gas_price(w3: Web3, block: int) -> GasPrice:
    price, feed = eth_usd(w3, block)
    return GasPrice(int(w3.eth.get_block(block)["baseFeePerGas"]), price, feed)


def gas_cost_usd(gas_used: int, gp: GasPrice, priority_fee_wei: int = 0) -> float:
    return gas_used * (gp.base_fee_wei + priority_fee_wei) / 1e18 * gp.eth_usd


def flash_liquidity(w3: Web3, morpho: str, token: str, block: BlockIdentifier = "latest") -> int:
    erc = w3.eth.contract(address=Web3.to_checksum_address(token), abi=load_abi("ERC20"))
    return int(erc.functions.balanceOf(Web3.to_checksum_address(morpho)).call(block_identifier=block))
