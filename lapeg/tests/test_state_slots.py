from web3 import Web3

from lapeg.fork.state import mapping_slot

HOLDER = "0x000000000000000000000000000000000000dEaD"


def test_solidity_mapping_slot_matches_abi_encoding() -> None:
    expected = Web3.solidity_keccak(["uint256", "uint256"], [int(HOLDER, 16), 9])
    assert mapping_slot(HOLDER, 9, "solidity") == int.from_bytes(expected, "big")


def test_vyper_layout_swaps_key_and_index() -> None:
    expected = Web3.solidity_keccak(["uint256", "uint256"], [3, int(HOLDER, 16)])
    assert mapping_slot(HOLDER, 3, "vyper") == int.from_bytes(expected, "big")
    assert mapping_slot(HOLDER, 3, "vyper") != mapping_slot(HOLDER, 3, "solidity")
