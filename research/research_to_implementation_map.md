# Research-to-Implementation Mapping

## 1. Purpose

This document connects the project's research questions with the existing literature themes, the planned experimental approach, and the evidence required to support conclusions.

The purpose is to keep the literature survey aligned with the project's implementation rather than treating the two as separate activities.

## 2. Research question mapping

| Research question | Literature theme to investigate | Project measurement or experiment | Evidence required |
|---|---|---|---|
| RQ1: Liquidation size | Market liquidity, price impact, oracle prices versus executable prices | Measure execution prices across different sale sizes and estimate liquidation capacity | Reproducible quotes, execution depth curves, and price-impact measurements |
| RQ2: Time to maturity | Fixed versus maturity-sensitive pricing and collateral risk | Compare collateral pricing and liquidation capacity as PTs approach maturity | Measurements across maturity-related time points |
| RQ3: Liquidity rollover | Liquidity fragmentation across markets and maturity dates | Investigate whether executable liquidity changes as activity shifts between maturities | Market liquidity observations across relevant dates and maturities |
| RQ4: Liquidator access | Liquidator incentives, market participation, and transaction constraints | Compare executable liquidation capacity with collateral exposure and investigate route restrictions | Route results, liquidity limits, and evidence of access constraints |
| RQ5: Mitigation | Liquidation mechanisms, oracle design, and mechanisms for reducing cascading liquidations | Compare the proposed LAPEG policy against a baseline under equivalent scenarios | Historical replay results, baseline comparisons, and measured outcomes |

## 3. Connection to the current implementation

The repository documents three Pendle PT collateral markets with different oracle designs. These provide a useful basis for investigating how oracle construction affects the relationship between market prices, executable prices, and liquidation incentives.

The repository also identifies a historical liquidation event on August 25, 2026. This event can support historical replay, but its cause and its relationship to the later liquidity measurements must be established rather than assumed.

The proposed LAPEG guard is a mitigation prototype. Its effectiveness should be evaluated through reproducible replay and comparison with an appropriate baseline; the existence of a working prototype alone does not establish that it prevents liquidation cascades.

## 4. Evidence and interpretation principles

1. Distinguish measured results from assumptions and hypotheses.
2. Record the block, timestamp, market, and configuration for reproducible measurements.
3. Do not treat oracle prices as equivalent to executable sale prices.
4. Do not infer that an oracle caused a liquidation event without supporting evidence.
5. Compare mitigation policies under equivalent initial conditions and stress scenarios.
6. Report route failures and unavailable liquidity as capacity constraints, not as ordinary price-impact observations.
7. Describe the research gap only after comparing the relevant prior literature.

## 5. Next research tasks

- Expand the literature review on DeFi liquidation mechanisms, oracle design, liquidity risk, and deleveraging feedback.
- Verify bibliographic details and the claims made by each cited paper.
- Record each paper's research question, methodology, findings, and limitations in the comparison matrix.
- Map the identified limitations to the project's research questions.
- Update the document as experimental results and historical replay validation become available.

## 6. Scope and status

This is a working research-planning document, not a claim that every experiment has been completed or that the proposed mitigation has been validated.

The literature comparison and research-gap claims require further source verification.
