# Design: Phases 4 to 7

What the shortened scope (v0) built, what the full spec still requires, and how each will be accepted.
Phase 3 has its own document (`phase3_design.md`).

## Phase 4: cascade predictor

**Built (v0): the fast tier** (`lapeg/cascade/fast.py`). It is an iterative estimator that runs in
milliseconds, with no fork. Each block:

1. The oracle updates as the lower of the Pendle TWAP (a moving average of the market price over 75 blocks)
   and the linear-discount ceiling.
2. Morpho's rule (`maxBorrow < borrowed`, integer math) gives the liquidatable set.
3. Liquidators act after a latency, largest position first. Each seizes `min(c, debt * LIF / P_o)` and sells it
   into the measured depth curve *after* everything already sold.
4. A liquidation is skipped if the sale is beyond the curve (refusal) or unprofitable after gas. That position
   is *stuck*.

The run stops at a fixed point or at the horizon. Inputs are all measured: the position book (Phase 1), the
executed depth curve and gas (Phase 2), and the oracle structure.

**Checked so far:**
- Unit tests: profitable liquidation, refusal, an unprofitable sale left stuck, TWAP lag, and a two-step cascade
  where one liquidation's sale triggers the next.
- On measured data: with no feedback, the fast tier must reproduce the liquidatable sets Morpho itself reported
  under the oracle override, at every shock (`phase45_cascade_guard`).

**Still required (full spec):**
- **Exact tier:** the Phase 3 agents run on the fork, which is slow but serves as ground truth.
- **Fast vs exact comparison** on at least 200 (state, transaction list) pairs drawn from historical blocks and
  synthetic shocks: precision and recall for "cascade above threshold", error on liquidated value, and latency
  of each tier. This is the Phase 4 acceptance test.

**Known simplifications of the fast tier:**
- The TWAP is an arithmetic moving average of price. Pendle's is time-weighted on ln(implied rate).
- Depth does not refill unless `replenish_per_block > 0`; arbitrage is a Phase 3 agent.
- One liquidator: no competition and no gas auctions.

## Phase 5: guard and policy

**Built (v0): guard v0** (`lapeg/guard/guard.py`).
- For each pending transaction, the fast tier runs with and without it. Risk is the stuck debt and bad debt the
  transaction *adds*.
- Within the threshold, the transaction gets PASS. Above it, DELAY by one block and re-evaluate. After `K`
  delays it is dropped only if the policy allows DROP (off by default, per the spec); otherwise it is released and
  flagged.
- Every decision logs the action, the reason, metrics with and without the transaction (the counterfactual),
  the number of delays, and the latency.

**v0 limits:**
- State is held fixed across blocks, so DELAY demonstrates the policy mechanics, not market recovery.
- Transactions are modelled by their effect (PT sold, or an oracle move), not by their calldata.
- There is no exact-tier confirmation.
- The simulator is not validated (Phase 3 gate). Decisions demonstrate the architecture, not effectiveness.

**Full design:**
1. **Sidecar loop:** take the pending set for block N+1 (in replay, the real block's transactions plus injected
   ones), run the fast predictor, confirm flagged orderings with the exact tier, then search for a safe order.
2. **Minimal culprit set:** leave-one-out over the flagged block, then greedy minimisation, to find the
   transactions whose removal eliminates the risk.
3. **Reorder search:** non-culprit transactions stay in place and culprits move. Heuristics: oracle updates and
   arbitrage first, liquidations spread across blocks, risk-increasing trades last. The search is bounded by a time
   budget that fits a 12 s L1 block (or 2 s on an L2), and over-budget cases are reported.
4. **DELAY** to the next block, then **DROP** only after `K` delays and only if enabled.
5. **Policy config:** risk threshold, horizon `H`, max delays `K`, DROP on or off, and per-collateral thresholds
   keyed to the illiquidity metric (`lapeg/metrics/README.md`).
6. **Censorship:** every DELAY and DROP is logged with the transaction, its delay and the counterfactual. DROP
   stays off by default.

## Phase 6: evaluation harness

All scenarios are driven by YAML, with pinned blocks.

| Scenario | Source |
|---|---|
| Aug 25, 2026 replay | `data/discovered/aug25_event.json` (located) |
| Oct 2025 USDe depeg window | to locate in `Liquidate` logs of USDe and sUSDe markets |
| Mar 2026 Aave CAPO misconfiguration | to locate on-chain (not verified yet) |
| False positives | at least 1,000 random normal blocks in the target markets |
| Synthetic shock sweeps | sale size `C` and oracle `Δ`, guard on and off |

**Per-scenario metrics:**
- cascade size, bad debt and amplification ratio, guard on vs off;
- `C*` with and without the guard;
- false-positive rate;
- delay distribution (count, blocks, value);
- p50 and p99 latency.

**Baselines** (protocol parameter changes, no guard): lower LLTV, a higher liquidation incentive, a TWAP oracle,
a liquidity-aware supply cap (for example, supply capped so that `B(Δ) ≤ 1` at a chosen shock), and halting
liquidations above an LTV (the "Toxic Liquidation Spirals" rule, arXiv 2212.07306, citation still to verify).

**Plots:** depth curves, `G(q)` over time through each event, cascade timelines with the guard on and off,
`C*` vs mitigation, and the latency CDF. Each run writes `results/summary.md`.

## Phase 7: generalisation

- **Adapters:** Aave v3 and Euler v2 behind the same interface as Morpho (positions, health, liquidation
  parameters). Phase 1's Morpho work defines the interface.
- **Other collateral:** run Phases 2 to 6 on tokenised RWA collateral markets where they exist, discovered on-chain
  or from the protocols' official market lists, with the source recorded.
- **Comparison across collateral types:** how the illiquidity metric differs for PT, LRT and RWA collateral.
  Phase 2 already shows the oracle design (TWAP vs fixed discount) decides the failure mode, so the comparison
  must be reported per oracle type, not only per asset type.
