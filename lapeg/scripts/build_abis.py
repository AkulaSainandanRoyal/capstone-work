"""Compile the vendored interfaces with forge and write the ABIs the Python code uses.

Outputs (committed, so Python does not need forge at runtime):
    lapeg/chain/abis/Morpho.json   IMorpho functions + EventsLib events (Morpho Blue v1.0.0)
    lapeg/chain/abis/Oracle.json   IOracle (Morpho oracle interface)
    lapeg/chain/abis/ERC20.json    forge-std IERC20
    lapeg/chain/abis/HealthReader.json, lapeg/chain/bytecode/HealthReader.hex
                                   helper ABI and runtime code (injected with eth_call state overrides)
    lapeg/chain/abis/SOURCES.json  which artifact each ABI came from

Usage: python scripts/build_abis.py [--no-build]
"""

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"
ABI_DIR = ROOT / "lapeg" / "chain" / "abis"

TARGETS = {
    "Morpho": [("IMorpho.sol", "IMorpho"), ("EventsLib.sol", "EventsLib")],
    "Oracle": [("IOracle.sol", "IOracle")],
    "ERC20": [("IERC20.sol", "IERC20")],
    "HealthReader": [("HealthReader.sol", "HealthReader")],
}
RUNTIME = {"HealthReader": ("HealthReader.sol", "HealthReader")}   # helpers whose runtime code we inject
BYTECODE_DIR = ROOT / "lapeg" / "chain" / "bytecode"


def artifact_abi(source: str, contract: str) -> list[dict]:
    path = OUT / source / f"{contract}.json"
    if not path.exists():
        raise SystemExit(f"missing artifact {path}: run forge build first")
    return json.loads(path.read_text())["abi"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-build", action="store_true", help="use the existing out/ artifacts")
    a = ap.parse_args()
    if not a.no_build:
        subprocess.run(["forge", "build"], cwd=ROOT, check=True)

    ABI_DIR.mkdir(parents=True, exist_ok=True)
    sources = {}
    for name, parts in TARGETS.items():
        abi: list[dict] = []
        for source, contract in parts:
            abi += artifact_abi(source, contract)
        (ABI_DIR / f"{name}.json").write_text(json.dumps(abi, indent=1) + "\n")
        sources[name] = [f"out/{s}/{c}.json" for s, c in parts]
        print(f"{name}: {len(abi)} entries")
    (ABI_DIR / "SOURCES.json").write_text(json.dumps(sources, indent=1) + "\n")

    BYTECODE_DIR.mkdir(parents=True, exist_ok=True)
    for name, (source, contract) in RUNTIME.items():
        art = json.loads((OUT / source / f"{contract}.json").read_text())
        code = art["deployedBytecode"]["object"]
        if not code or code == "0x":
            raise SystemExit(f"{contract} has no runtime bytecode")
        (BYTECODE_DIR / f"{name}.hex").write_text(code + "\n")
        print(f"{name}: runtime code {len(code) // 2 - 1} bytes")


if __name__ == "__main__":
    main()
