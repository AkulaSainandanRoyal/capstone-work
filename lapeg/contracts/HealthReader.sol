// SPDX-License-Identifier: GPL-2.0-or-later
pragma solidity 0.8.19;

import {IMorpho, Id, MarketParams} from "./vendor/morpho-blue/interfaces/IMorpho.sol";
import {IOracle} from "./vendor/morpho-blue/interfaces/IOracle.sol";
import {ORACLE_PRICE_SCALE} from "./vendor/morpho-blue/libraries/ConstantsLib.sol";
import {MathLib} from "./vendor/morpho-blue/libraries/MathLib.sol";
import {SharesMathLib} from "./vendor/morpho-blue/libraries/SharesMathLib.sol";
import {MorphoBalancesLib} from "./vendor/morpho-blue/libraries/periphery/MorphoBalancesLib.sol";
import {MorphoLib} from "./vendor/morpho-blue/libraries/periphery/MorphoLib.sol";

/// @notice Read-only helper: Morpho Blue's own health computation for many borrowers in one call.
/// @dev Mirrors `Morpho._isHealthy` line for line, using Morpho's libraries (vendored from v1.0.0):
///      borrowed  = borrowShares.toAssetsUp(totalBorrowAssets, totalBorrowShares)
///      maxBorrow = collateral.mulDivDown(price, ORACLE_PRICE_SCALE).wMulDown(lltv)
///      healthy  <=> maxBorrow >= borrowed
/// With `accrue`, totals include interest up to block.timestamp (MorphoBalancesLib.expectedMarketBalances),
/// which is what `liquidate` sees after `_accrueInterest`. Never deployed: injected with an eth_call state
/// override, so it has no constructor and no immutables.
contract HealthReader {
    using MathLib for uint256;
    using SharesMathLib for uint256;
    using MorphoLib for IMorpho;
    using MorphoBalancesLib for IMorpho;

    struct Account {
        uint256 collateral;
        uint256 borrowShares;
        uint256 borrowed;
        uint256 maxBorrow;
    }

    struct Snapshot {
        uint256 blockNumber;
        uint256 timestamp;
        uint256 price;
        uint256 lltv;
        uint256 totalBorrowAssets;
        uint256 totalBorrowShares;
        Account[] accounts;
    }

    function read(IMorpho morpho, Id id, address[] calldata users, bool accrue)
        external
        view
        returns (Snapshot memory s)
    {
        MarketParams memory params = morpho.idToMarketParams(id);
        if (accrue) {
            (,, s.totalBorrowAssets, s.totalBorrowShares) = morpho.expectedMarketBalances(params);
        } else {
            s.totalBorrowAssets = morpho.totalBorrowAssets(id);
            s.totalBorrowShares = morpho.totalBorrowShares(id);
        }
        s.blockNumber = block.number;
        s.timestamp = block.timestamp;
        s.price = IOracle(params.oracle).price();
        s.lltv = params.lltv;
        s.accounts = new Account[](users.length);
        for (uint256 i; i < users.length; ++i) {
            uint256 shares = morpho.borrowShares(id, users[i]);
            uint256 collateral = morpho.collateral(id, users[i]);
            s.accounts[i] = Account({
                collateral: collateral,
                borrowShares: shares,
                borrowed: shares.toAssetsUp(s.totalBorrowAssets, s.totalBorrowShares),
                maxBorrow: collateral.mulDivDown(s.price, ORACLE_PRICE_SCALE).wMulDown(params.lltv)
            });
        }
    }
}
