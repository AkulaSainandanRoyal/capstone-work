"""Storage-level helpers: locate and overwrite ERC20 balances on a fork.

Balance slots differ per token and are never hardcoded: `find_balance_slot` probes candidate slots
(Solidity and Vyper mapping layouts) by writing a sentinel and checking `balanceOf`, inside a snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from eth_utils import keccak
from web3 import Web3

from lapeg.chain.abi import load_abi
from lapeg.fork.anvil import AnvilFork

Layout = Literal["solidity", "vyper"]
PROBE_SENTINEL = 0x1A2B3C4D5E6F7081  # unlikely to be anyone's real balance


class BalanceSlotNotFound(RuntimeError):
    pass


@dataclass(frozen=True)
class BalanceSlot:
    token: str
    index: int  # the mapping's declared slot
    layout: Layout

    def slot_for(self, holder: str) -> int:
        return mapping_slot(holder, self.index, self.layout)


def mapping_slot(key: str, index: int, layout: Layout = "solidity") -> int:
    """Storage slot of mapping[key] for a mapping declared at `index`."""
    k = int(key, 16).to_bytes(32, "big")
    i = index.to_bytes(32, "big")
    return int.from_bytes(keccak(k + i) if layout == "solidity" else keccak(i + k), "big")


def balance_of(fork: AnvilFork, token: str, holder: str) -> int:
    assert fork.w3 is not None
    erc20 = fork.w3.eth.contract(address=Web3.to_checksum_address(token), abi=load_abi("ERC20"))
    return int(erc20.functions.balanceOf(Web3.to_checksum_address(holder)).call())


def find_balance_slot(
    fork: AnvilFork,
    token: str,
    max_index: int = 100,
    probe_holder: str = "0x000000000000000000000000000000000000dEaD",
) -> BalanceSlot:
    """Find where `token` stores balances. State is restored afterwards."""
    with fork.branch():
        for index in range(max_index):
            for layout in ("solidity", "vyper"):
                slot = mapping_slot(probe_holder, index, layout)  # type: ignore[arg-type]
                original = fork.get_storage(token, slot)
                fork.set_storage(token, slot, PROBE_SENTINEL)
                if balance_of(fork, token, probe_holder) == PROBE_SENTINEL:
                    return BalanceSlot(Web3.to_checksum_address(token), index, layout)  # type: ignore[arg-type]
                fork.set_storage(token, slot, original)
    raise BalanceSlotNotFound(f"no balance mapping found for {token} in slots 0..{max_index - 1}")


def nested_mapping_slot(outer_key: str, inner_key: str, index: int, layout: Layout = "solidity") -> int:
    """Storage slot of mapping[outer_key][inner_key] for a nested mapping declared at `index`."""
    inner = mapping_slot(outer_key, index, layout)
    k = int(inner_key, 16).to_bytes(32, "big")
    s = inner.to_bytes(32, "big")
    return int.from_bytes(keccak(k + s) if layout == "solidity" else keccak(s + k), "big")


def find_allowance_index(
    fork: AnvilFork,
    token: str,
    max_index: int = 100,
    owner: str = "0x000000000000000000000000000000000000dEaD",
    spender: str = "0x000000000000000000000000000000000000bEEF",
) -> tuple[int, Layout]:
    """Where `token` stores allowances (owner -> spender -> amount). State is restored afterwards."""
    assert fork.w3 is not None
    erc = fork.w3.eth.contract(address=Web3.to_checksum_address(token), abi=load_abi("ERC20"))
    o, s = Web3.to_checksum_address(owner), Web3.to_checksum_address(spender)
    with fork.branch():
        for index in range(max_index):
            for layout in ("solidity", "vyper"):
                slot = nested_mapping_slot(o, s, index, layout)  # type: ignore[arg-type]
                fork.set_storage(token, slot, PROBE_SENTINEL)
                if erc.functions.allowance(o, s).call() == PROBE_SENTINEL:
                    return index, layout  # type: ignore[return-value]
    raise BalanceSlotNotFound(f"no allowance mapping found for {token} in slots 0..{max_index - 1}")


def set_erc20_balance(
    fork: AnvilFork, token: str, holder: str, amount: int, slot: BalanceSlot | None = None
) -> BalanceSlot:
    """Set `holder`'s balance of `token` to `amount` (raw units). Total supply is not adjusted."""
    slot = slot or find_balance_slot(fork, token)
    fork.set_storage(token, slot.slot_for(holder), amount)
    got = balance_of(fork, token, holder)
    if got != amount:
        raise RuntimeError(f"balance write did not take effect: balanceOf={got}, wanted {amount}")
    return slot
