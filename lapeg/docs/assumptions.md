# Assumptions, divergences and findings

Everything that is assumed rather than measured, plus facts discovered on-chain that the design depends on.
Each discovered fact points to its record in `data/discovered/`.

## 1. RPC and archive access (addendum step 1)

Record: `data/discovered/archive_check_publicnode.json`, `data/discovered/archive_check_drpc.json`.

- The public endpoint used by the existing scripts (`ethereum-rpc.publicnode.com`) is **not archive**: state
  and logs older than about 128 blocks return HTTP 403 ("Archive requests require a personal token"). Anvil
  cannot fork it at an August 2026 block.
- The free public endpoint `eth.drpc.org` **served archive state** at the Aug 25, 2026 block (25828483):
  `eth_getBalance`, a Morpho `market()` call and an anvil fork at that block all worked (2026-10-22).
  Limits seen: `eth_getLogs` capped at about 100 blocks per request, intermittent HTTP 408 timeouts.
- `rpc.mevblocker.io` served historical logs with 10,000-block ranges but rate-limits (HTTP 429).
- **Decision needed:** a free public endpoint can change or disappear. For Phase 3 runs that must be
  reproducible, get a keyed archive RPC (Alchemy, Infura, drpc or similar) and set `ARCHIVE_RPC_URL`.
- Until then, experiments may set `allow_recent_block: true`, which forks a recent block on the
  non-archive fallback. Such runs record the block used but **cannot be replayed** later.

## 2. How each market's oracle prices the PT (addendum step 3)

Record: `data/discovered/oracles.json` (block 26249591 or later; values change over time).

| Market | Oracle structure | Follows the PT market price? |
|---|---|---|
| PT-reUSD-10DEC2026 | `MorphoChainlinkOracleV2` with one base feed: `OjoPTFeed = min(Pendle 15-min TWAP, 6%/yr linear discount)` | **Yes, when the TWAP is below the linear discount** (it was: 0.98519 vs 0.99206). The linear discount acts as a ceiling. 15-minute lag. |
| PT-USD3-17DEC2026 | `MorphoChainlinkOracleV2` (instance unverified, bytecode equals the verified one apart from immutables) with one base feed: a **30%/yr linear discount** | **No.** Pure function of time to maturity. |
| PT-sUSDS-26NOV2026 | Unverified failover oracle (EIP-1167 proxy). Primary: `OjoPTFeed = min(Pendle 15-min TWAP, 13%/yr linear discount)`. Backup: the same Ojo feed times Chainlink USDS/USD. Switches when the two deviate by more than 0.75%, through a challenge (16 h) and healing (24 h) timelock. | **Not currently.** The linear discount is binding (0.98779 vs TWAP 0.99505), so the TWAP only matters if the market falls below the discount curve. |

Consequences for the design:

- **Price-feedback spiral.** Possible for PT-reUSD: a market drop moves the TWAP, and with it the oracle,
  after a lag of up to 15 minutes. Not possible for PT-USD3. For PT-sUSDS, only once the market price falls
  below the 13%/yr discount curve.
- **Failure mode for PT-USD3.** Liquidations are never triggered by market moves, only by interest accrual
  or by time (the oracle rises toward 1 at maturity). If the market falls, liquidations that do trigger
  become unprofitable (S_o rises) rather than more frequent.
- **Phase 2 sanity check (G near 0 at tiny q).** Holds for PT-reUSD, whose oracle follows the TWAP. It cannot
  hold for PT-USD3 or PT-sUSDS while their linear discounts bind: those oracles sit below market by design
  (measured S_o at $100k: -3.34% and -0.83%).
- **Peg risk is not priced in the main path.** `PT_TO_ASSET` prices the PT in units of the SY's asset. No
  asset/USD feed is used for PT-reUSD or PT-USD3, nor in the sUSDS primary, so a depeg of the underlying
  does not move these oracles. It would show up only as unprofitable liquidations. (Which token is the "asset"
  for each SY has not been checked yet: open item.)
- **Oracle override (Phase 2).** The Morpho oracle's feeds are immutables (baked into its bytecode), so they
  cannot be swapped by a storage write. `OjoPTFeed` stores `FEED_1` and `FEED_2` in ordinary storage (in the
  proxy), so for PT-reUSD and the PT-sUSDS primary the cleanest override is a storage write pointing one feed at
  a mock aggregator. The fallback is replacing the Morpho oracle's code with `anvil_setCode`. Neither has been
  tried yet.

Inference method for unverified contracts: equal-length bytecode whose every differing byte run lies inside a
32-byte word equal to one of the instance's own getter values (its immutables). Evidence is stored per node
in `oracles.json` (`inference`). Getter names for the failover oracle come from the 4byte signature database,
not from verified source, and are marked `values_unverified_names`.

## 3. The Aug 25, 2026 liquidations (addendum step 4)

Record: `data/discovered/aug25_event.json` (query, per-market summary and every event).

- **Found.** Window Aug 24 to 27 UTC, blocks 25821306 to 25842829: 58 `Liquidate` events across 13 Morpho
  markets. Two are PT-reUSD-10DEC2026 markets:

  | Market | Liquidations | Borrowers | Liquidators | Repaid | Seized | Bad debt | Time (UTC) |
  |---|---|---|---|---|---|---|---|
  | PT-reUSD-10DEC2026 / USDC (`0x1e9d...fc64`, **the dataset's market**) | 16 | 13 | 3 | 35.19M USDC | 37.60M PT | 0 | Aug 25 04:37 to 04:48 (55 blocks) |
  | PT-reUSD-10DEC2026 / USDT (`0x6acd...14ca`) | 17 | 7 | 5 | 0.96M USDT | 1.03M PT | 0 | Aug 25 04:39 to 04:51 |

- The largest single liquidation in the USDC market repaid 13.01M USDC. That is close to the Layer 1
  q* for this market ($12.8M to $14.0M across the Oct 18 and 19 snapshots), measured two months later. This is
  an observation for Phase 3 to examine, not evidence of a link.
- **Not yet verified:** the YT side of the "PT/YT-reUSD" description (YT positions are not Morpho
  collateral), what triggered the liquidations, and whether liquidity on Aug 25 matched October's.
- The other two events named in the spec (Oct 2025 USDe depeg window, Mar 2026 Aave CAPO misconfiguration) have
  not been searched for yet.

## 4. Phase 0 implementation choices

- **Forking.** One anvil process per fork, started as a subprocess on a free local port. Anvil caches forked
  state under `~/.foundry/cache`. `evm_revert` consumes the snapshot it reverts to (checked by test).
- **RPC cache.** `CachingHTTPProvider` caches only immutable reads: calls pinned to a block number or hash,
  logs over a pinned range, and mined transactions and receipts. It assumes pinned blocks are final; a cached
  read of a later-reorged block would be stale. Never point it at an anvil fork.
- **Balances.** ERC20 balances are set by writing the balance mapping slot. The slot is found by probing
  (Solidity and Vyper layouts, slots 0 to 99) inside a snapshot, never hardcoded. Total supply is not
  adjusted, so supply-dependent logic sees an inconsistent total. Works for USDC and PT-reUSD (tested).
- **Acceptance mutation.** `accrueInterest` after `evm_increaseTime(3600)`, sent from an impersonated EOA,
  rather than a raw storage write to Morpho's market struct. This avoids depending on Morpho's storage layout.
- **Configs** name the RPC by environment variable, never by URL, so keys stay out of the repository.
