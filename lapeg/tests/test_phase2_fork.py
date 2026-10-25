"""Phase 2 building blocks on the pinned fork block (no live API needed)."""

import json

import pytest
from web3 import Web3

from lapeg import PROJECT_ROOT
from lapeg.chain.abi import load_abi
from lapeg.chain.morpho import MorphoBlue
from lapeg.fork.anvil import AnvilFork
from lapeg.liquidity.capacity import flash_liquidity, gas_price
from lapeg.liquidity.execute import sell_pt_for_sy
from lapeg.metrics.illiquidity import ORACLE_PRICE_SCALE
from lapeg.oracle.override import MOCK_ADDRESS, override_ojo_feed

pytestmark = pytest.mark.fork

D = PROJECT_ROOT / "data" / "discovered"
MARKETS = json.loads((D / "markets.json").read_text())["markets"]
REUSD = next(m for m in MARKETS if m["name"] == "PT-reUSD-10DEC2026")
TREE = json.loads((D / "oracles.json").read_text(encoding="utf-8"))["markets"]["PT-reUSD-10DEC2026"]["tree"]
OJO = TREE["children"]["BASE_FEED_1"]["address"]
PENDLE_MARKET = TREE["children"]["BASE_FEED_1"]["children"]["FEED_1"]["children"]["market"]["address"]
ROUTER = json.loads((D / "pendle_router.json").read_text())["router"]   # scripts/discover_pendle_router.py


def test_oracle_override_is_exact_and_reverts(fork: AnvilFork, morpho: MorphoBlue) -> None:
    before = morpho.oracle_price(REUSD["oracle"])
    with fork.branch():
        ov = override_ojo_feed(fork, OJO, 95 * 10**16)
        assert ov.mock == MOCK_ADDRESS and set(ov.feed_slots) == {"FEED_1", "FEED_2"}
        assert morpho.oracle_price(REUSD["oracle"]) == 95 * 10**16 * 10**18   # SCALE_FACTOR 1e18 x answer
    assert morpho.oracle_price(REUSD["oracle"]) == before


def test_pendle_leg_sells_pt_for_sy(fork: AnvilFork, morpho: MorphoBlue) -> None:
    assert fork.w3 is not None
    mk = fork.w3.eth.contract(address=Web3.to_checksum_address(PENDLE_MARKET), abi=load_abi("PendleMarket"))
    sy, mpt, _ = mk.functions.readTokens().call()
    assert mpt.lower() == REUSD["collateral_token"].lower()
    rate = fork.w3.eth.contract(address=sy, abi=load_abi("PendleSY")).functions.exchangeRate().call()
    seller = Web3.to_checksum_address(Web3.keccak(text="test-seller")[-20:])
    amount = 1_000 * 10**6
    ex = sell_pt_for_sy(fork, ROUTER, PENDLE_MARKET, mpt, sy, amount, seller)
    assert ex.status == "ok" and ex.amount_out > 0
    price = morpho.oracle_price(REUSD["oracle"])
    g_leg = 1 - (ex.amount_out * rate / 1e18) * ORACLE_PRICE_SCALE / (amount * price)
    assert abs(g_leg) < 0.01      # a 1,000 PT sale through the Pendle pool is within 1% of the oracle


def test_gas_and_flash_liquidity(fork: AnvilFork, upstream: tuple[str, int], morpho: MorphoBlue) -> None:
    assert fork.w3 is not None
    gp = gas_price(fork.w3, upstream[1])
    assert gp.eth_usd > 100 and gp.base_fee_wei > 0
    assert len(fork.w3.eth.get_code(Web3.to_checksum_address(gp.feed))) > 0
    assert flash_liquidity(fork.w3, morpho.address, REUSD["loan_token"]) > 0
