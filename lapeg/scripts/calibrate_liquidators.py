"""Phase 3 calibration inputs from recorded Liquidate events (no network needed for this part).

Reads data/discovered/aug25_event.json and, for one market, computes:
  - identity concentration: liquidations and repaid value per liquidator (caller), Herfindahl index
  - size distribution: repaid assets and seized collateral per liquidation
  - timing: blocks between consecutive liquidations
Output: data/discovered/<name>_calibration.json

Usage: python scripts/calibrate_liquidators.py [--market-id 0x...] [--events aug25_event]
"""

import argparse
import json
import statistics
from typing import Any

from lapeg import PROJECT_ROOT

D = PROJECT_ROOT / "data" / "discovered"
DEFAULT_MARKET = "0x1e9d614631a7df0ec07fb05b2c8cb2491575fd1a63a33bf187a6afb295a4fc64"


def describe(xs: list[float]) -> dict[str, float]:
    xs = sorted(xs)
    return {"n": len(xs), "min": xs[0], "median": statistics.median(xs), "mean": statistics.fmean(xs),
            "max": xs[-1], "sum": sum(xs)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market-id", default=DEFAULT_MARKET)
    ap.add_argument("--events", default="aug25_event")
    a = ap.parse_args()
    data = json.loads((D / f"{a.events}.json").read_text())
    meta = next(m for m in data["markets"] if m["market_id"] == a.market_id)
    ld, cd = 10 ** meta["loan"]["decimals"], 10 ** meta["collateral"]["decimals"]
    evs = sorted((e for e in data["events"] if e["market_id"] == a.market_id),
                 key=lambda e: (e["block"], e["log_index"]))

    by_liq: dict[str, dict[str, Any]] = {}
    for e in evs:
        s = by_liq.setdefault(e["liquidator"], {"n": 0, "repaid": 0.0, "borrowers": set()})
        s["n"] += 1
        s["repaid"] += int(e["repaid_assets"]) / ld
        s["borrowers"].add(e["borrower"])
    total = sum(s["repaid"] for s in by_liq.values())
    shares = {k: s["repaid"] / total for k, s in by_liq.items()}
    out = {
        "source": f"data/discovered/{a.events}.json", "market_id": a.market_id,
        "collateral": meta["collateral"]["symbol"], "loan": meta["loan"]["symbol"],
        "n_liquidations": len(evs), "n_borrowers": len({e["borrower"] for e in evs}),
        "liquidators": {k: {"liquidations": s["n"], "repaid": s["repaid"], "share_of_repaid": shares[k],
                            "borrowers": len(s["borrowers"])}
                        for k, s in sorted(by_liq.items(), key=lambda kv: -kv[1]["repaid"])},
        "herfindahl_repaid": sum(v * v for v in shares.values()),
        "repaid_per_liquidation": describe([int(e["repaid_assets"]) / ld for e in evs]),
        "seized_per_liquidation": describe([int(e["seized_assets"]) / cd for e in evs]),
        "blocks_between_liquidations": describe([float(b - a_) for a_, b in
                                                 zip([e["block"] for e in evs], [e["block"] for e in evs][1:],
                                                     strict=False)]) if len(evs) > 1 else None,
        "first_block": evs[0]["block"], "last_block": evs[-1]["block"],
        "bad_debt": sum(int(e["bad_debt_assets"]) for e in evs) / ld,
    }
    path = D / f"{a.events}_calibration.json"
    path.write_text(json.dumps(out, indent=1) + "\n")
    keys = ("n_liquidations", "n_borrowers", "herfindahl_repaid", "repaid_per_liquidation",
            "blocks_between_liquidations")
    print(json.dumps({k: out[k] for k in keys}, indent=1))
    for k, v in out["liquidators"].items():
        print(f"  {k}: {v['liquidations']} liquidations, {v['repaid'] / 1e6:.2f}M repaid "
              f"({100 * v['share_of_repaid']:.1f}%), {v['borrowers']} borrowers")


if __name__ == "__main__":
    main()
