"""Walk each market's oracle down to its leaf price sources and record how the PT price is computed.

For every contract in the tree:
  - resolve EIP-1167 minimal proxies to their implementation,
  - look up the verified source on Sourcify (name + ABI),
  - call every zero-argument view function in the verified ABI and record the result,
  - recurse into fields that point at other price sources (feeds, vaults, inner/primary/backup oracles).
Contracts with no verified source are probed with getter names taken from the 4byte signature database;
those values are marked unverified.

Output: data/discovered/oracles.json (tree, per-market classification, block, method).
Usage: python scripts/inspect_oracles.py [--rpc URL]
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from typing import Any

import requests
from eth_abi import decode
from web3 import Web3

from lapeg import PROJECT_ROOT
from lapeg.config import PUBLIC_ARCHIVE_RPC

SOURCIFY = "https://sourcify.dev/server/v2/contract/1/{address}?fields=compilation,abi"
SOURCIFY_CACHE = PROJECT_ROOT / "data" / "raw" / "sourcify"
OUT = PROJECT_ROOT / "data" / "discovered" / "oracles.json"
EIP1167_PREFIX, EIP1167_SUFFIX = "363d3d373d3d3d363d73", "5af43d82803e903d91602b57fd5bf3"
ZERO = "0x0000000000000000000000000000000000000000"
# Sourcify-verified instances found while walking these trees, used to identify unverified copies of the
# same code. getters: zero-arg views whose values are that contract's immutables.
REFERENCES: dict[str, tuple[str, dict[str, str]]] = {
    "MorphoChainlinkOracleV2": ("0x217d6DdCDB95112C51657F6270e8C079CFDB51f0", {
        "BASE_FEED_1()": "address", "BASE_FEED_2()": "address", "QUOTE_FEED_1()": "address",
        "QUOTE_FEED_2()": "address", "BASE_VAULT()": "address", "QUOTE_VAULT()": "address",
        "BASE_VAULT_CONVERSION_SAMPLE()": "uint256", "QUOTE_VAULT_CONVERSION_SAMPLE()": "uint256",
        "SCALE_FACTOR()": "uint256"}),
    "PendleSparkLinearDiscountOracle": ("0x68EfEdb720F4fFbA213745B21756365fa8617B9b", {
        "PT()": "address", "maturity()": "uint256", "baseDiscountPerYear()": "uint256"}),
}

# Fields that point at another price source: recurse into these.
CHILD_FIELDS = {"BASE_FEED_1", "BASE_FEED_2", "QUOTE_FEED_1", "QUOTE_FEED_2", "BASE_VAULT", "QUOTE_VAULT",
                "FEED_1", "FEED_2", "innerOracle", "primaryOracle", "backupOracle"}
# Fields that point at a token or market: identify, but do not recurse.
LEAF_FIELDS = {"market", "PT", "factory"}
# Getters for the unverified failover oracle (names from the 4byte signature database, not from source).
UNVERIFIED_GETTERS = {
    "primaryOracle()": "address", "backupOracle()": "address", "currentOracle()": "address",
    "isPrimary()": "bool", "isBackup()": "bool", "deviationThreshold()": "uint256",
    "getDeviation()": "uint256",
    "isDeviant()": "bool", "isChallenged()": "bool", "isHealing()": "bool", "primaryPrice()": "uint256",
    "backupPrice()": "uint256", "price()": "uint256", "challengeTimelockDuration()": "uint256",
    "healingTimelockDuration()": "uint256",
}


class Inspector:
    def __init__(self, w3: Web3, block: int) -> None:
        self.w3, self.block = w3, block

    def sourcify(self, address: str) -> dict[str, Any]:
        SOURCIFY_CACHE.mkdir(parents=True, exist_ok=True)
        path = SOURCIFY_CACHE / f"{address.lower()}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        r = requests.get(SOURCIFY.format(address=address), timeout=60)
        data = r.json() if r.ok else {}
        path.write_text(json.dumps(data), encoding="utf-8")
        return data

    def proxy_target(self, address: str) -> str | None:
        code = self.w3.eth.get_code(Web3.to_checksum_address(address), self.block).hex().removeprefix("0x")
        if code.startswith(EIP1167_PREFIX) and code.endswith(EIP1167_SUFFIX):
            return Web3.to_checksum_address("0x" + code[len(EIP1167_PREFIX):len(EIP1167_PREFIX) + 40])
        return None

    def raw_call(self, address: str, sig: str, types: list[str]) -> Any:
        data = Web3.keccak(text=sig)[:4]
        out = self.w3.eth.call({"to": Web3.to_checksum_address(address), "data": data}, self.block)
        vals = decode(types, out)
        return vals[0] if len(vals) == 1 else list(vals)

    def match_reference(self, address: str) -> tuple[str, str, dict[str, Any]] | None:
        """Match an unverified contract to a verified reference with the same code apart from immutables.

        Accept only if the bytecodes have equal length and every differing byte run lies inside a 32-byte
        word equal to one of the instance's own getter values (its immutables)."""
        code = bytes(self.w3.eth.get_code(Web3.to_checksum_address(address), self.block))
        for ref_name, (ref_addr, getters) in REFERENCES.items():
            ref = bytes(self.w3.eth.get_code(Web3.to_checksum_address(ref_addr), self.block))
            if len(ref) != len(code):
                continue
            try:
                values = [self.raw_call(address, sig, [t]) for sig, t in getters.items()]
            except Exception:
                continue
            words = {(int(v, 16) if isinstance(v, str) else int(v)).to_bytes(32, "big") for v in values}
            diff = [i for i in range(len(code)) if code[i] != ref[i]]
            runs = [i for i in diff if i == 0 or i - 1 not in diff]
            if all(any(code[max(0, s - k):max(0, s - k) + 32] in words for k in range(32)) for s in runs):
                return ref_name, ref_addr, {"reference": ref_addr, "code_bytes": len(code),
                                            "differing_bytes": len(diff), "differing_runs": len(runs),
                                            "all_runs_inside_own_immutables": True}
        return None

    def identify(self, address: str) -> tuple[str | None, str | None, list[dict[str, Any]]]:
        """(implementation if proxy, verified contract name, verified ABI)."""
        impl = self.proxy_target(address)
        meta = self.sourcify(impl or address)
        name = (meta.get("compilation") or {}).get("name")
        return impl, name, meta.get("abi") or []

    def inspect(self, address: str, depth: int = 0, seen: set[str] | None = None) -> dict[str, Any]:
        seen = seen or set()
        address = Web3.to_checksum_address(address)
        impl, name, abi = self.identify(address)
        node: dict[str, Any] = {"address": address, "eip1167_implementation": impl,
                                "verified_name": name or "not verified on Sourcify",
                                "values": {}, "children": {}}
        if address in seen or depth > 6:
            node["see_above"] = True
            return node
        seen.add(address)

        if not abi:
            match = self.match_reference(address)
            if match is not None:
                ref_name, ref_addr, evidence = match
                abi = self.sourcify(ref_addr)["abi"]
                node["verified_name"] = f"{ref_name} (inferred: bytecode equals verified {ref_addr} " \
                                        f"except immutables)"
                node["inference"] = evidence

        if abi:
            getters = [f for f in abi if f.get("type") == "function" and not f.get("inputs")
                       and f.get("stateMutability") in ("view", "pure")]
            for f in getters:
                types = [o["type"] for o in f["outputs"]]
                try:
                    node["values"][f["name"]] = _jsonable(self.raw_call(address, f"{f['name']}()", types))
                except Exception as e:
                    node["values"][f["name"]] = f"reverted: {str(e)[:80]}"
        else:
            node["values_unverified_names"] = True
            for sig, t in UNVERIFIED_GETTERS.items():
                try:
                    node["values"][sig[:-2]] = _jsonable(self.raw_call(address, sig, [t]))
                except Exception:
                    pass

        for field, val in node["values"].items():
            if isinstance(val, str) and val.startswith("0x") and len(val) == 42 and val.lower() != ZERO:
                if field in CHILD_FIELDS:
                    node["children"][field] = self.inspect(val, depth + 1, seen)
                elif field in LEAF_FIELDS:
                    node["children"][field] = {"address": val, "verified_name": self.identify(val)[1]}
        return node


