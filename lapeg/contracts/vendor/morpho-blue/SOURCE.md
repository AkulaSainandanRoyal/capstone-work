# Vendored Morpho Blue sources

Copied unchanged from the verified Morpho Blue repository so that ABIs are compiled from source, not written by hand.

- Repository: https://github.com/morpho-org/morpho-blue
- Release: `v1.0.0`
- Commit: `55d2d99304fb3fb930c688462ae2ccabb1d533ad`
- Files:
  - `src/interfaces/IMorpho.sol` -> `interfaces/IMorpho.sol`
  - `src/interfaces/IOracle.sol` -> `interfaces/IOracle.sol`
  - `src/libraries/EventsLib.sol` -> `libraries/EventsLib.sol`
- License: GPL-2.0-or-later (see the SPDX header in each file)

Integrity: each file's `git hash-object` equals the upstream blob SHA at that commit.

| File | Git blob SHA |
|---|---|
| `interfaces/IMorpho.sol` | `9c82524cb56a1b89a5a14ec5ca1e69665bc25cc3` |
| `interfaces/IOracle.sol` | `482737ef92f56722201610d2e42a4433431a4cec` |
| `libraries/EventsLib.sol` | `2ff9b829d45289aa6165788bdadc9cbee60ff4ae` |

`EventsLib.sol` imports `../interfaces/IMorpho.sol`, so the folder layout mirrors the upstream `src/` tree.
