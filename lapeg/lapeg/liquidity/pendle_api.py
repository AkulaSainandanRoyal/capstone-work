"""Pendle Convert API client: PT -> token quotes with ready-to-send router transactions.

Quotes are live: they reflect the chain at the time of the request and cannot be replayed at a past block.
LAPEG uses them for two things only: the routes (calldata) that are then *executed* on a fork, and a live
cross-check of the fork's executed output against the quoted output.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import requests

CONVERT_URL = "https://api-v2.pendle.finance/core/v3/sdk/1/convert"


@dataclass(frozen=True)
class Route:
    aggregator: str | None
    tx_to: str
    tx_from: str
    tx_data: str
    quoted_out: int
    api_gas: int | None
    price_impact: float | None
    internal_impact: float | None
    external_impact: float | None


@dataclass
class Quote:
    amount_in: int
    http_status: int
    quoted_utc: str
    routes: list[Route] = field(default_factory=list)
    refusal: str | None = None  # API refusal message (e.g. MarketProportionTooHigh)


def _routes(body: dict[str, Any], token_out: str) -> list[Route]:
    out = []
    for r in body.get("routes", []):
        amount = next(
            (
                int(o["amount"])
                for o in r.get("outputs", [])
                if str(o.get("token", "")).lower() == token_out.lower()
            ),
            None,
        )
        tx = r.get("tx") or {}
        if amount is None or not tx.get("data"):
            continue
        d = r.get("data") or {}
        br = d.get("priceImpactBreakDown") or {}
        out.append(
            Route(
                d.get("aggregatorType"),
                tx["to"],
                tx["from"],
                tx["data"],
                amount,
                d.get("gasUsed"),
                d.get("priceImpact"),
                br.get("internalPriceImpact"),
                br.get("externalPriceImpact"),
            )
        )
    return out


def quote(
    token_in: str,
    token_out: str,
    amount_in: int,
    receiver: str,
    *,
    slippage: float = 0.01,
    retries: int = 4,
    pause_s: float = 0.5,
) -> Quote:
    """One Convert quote (aggregators enabled). Refusals are returned, not raised."""
    body = {
        "receiver": receiver,
        "slippage": slippage,
        "inputs": [{"token": token_in, "amount": str(amount_in)}],
        "outputs": [token_out],
        "enableAggregator": True,
    }
    last: Exception | None = None
    for attempt in range(retries):
        try:
            r = requests.post(CONVERT_URL, json=body, timeout=120)
        except requests.RequestException as e:
            last = e
            time.sleep(2**attempt)
            continue
        stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        if r.status_code == 429:
            time.sleep(min(65, 5 * 2**attempt))
            continue
        if not r.ok:
            try:
                msg = r.json().get("message", r.text)
            except ValueError:
                msg = r.text
            return Quote(amount_in, r.status_code, stamp, refusal=str(msg)[:300])
        time.sleep(pause_s)
        return Quote(amount_in, r.status_code, stamp, routes=_routes(r.json(), token_out))
    raise RuntimeError(f"Convert API unavailable after {retries} attempts: {last}")
