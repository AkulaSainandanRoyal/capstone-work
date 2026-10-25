"""Fetch ABIs of deployed third-party contracts from their Sourcify-verified sources.

Complements scripts/build_abis.py (which compiles vendored sources). Each ABI is taken from a contract that
is fully verified on Sourcify, and SOURCES.json records which address it came from.

Usage: python scripts/fetch_verified_abis.py
"""

import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
ABI_DIR = ROOT / "lapeg" / "chain" / "abis"
SOURCIFY = "https://sourcify.dev/server/v2/contract/1/{address}?fields=compilation,abi"

# name -> (verified contract address, expected contract name). Addresses come from the PT-reUSD route trace
# (data/discovered/route_trace_*.json) and the oracle walk (data/discovered/oracles.json).
TARGETS = {
    "PendleActionSwapPT": ("0x9d215290f43366bbceff40a79fbac9dd23325379", "ActionSwapPTV3"),
    "PendleMarket": ("0x13285bcbc27f92b47b4edb99d744c07b48c977c0", "PendleMarketV7"),
    "PendleSY": ("0xba923d186156e48baab7e3c749e10f06e0b25067", "PendleREUSDSY"),
    "OjoPTFeed": ("0x5AAb95E3C6F9bA0CCfa0a17c2C7235633C7C6585", "OjoPTFeed"),
    "MorphoChainlinkOracleV2": ("0x217d6DdCDB95112C51657F6270e8C079CFDB51f0", "MorphoChainlinkOracleV2"),
}


def main() -> None:
    sources_path = ABI_DIR / "SOURCES.json"
    sources = json.loads(sources_path.read_text()) if sources_path.exists() else {}
    for name, (address, expected) in TARGETS.items():
        meta = requests.get(SOURCIFY.format(address=address), timeout=60).json()
        got = (meta.get("compilation") or {}).get("name")
        if got != expected or not meta.get("abi"):
            raise SystemExit(f"{address}: expected verified {expected}, Sourcify says {got!r}")
        (ABI_DIR / f"{name}.json").write_text(json.dumps(meta["abi"], indent=1) + "\n")
        sources[name] = [f"sourcify:1:{address} ({expected})"]
        print(f"{name}: {len(meta['abi'])} entries from {expected} at {address}")
    sources_path.write_text(json.dumps(sources, indent=1) + "\n")


if __name__ == "__main__":
    main()
