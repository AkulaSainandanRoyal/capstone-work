# Interfaces

Interfaces LAPEG calls, taken from verified sources. Nothing here is written from memory: each section names
its source, and addresses come from `data/discovered/`.

## Morpho Blue core

Source: `morpho-org/morpho-blue` release `v1.0.0`, commit `55d2d99304fb3fb930c688462ae2ccabb1d533ad`, vendored
unchanged in `contracts/vendor/morpho-blue/` (blob hashes in `SOURCE.md`). ABI: `lapeg/chain/abis/Morpho.json`,
compiled from those files by `scripts/build_abis.py`.

Address: `data/discovered/morpho_blue.json` (Morpho GraphQL API, then verified on-chain: has code, and
`idToMarketParams` matches the capstone dataset for all three markets).

```solidity
type Id is bytes32;
struct MarketParams { address loanToken; address collateralToken; address oracle; address irm; uint256 lltv; }
struct Market   { uint128 totalSupplyAssets; uint128 totalSupplyShares; uint128 totalBorrowAssets;
                  uint128 totalBorrowShares; uint128 lastUpdate; uint128 fee; }
struct Position { uint256 supplyShares; uint128 borrowShares; uint128 collateral; }

function idToMarketParams(Id id) external view returns (MarketParams memory);
function market(Id id) external view returns (Market memory m);
function position(Id id, address user) external view returns (Position memory p);
function accrueInterest(MarketParams memory marketParams) external;
function liquidate(MarketParams memory marketParams, address borrower, uint256 seizedAssets,
                   uint256 repaidShares, bytes memory data) external returns (uint256, uint256);
```

Notes from the source comments:

- `market()` totals and `position()` shares exclude interest accrued since `lastUpdate`. Call `accrueInterest`
  (or replicate the IRM) before comparing debt to collateral.
- `liquidate`: pass exactly one of `seizedAssets` or `repaidShares` as non-zero. Seizing more than the
  collateral, or repaying more than the debt, reverts without a message. A small front-running repay can make a
  liquidation revert.
- `lltv` is WAD-scaled (`915000000000000000` = 91.5%).

Events used for the position book (Phase 1) and event discovery (`libraries/EventsLib.sol`):

```solidity
event Borrow(Id indexed id, address caller, address indexed onBehalf, address indexed receiver, uint256 assets, uint256 shares);
event Repay(Id indexed id, address indexed caller, address indexed onBehalf, uint256 assets, uint256 shares);
event SupplyCollateral(Id indexed id, address indexed caller, address indexed onBehalf, uint256 assets);
event WithdrawCollateral(Id indexed id, address caller, address indexed onBehalf, address indexed receiver, uint256 assets);
event Liquidate(Id indexed id, address indexed caller, address indexed borrower, uint256 repaidAssets,
                uint256 repaidShares, uint256 seizedAssets, uint256 badDebtAssets, uint256 badDebtShares);
event AccrueInterest(Id indexed id, uint256 prevBorrowRate, uint256 interest, uint256 feeShares);
```

`Liquidate` topic0 = `keccak256("Liquidate(bytes32,address,address,uint256,uint256,uint256,uint256,uint256)")`
= `0xa4946ede45d0c6f06a0f5ce92c9ad3b4751452d2fe0e25010783bcab57a67e41` (checked with `cast keccak`).

## Morpho oracle interface

Source: `src/interfaces/IOracle.sol`, same commit.

```solidity
function price() external view returns (uint256);
```

The price of 1 collateral asset in loan asset, scaled by `1e(36 + loanDecimals - collateralDecimals)`.
For the 6-decimal PTs against USDC the scale is `1e36`; for the 18-decimal PT-sUSDS it is `1e24`.

## Oracle building blocks used by the three markets

All verified on Sourcify unless marked otherwise. Full trees with live values: `data/discovered/oracles.json`.

| Contract | Price it returns | Key parameters |
|---|---|---|
| `MorphoChainlinkOracleV2` | `SCALE_FACTOR * (baseVault * baseFeed1 * baseFeed2) / (quoteVault * quoteFeed1 * quoteFeed2)` | feeds and vaults are immutables; unused ones are `address(0)` and count as 1 |
| `OjoPTFeed` (behind EIP-1167 proxies) | `min(FEED_1, FEED_2)` from `latestRoundData` | reverts if either feed is staler than 24 h |
| `PendleChainlinkOracle` | Pendle market TWAP: `PendlePYOracleLib.getPtToAssetRate(market, twapDuration)` for `baseOracleType = 1` (`PT_TO_ASSET`) | `market`, `twapDuration` (900 s in all three markets) |
| `PendleSparkLinearDiscountOracle` | `1 - baseDiscountPerYear * timeLeft / 365 days` (18 decimals) | `PT`, `maturity`, `baseDiscountPerYear` |
| `ChainlinkCurrentTimestampAdapter`, `PendleLinearDiscountOracleWrapper` | inner oracle's answer, with `updatedAt = block.timestamp` | `innerOracle` |

`PendleOracleType` enum (from `IPChainlinkOracle.sol`): `PT_TO_SY = 0, PT_TO_ASSET = 1, LP_TO_SY = 2, LP_TO_ASSET = 3`.

`PendlePYOracleLib.getPtToAssetRate` (Pendle's library, compiled into `PendleChainlinkOracle`) derives the PT
price from the market's time-weighted ln(implied rate) over `duration`, returns exactly 1 after expiry, and
scales down by `syIndex / pyIndex` if the SY exchange rate has fallen (insolvency guard). The markets do not
call a separate `PendlePYLpOracle` contract; the spec's reference to it is covered by this library.
