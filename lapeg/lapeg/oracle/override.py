"""Force a Morpho oracle's price on a fork, independently of DEX prices.

The Morpho oracle (MorphoChainlinkOracleV2) keeps its feeds as immutables, so they cannot be swapped by a
storage write. For PT-reUSD its base feed is an OjoPTFeed proxy, which keeps FEED_1 and FEED_2 in ordinary
storage and returns min(FEED_1, FEED_2). Pointing both at a MockAggregator (installed with anvil_setCode)
makes the Morpho oracle return SCALE_FACTOR * mockAnswer exactly. Storage slots are found by matching the
current feed addresses, never hardcoded. Use inside `fork.branch()` to undo.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from importlib import resources

from eth_utils import keccak
from web3 import Web3

from lapeg.chain.abi import load_abi
from lapeg.fork.anvil import AnvilFork

MOCK_ADDRESS = Web3.to_checksum_address(keccak(b"lapeg.MockAggregator")[-20:])


@cache
def mock_runtime_code() -> str:
    return resources.files("lapeg.chain").joinpath("bytecode", "MockAggregator.hex").read_text().strip()


@dataclass(frozen=True)
class OjoOverride:
    ojo_feed: str
    feed_slots: dict[str, int]      # "FEED_1"/"FEED_2" -> storage slot in the Ojo proxy
    original_feeds: dict[str, str]
    mock: str


def find_address_slot(fork: AnvilFork, contract: str, target: str, max_slot: int = 32) -> int:
    """First storage slot whose word is exactly `target` (an address stored alone in its slot)."""
    want = int(target, 16)
    for slot in range(max_slot):
        if fork.get_storage(contract, slot) == want:
            return slot
    raise RuntimeError(f"{target} not found in the first {max_slot} storage slots of {contract}")


def set_mock_answer(fork: AnvilFork, answer: int) -> None:
    """Set the mock feed's answer (18 decimals). Negative values are stored in two's complement."""
    fork.set_storage(MOCK_ADDRESS, 0, answer % 2**256)


def override_ojo_feed(fork: AnvilFork, ojo_feed: str, answer: int) -> OjoOverride:
    """Point both feeds of an OjoPTFeed at a mock returning `answer`."""
    assert fork.w3 is not None
    ojo = fork.w3.eth.contract(address=Web3.to_checksum_address(ojo_feed), abi=load_abi("OjoPTFeed"))
    originals = {"FEED_1": ojo.functions.FEED_1().call(), "FEED_2": ojo.functions.FEED_2().call()}
    slots = {name: find_address_slot(fork, ojo_feed, addr) for name, addr in originals.items()}
    fork.set_code(MOCK_ADDRESS, mock_runtime_code())
    set_mock_answer(fork, answer)
    for slot in slots.values():
        fork.set_storage(ojo_feed, slot, int(MOCK_ADDRESS, 16))
    for name in originals:
        if getattr(ojo.functions, name)().call() != MOCK_ADDRESS:
            raise RuntimeError(f"override of {name} did not take effect")
    return OjoOverride(Web3.to_checksum_address(ojo_feed), slots, originals, MOCK_ADDRESS)
