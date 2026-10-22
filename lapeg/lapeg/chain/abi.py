"""ABIs compiled from verified sources by scripts/build_abis.py (see abis/SOURCES.json)."""

import json
from functools import cache
from importlib import resources
from typing import Any


@cache
def load_abi(name: str) -> list[dict[str, Any]]:
    """Load abis/<name>.json, e.g. 'Morpho', 'Oracle', 'ERC20'."""
    text = resources.files("lapeg.chain").joinpath("abis", f"{name}.json").read_text(encoding="utf-8")
    return json.loads(text)