def _jsonable(v: Any) -> Any:
    if isinstance(v, bytes):
        return "0x" + v.hex()
    if isinstance(v, str) and v.startswith("0x") and len(v) == 42:
        return Web3.to_checksum_address(v)
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    if isinstance(v, int) and not isinstance(v, bool):
        return str(v) if abs(v) > 2**53 else v
    return v


def leaves(node: dict[str, Any]) -> list[str]:
    if node.get("see_above"):
        return []
    kids = [c for k, c in node["children"].items() if k in CHILD_FIELDS]
    if not kids:
        return [node["verified_name"]]
    return [name for c in kids for name in leaves(c)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rpc", default=os.environ.get("ARCHIVE_RPC_URL", PUBLIC_ARCHIVE_RPC))
    a = ap.parse_args()
    w3 = Web3(Web3.HTTPProvider(a.rpc, request_kwargs={"timeout": 60}))
    block = w3.eth.block_number - 8
    markets = json.loads((PROJECT_ROOT / "data" / "discovered" / "markets.json").read_text())["markets"]
    ins = Inspector(w3, block)

    result: dict[str, Any] = {
        "block": block,
        "retrieved_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "method": "eth_getCode (EIP-1167 resolution) + Sourcify verified ABI + eth_call of zero-arg views",
        "sourcify_api": SOURCIFY,
        "markets": {},
    }
    for m in markets:
        tree = ins.inspect(m["oracle"])
        result["markets"][m["name"]] = {"oracle": m["oracle"], "leaf_sources": sorted(set(leaves(tree))),
                                        "tree": tree}
        print(f"{m['name']}: leaves = {sorted(set(leaves(tree)))}")
    OUT.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
