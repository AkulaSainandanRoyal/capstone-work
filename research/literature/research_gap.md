# Provisional Research Gap

## Project focus

The capstone studies illiquidity in collateral-based DeFi lending, with the broad original scope including lending protocols and tokenised/yield-bearing collateral. The current implementation notes focus more narrowly on three Morpho Blue Pendle PT markets and a Liquidity-Aware Pre-Execution Guard (LAPEG). Keep these scopes distinct in the final report.

## What the first seven papers cover

The first batch provides:
- General DeFi architecture, applications and composability.
- Financial-stability risks such as leverage, liquidity mismatch and interconnectedness.
- Risk frameworks for stablecoins and collateral.
- Conceptual models of deleveraging spirals and feedback.

## What remains unaddressed in this batch

The first seven papers do not directly demonstrate a combined empirical pipeline that measures executable PT sale capacity by size, compares it with oracle values, estimates liquidation demand under shocks, models eligible liquidator capacity, and evaluates mitigation policies through historical replay.

## Candidate research gap

A candidate gap is the integration of **market execution capacity and liquidation mechanics** into a reproducible evaluation of collateral illiquidity. Rather than treating oracle prices as sufficient proxies for sale proceeds, the project can measure how executable prices and route capacity vary with trade size and timing, then test whether a pre-execution guard reduces unprofitable liquidation attempts or adverse feedback relative to a fixed-parameter baseline.

## Research-question mapping

- RQ1: measure oracle-versus-executable price by trade size and estimate cost-to-liquidate.
- RQ2: examine whether execution risk changes as PTs approach maturity.
- RQ3: test whether liquidity and liquidation pressure move across maturity rollovers.
- RQ4: compare liquidation demand with actual eligible execution/redemption capacity.
- RQ5: replay events under alternative oracle/parameter/liquidation policies and report comparable outcomes.

## Evidence and limitations

This gap is **provisional and based only on the first seven supplied PDFs**. It is not evidence that no prior work exists. A full literature search should include empirical DeFi liquidation studies, oracle manipulation and TWAP studies, AMM execution/slippage models, Morpho/Aave/Euler protocol documentation, Pendle PT market research, and liquidation mechanism papers.

The implementation should not claim LAPEG prevents cascades unless the replay has been validated against a baseline and the results support that claim. Report limitations such as gas/capital costs, route reverts, snapshot timing, and the distinction between simulated and observed execution.
