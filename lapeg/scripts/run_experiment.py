"""Run an experiment from its YAML config and print the result summary.

Usage: python scripts/run_experiment.py experiments/phase0_fork_smoke.yaml
"""

import json
import sys

from lapeg.config import load_experiment
from lapeg.fork.smoke import run_fork_smoke

RUNNERS = {"phase0_fork_smoke": run_fork_smoke}


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    cfg = load_experiment(sys.argv[1])
    runner = RUNNERS.get(cfg.name)
    if runner is None:
        raise SystemExit(f"no runner for experiment '{cfg.name}' (known: {', '.join(RUNNERS)})")
    result = runner(cfg)
    print(json.dumps({k: result[k] for k in ("experiment", "rpc_source", "fork_block", "block_pinned",
                                             "checks", "passed")}, indent=1))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
