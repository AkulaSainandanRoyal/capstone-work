# Phase 3 design: cascade simulator, calibration and validation

Status: **design** (v0 scope), with event discovery done and calibration started from on-chain data.
The full build is the first step after Review 2. Section 6 lists what is already measured.

## 1. Purpose

Phase 3 answers: *given real chain state and a shock, how do liquidators, arbitrageurs and the oracle actually
behave over the next blocks, and does a simulation of that match what happened on Aug 25, 2026?* It is the
spec's validation gate: the guard (Phases 4 and 5) must not be tuned against an unvalidated simulator.

## 2. Agents

All agents act through real contracts on the fork (Morpho `liquidate`, Pendle router, aggregator routes); no
protocol logic is reimplemented.

| Agent | State it reads | Action each block | Parameters (to calibrate) |
|---|---|---|---|
| **Liquidator** (one per real liquidator identity) | Position book, Morpho oracle price, depth curve | Liquidate positions with `HF < 1`, largest expected profit first; sell the seized PT on the best route; stop when the next liquidation would be unprofitable after gas | Profit threshold, gas budget (priority fee), latency in blocks after `HF` crosses 1, capital or flash-loan limit, max sale size per block |
| **Arbitrageur** | Pendle market implied rate vs PT fundamental (SY exchange rate discounted to maturity), DEX prices of the underlying | Buy PT (or the underlying) when it trades below fundamental by more than its cost, which refills depth | Reaction lag (blocks), size per block, threshold |
| **Shock agent** | n/a | Injects a trade of size $C$ (e.g. PT sold into the Pendle market) or a direct price move | $C$, timing |
| **Oracle** (not an agent) | Pendle market TWAP (15 min) and the 6%/yr linear discount | Read only: the PT-reUSD oracle is `min(TWAP, linear)` (see `assumptions.md`) | None: real contracts |

**Feedback loop.** Shock, then lower Pendle price, then (after TWAP lag) lower oracle, then positions with
`HF < 1`, then liquidations, then seized PT sold into the same depth, then lower price again. The loop's speed is
set by the TWAP window (900 s) and by liquidator latency; its size by the depth curve and the backlog ratio
$B(\Delta)$ from Phase 2.

## 3. Calibration from historical `Liquidate` events

Target market history contains exactly 16 liquidations, all on Aug 25, 2026 (`data/discovered/aug25_event.json`):

| Quantity | Method | Status |
|---|---|---|
| Identity concentration | Share of liquidations and repaid value per `caller` | From events (section 6) |
| Size distribution | Repaid assets and seized collateral per liquidation | From events (section 6) |
| Response latency | For each liquidated borrower, the first block where `HF < 1` (binary search with `HealthReader` at historical blocks), minus the liquidation block | To do: needs about 15 archive reads per borrower |
| Realized execution | What each liquidator received for the seized PT (receipt logs, or a local trace of the replayed transaction), giving the realized $G$ at the actual liquidation sizes | To do. This is the spec's headline number: $G$ at the actual liquidation sizes |

## 4. Validation: Aug 25 replay

1. **Locate the trigger.** Scan Pendle market `Swap` events (and the oracle's TWAP) in the hours before 04:37 UTC
   to find what moved the oracle. Record the block range and trades in `data/discovered/`.
2. **Fork the block before the triggering trades.** Archive state for Aug 25 is available on the free endpoint
   (anvil forks at block 25828483 were tested).
3. **Run the agents** with calibrated parameters, replaying the real triggering trades as the shock.
4. **Compare** simulated against actual: number of liquidations (16), total repaid value (35.19M USDC), timeline
   (11 minutes, 55 blocks), bad debt (0), and the amplification ratio (liquidated value / triggering capital).
5. **Report the error** on each. If it is large, diagnose and recalibrate before moving on (spec gate).

## 5. Capital-to-spiral search

Find the minimum shock $C^*$ (PT sold into the Pendle market) that produces a cascade above a threshold (for
example 10% of borrow liquidated, or any bad debt). Bisection on $C$, each trial on a fresh snapshot. Output
$C^*$, the amplification ratio, and the resulting bad debt. Phase 2's $\Delta^*$ is the static (one-step)
analogue: it ignores the feedback loop and liquidator latency.

## 6. Already measured

- **Event discovery:** the Aug 25 event is located in the target market (`aug25_event.json`): 16 liquidations,
  13 borrowers, 3 liquidator addresses, 35.19M USDC repaid, 37.60M PT seized, no bad debt, 04:37 to 04:48 UTC,
  16 transactions in 16 blocks.
- **Archive access** for that date (`archive_check_drpc.json`).
- **Depth, oracle override, gas and capacity** at the current block (Phase 2), which give the agents' inputs.

## 7. Risks

- **Liquidity on Aug 25 may differ from today**: the replay must use Aug 25 state, which the archive fork gives,
  but the aggregator routes cannot be quoted for that date. The replay needs either on-chain routes (Pendle
  market plus the venues found in the route trace) or the liquidators' own executed paths.
- **Private order flow and builder behaviour** are not visible; recorded as divergences in `assumptions.md`.
- **Three liquidator identities** are a small sample for calibration; parameters will carry wide uncertainty.
