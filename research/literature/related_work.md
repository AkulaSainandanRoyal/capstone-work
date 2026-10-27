# Related Work — First Seven Papers (Provisional)

## Scope

This note synthesises the first seven supplied PDFs for the capstone project, **Measurement and Mitigation of Illiquidity in Collateral-Based Lending in DeFi**. It is a provisional first-batch review, not a claim that the full literature has been covered. Statements below are high-level summaries; add page-level citations after checking each PDF.

## DeFi architecture and risk context

Schär (2021) describes DeFi as a set of blockchain- and smart-contract-based financial-market layers, including exchanges, debt markets and asset-management applications. This helps place collateralised lending within a composable system, but it does not provide an executable-price curve for a particular collateral asset.

Jensen, von Wachter and Ross (2021) offer an introductory taxonomy of DeFi applications, participants, incentives and risks. This is useful for defining actors and mechanisms, but it is not a direct empirical study of liquidation capacity.

Aramonte, Huang and Schrimpf (2021) frame DeFi risks in financial-stability terms, including leverage, liquidity mismatch and interconnectedness. Carapella et al. (2022) provide a broad overview of DeFi's potential and risks. Together, these sources motivate studying liquidity under stress, while leaving open the narrower measurement question of whether collateral can be sold at an oracle-implied value for the size and timing of a liquidation.

## Collateral, stablecoins and deleveraging

Klages-Mundt et al. (2020) develop risk-based models for stablecoins and discuss risk channels involving collateral, deleveraging, data feeds, governance, the base layer and smart contracts. Klages-Mundt and Minca model deleveraging spirals and stablecoin attacks, providing a conceptual basis for feedback effects during stress. These works help motivate liquidation-cascade analysis, but they do not, by themselves, establish the executable capacity of the specific Pendle PT collateral markets studied in this capstone.

The seventh supplied PDF has inconsistent identity information: its filename refers to d’Avernas, Maurin and Vandeweyer (2022), while the visible title is “Can Stablecoins Be Stable?” and the visible date is 2025-12-31. It should be excluded from attributed claims until its bibliographic identity is verified.

## Synthesis against the research questions

- **RQ1 — Trade size:** The first seven papers motivate liquidity risk but do not directly provide the project's trade-size-dependent oracle-versus-executable price curve or `q_max` measurement.
- **RQ2 — Time to maturity:** This batch does not directly establish how Pendle PT executable capacity changes as maturity approaches.
- **RQ3 — Rollover:** Deleveraging models motivate feedback risk, but the supplied papers do not directly measure liquidity migrating across successive PT maturities.
- **RQ4 — Access and capacity:** The papers discuss participants and systemic risk, but do not quantify eligible liquidator/redemption capacity against the target collateral exposure.
- **RQ5 — Mitigation:** The sources provide risk mechanisms and context, but do not compare the project's proposed guard or alternative liquidation policies through a reproducible historical replay.

## Provisional gap statement

Based only on this first batch, a promising project-specific gap to test is the lack of an integrated, reproducible workflow that connects (1) executable collateral-sale capacity by trade size, (2) oracle-to-execution divergence, (3) liquidation demand under shocks, (4) liquidator/access constraints and feedback, and (5) counterfactual evaluation of pre-execution mitigations against a fixed-parameter baseline. This is a **provisional gap**, not a verified claim of novelty. It must be tested against additional empirical studies and protocol-specific research.

## What to do before final submission

1. Review the remaining papers and update the comparison matrix.
2. Verify the seventh PDF's actual authors, title, date and publication source.
3. Add page/section-level citations for each specific claim.
4. Separate literature-supported claims from project implementation choices and results.
5. Avoid claiming that LAPEG prevents cascades until replay results support that conclusion.
