// SPDX-License-Identifier: GPL-2.0-or-later
pragma solidity 0.8.19;

import {Test} from "forge-std/Test.sol";
import {IMorpho, Id, Market, MarketParams} from "../contracts/vendor/morpho-blue/interfaces/IMorpho.sol";

/// Phase 0 acceptance, Solidity side: fork mainnet, read a Morpho Blue market, snapshot, mutate, revert.
/// RPC: ARCHIVE_RPC_URL, else the public non-archive fallback. Block: LAPEG_FORK_BLOCK, else latest.
/// Morpho address and market id come from data/discovered/ (written by scripts/discover_morpho.py).
contract ForkSmokeTest is Test {
    IMorpho morpho;
    Id id;

    function setUp() public {
        string memory url = vm.envOr("ARCHIVE_RPC_URL", string("https://ethereum-rpc.publicnode.com"));
        uint256 blockNumber = vm.envOr("LAPEG_FORK_BLOCK", uint256(0));
        if (blockNumber == 0) vm.createSelectFork(url);
        else vm.createSelectFork(url, blockNumber);

        morpho = IMorpho(vm.parseJsonAddress(vm.readFile("data/discovered/morpho_blue.json"), ".address"));
        id = Id.wrap(vm.parseJsonBytes32(vm.readFile("data/discovered/markets.json"), ".markets[0].market_id"));
    }

    function test_snapshotMutateRevert() public {
        MarketParams memory params = morpho.idToMarketParams(id);
        assertGt(params.lltv, 0, "market exists");
        Market memory before = morpho.market(id);

        uint256 snap = vm.snapshotState();
        vm.warp(block.timestamp + 1 hours);
        morpho.accrueInterest(params);
        Market memory mutated = morpho.market(id);
        assertGt(mutated.lastUpdate, before.lastUpdate, "accrueInterest moved lastUpdate");

        assertTrue(vm.revertToState(snap), "revert succeeded");
        Market memory restored = morpho.market(id);
        assertEq(restored.lastUpdate, before.lastUpdate);
        assertEq(restored.totalBorrowAssets, before.totalBorrowAssets);
        assertEq(restored.totalSupplyAssets, before.totalSupplyAssets);
        assertEq(restored.totalBorrowShares, before.totalBorrowShares);
        assertEq(restored.totalSupplyShares, before.totalSupplyShares);
    }
}
