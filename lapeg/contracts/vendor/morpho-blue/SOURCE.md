# Vendored Morpho Blue sources

Copied unchanged from the verified Morpho Blue repository so that ABIs are compiled from source, not written by hand.

- Repository: https://github.com/morpho-org/morpho-blue
- Release: `v1.0.0`
- Commit: `55d2d99304fb3fb930c688462ae2ccabb1d533ad`
- Files: each `src/<path>` upstream is vendored at `<path>` here (table below).
- License: GPL-2.0-or-later (see the SPDX header in each file)

Integrity: each file's `git hash-object` equals the upstream blob SHA at that commit.

| File | Git blob SHA |
|---|---|
| `interfaces/IMorpho.sol` | `9c82524cb56a1b89a5a14ec5ca1e69665bc25cc3` |
| `interfaces/IOracle.sol` | `482737ef92f56722201610d2e42a4433431a4cec` |
| `libraries/EventsLib.sol` | `2ff9b829d45289aa6165788bdadc9cbee60ff4ae` |
| `interfaces/IIrm.sol` | `3de0bc1e8c5bada783e0b1d303242ce339efdd69` |
| `libraries/MathLib.sol` | `653db4f87580d5f9fd6162a78715d5416f8aac63` |
| `libraries/SharesMathLib.sol` | `3ed7115b5bcc491199446837c5a737eb80c5675c` |
| `libraries/UtilsLib.sol` | `f343ef769d04dc037578c226f23aca420f29da26` |
| `libraries/MarketParamsLib.sol` | `456b0e17e45eb43deeddc97424e113445c1dff24` |
| `libraries/ConstantsLib.sol` | `c4e49fe5470fb5f93e0f4e2f051ad1c45bcbbac8` |
| `libraries/ErrorsLib.sol` | `02cc94423aae4ff319dfae18ba93971b9b905ca5` |
| `libraries/periphery/MorphoBalancesLib.sol` | `94b3b85f9d9d28847da90a49e1855cb02362decf` |
| `libraries/periphery/MorphoLib.sol` | `c366d1a6bb309ca6597e7feedd41bada50054839` |
| `libraries/periphery/MorphoStorageLib.sol` | `07e3900885d3902a573a9a8055de18a0c24d5cab` |

The libraries (added in Phase 1) are used by `contracts/HealthReader.sol` to compute health exactly as
`Morpho._isHealthy` does.

`EventsLib.sol` imports `../interfaces/IMorpho.sol`, so the folder layout mirrors the upstream `src/` tree.
