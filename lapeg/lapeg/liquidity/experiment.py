"""Phase 2 experiment: liquidity and oracle measurement for one market, on a fork of the current block.

Steps:
  1. Quote a log-spaced grid of PT sizes with Pendle's Convert API (live), then fork the current block.
  2. Execute every returned route on the fork (real venues) and keep the best output: P_exec(q), G(q).
     Also sell through the Pendle market alone (internal leg) at each size.
  3. Bisect towards q_max (fresh quotes, executed on the same fork).
  4. Gas in USD (Chainlink via ENS), flash liquidity, q_max with and without gas, and under stress gas.
  5. Rebuild the position book at the same block (Phase 1).
  6. Oracle override: force P_o(1-Delta) and let Morpho's own code decide who is liquidatable, for a shock
     grid and at the exact break point Delta*.
  7. End to end at Delta*: a real `liquidate` on the fork, then the sale of the seized PT on a real route.
Acceptance (spec, Phase 2): depth curve and G(q) at one block; G ~ 0 for tiny q when the oracle is fresh;
G non-decreasing in q. Shared addendum test: fork-executed output matches the API quote at the current block.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from web3 import Web3

from lapeg import PROJECT_ROOT
from lapeg.chain.abi import load_abi
from lapeg.chain.health_reader import read_health
from lapeg.chain.morpho import MorphoBlue, load_morpho_address
from lapeg.config import ExperimentConfig, resolve_rpc_url
from lapeg.fork.anvil import AnvilError, AnvilFork
from lapeg.fork.state import find_allowance_index, find_balance_slot, set_erc20_balance
from lapeg.liquidity.capacity import flash_liquidity, gas_cost_usd, gas_price
from lapeg.liquidity.execute import Execution, execute_route, sell_pt_for_sy
from lapeg.liquidity.pendle_api import Quote, Route, quote
from lapeg.liquidity.realnode import TokenSlots, call_route
from lapeg.market import morpho_math as mm
from lapeg.market.experiment import run_position_book
from lapeg.metrics import illiquidity as il
from lapeg.oracle.override import override_ojo_feed

DISCOVERED = PROJECT_ROOT / "data" / "discovered"


def _grid(lo: float, hi: float, growth: float) -> list[float]:
    n = int(math.floor(math.log(hi / lo) / math.log(growth))) + 1
    return [lo * growth**i for i in range(n)]


def _oracle_setup(name: str) -> dict[str, str]:
    tree = json.loads((DISCOVERED / "oracles.json").read_text(encoding="utf-8"))["markets"][name]["tree"]
    feed = tree["children"].get("BASE_FEED_1", {})
    if not str(feed.get("verified_name", "")).startswith("OjoPTFeed"):
        raise RuntimeError(f"{name}: oracle override is implemented for OjoPTFeed base feeds only")
    twap = feed["children"]["FEED_1"]
    return {"ojo": feed["address"], "pendle_market": twap["children"]["market"]["address"]}


def _head_block(url: str, attempts: int = 6) -> int:
    """Current block, retried on a fresh connection (free endpoints drop idle connections)."""
    for i in range(attempts):
        try:
            return int(Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 60})).eth.block_number)
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(2**i)
    raise AssertionError("unreachable")


def _checkpoint_path(cfg: ExperimentConfig) -> Path:
    return cfg.path(Path("data/raw")) / f"checkpoint_{cfg.name}_{cfg.market.name}.json"


def _quote_to_json(phase: str, q: Quote) -> dict[str, Any]:
    return {"phase": phase, "quote": {**asdict(q), "routes": [asdict(r) for r in q.routes]}}


def _quote_from_json(d: dict[str, Any]) -> tuple[str, Quote]:
    q = dict(d["quote"])
    q["routes"] = [Route(**r) for r in q["routes"]]
    return d["phase"], Quote(**q)


def run_liquidity(cfg: ExperimentConfig, write_results: bool = True) -> dict[str, Any]:
    t0 = time.monotonic()
    p = cfg.params
    market = next(
        m
        for m in json.loads((DISCOVERED / "markets.json").read_text())["markets"]
        if m["market_id"] == cfg.market.market_id
    )
    pt, usdc, oracle = market["collateral_token"], market["loan_token"], market["oracle"]
    setup = _oracle_setup(cfg.market.name)
    morpho_addr = load_morpho_address(cfg.path(cfg.morpho_discovery))
    seller = Web3.to_checksum_address(Web3.keccak(text=f"lapeg-seller-{cfg.seed}")[-20:])
    url, rpc_source = resolve_rpc_url(cfg.fork)
    up = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 60}))

    # 1. quotes (live), sized at the current oracle price
    price_now = MorphoBlue(up, morpho_addr).oracle_price(oracle)
    loan_dec = int(up.eth.contract(address=usdc, abi=load_abi("ERC20")).functions.decimals().call())

    def pt_for_usd(usd: float, price: int) -> int:
        return int(usd * 10**loan_dec * il.ORACLE_PRICE_SCALE // price)

    ckpt = _checkpoint_path(cfg)
    if p.get("resume", True) and ckpt.exists():
        saved = json.loads(ckpt.read_text())
        block, rows, route_rows = saved["block"], saved["rows"], saved["route_rows"]
        quotes = [_quote_from_json(d) for d in saved["quotes"]]
        print(f"resuming at block {block}: {len(rows)} of {len(quotes)} sizes done ({ckpt.name})")
    else:
        sizes = _grid(float(p.get("min_usd", 1e5)), float(p.get("max_usd", 4e7)), float(p.get("growth", 1.5)))
        print(f"quoting {len(sizes)} sizes")
        quotes = [("grid", quote(pt, usdc, pt_for_usd(s, price_now), seller)) for s in sizes]
        block = _head_block(url)  # fresh connection: the one above sat idle while quoting
        rows, route_rows = [], []
        print(f"forking block {block}")

    def save_checkpoint() -> None:
        ckpt.parent.mkdir(parents=True, exist_ok=True)
        ckpt.write_text(
            json.dumps(
                {
                    "block": block,
                    "rows": rows,
                    "route_rows": route_rows,
                    "quotes": [_quote_to_json(ph, q) for ph, q in quotes],
                },
                default=str,
            )
        )

    save_checkpoint()
    real = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 120}))  # real-node cross-check
    retries = int(p.get("fork_retries", 3))
    for attempt in range(retries):
        try:
            with AnvilFork(
                url, block, extra_args=cfg.fork.anvil_args, startup_timeout_s=cfg.fork.startup_timeout_s
            ) as fork:
                assert fork.w3 is not None
                w3 = fork.w3
                fork.set_block_interval(12)  # deterministic timestamps: fork block + 12 s per mined block
                morpho = MorphoBlue(w3, morpho_addr)
                params = morpho.market_params(cfg.market.market_id)
                price = morpho.oracle_price(oracle)
                lif = mm.liquidation_incentive_factor(params.lltv)
                thr = il.bonus_threshold(lif)
                gp = gas_price(w3, block)
                stress_fee = int(float(p.get("stress_priority_fee_gwei", 100)) * 1e9)
                slot_pt = find_balance_slot(fork, pt)
                allow_index, allow_layout = find_allowance_index(fork, pt)
                token_slots = TokenSlots(pt, slot_pt.index, slot_pt.layout, allow_index, allow_layout)
                pmarket = w3.eth.contract(
                    address=Web3.to_checksum_address(setup["pendle_market"]), abi=load_abi("PendleMarket")
                )
                sy, mpt, _ = pmarket.functions.readTokens().call()
                if mpt.lower() != pt.lower():
                    raise RuntimeError("Pendle market does not trade this PT")
                sy_rate = int(
                    w3.eth.contract(address=sy, abi=load_abi("PendleSY")).functions.exchangeRate().call()
                )
                router = quotes[0][1].routes[0].tx_to if quotes[0][1].routes else None

                def measure(phase: str, q: Quote) -> dict[str, Any]:
                    amt = q.amount_in
                    best: Execution | None = None
                    best_route: Route | None = None
                    measured_on = None
                    for i, r in enumerate(q.routes):
                        ex = execute_route(fork, r, pt, usdc, amt, slot_pt)
                        if (
                            ex.status == "timeout"
                        ):  # first touch of many venues; retry once on the warmed fork
                            ex = execute_route(fork, r, pt, usdc, amt, slot_pt)
                        rn = None
                        if (
                            ex.status != "ok"
                        ):  # same tx on the real node at the same block: real revert or fork artifact?
                            rn = call_route(real, block, token_slots, r.tx_from, r.tx_to, r.tx_data, amt)
                        route_rows.append(
                            {
                                "phase": phase,
                                "amount_in": str(amt),
                                "route": i,
                                "aggregator": r.aggregator,
                                "status": ex.status,
                                "amount_out": str(ex.amount_out),
                                "quoted_out": str(r.quoted_out),
                                "gas_used": ex.gas_used,
                                "error": ex.error,
                                "tx_to": r.tx_to,
                                "tx_from": r.tx_from,
                                "tx_data": r.tx_data,
                                "quoted_utc": q.quoted_utc,
                                "real_node_status": rn.status if rn else None,
                                "real_node_out": str(rn.amount_out) if rn else None,
                                "real_node_error": rn.error if rn else None,
                            }
                        )
                        if ex.status == "ok" and (best is None or ex.amount_out > best.amount_out):
                            best, best_route, measured_on = ex, r, "fork"
                        elif rn and rn.status == "ok" and (best is None or rn.amount_out > best.amount_out):
                            gas = int(r.api_gas or 0)
                            best, best_route, measured_on = (
                                Execution("ok", rn.amount_out, gas),
                                r,
                                "real_node_call",
                            )
                    leg = (
                        sell_pt_for_sy(fork, router, setup["pendle_market"], pt, sy, amt, seller, slot_pt)
                        if router
                        else None
                    )
                    timed_out = (
                        any(x["status"] == "timeout" for x in route_rows[-len(q.routes) :])
                        if q.routes
                        else False
                    )
                    status = (
                        "refused"
                        if q.refusal
                        else "ok"
                        if best
                        else "timeout"
                        if timed_out
                        else "reverted"
                        if q.routes
                        else "no_route"
                    )
                    row: dict[str, Any] = {
                        "phase": phase,
                        "amount_in": amt,
                        "size_usd_at_oracle": amt * price / il.ORACLE_PRICE_SCALE / 10**loan_dec,
                        "status": status,
                        "refusal": q.refusal,
                        "n_routes": len(q.routes),
                        "amount_out": best.amount_out if best else 0,
                        "measured_on": measured_on,
                        "n_routes_reverting_on_real_node": sum(
                            1 for x in route_rows[-len(q.routes) :] if x["real_node_status"] == "reverted"
                        )
                        if q.routes
                        else 0,
                        "gas_used": best.gas_used if best else 0,
                        "aggregator": best_route.aggregator if best_route else None,
                        "api_quoted_out": best_route.quoted_out if best_route else None,
                        "api_internal_impact": best_route.internal_impact if best_route else None,
                        "api_external_impact": best_route.external_impact if best_route else None,
                        "pendle_leg_status": leg.status if leg else None,
                        "pendle_leg_error": leg.error if leg else None,
                        "pendle_leg_sy_out": leg.amount_out if leg else None,
                    }
                    if best:
                        value = amt * price / il.ORACLE_PRICE_SCALE
                        g_usd, s_usd = (
                            gas_cost_usd(best.gas_used, gp),
                            gas_cost_usd(best.gas_used, gp, stress_fee),
                        )
                        row.update(
                            g=il.oracle_gap(best.amount_out, amt, price),
                            api_match=best.amount_out / best_route.quoted_out - 1 if best_route else None,
                            gas_usd=g_usd,
                            gas_usd_stress=s_usd,
                            threshold_gas=il.gas_adjusted_threshold(lif, value, g_usd * 10**loan_dec),
                            threshold_stress=il.gas_adjusted_threshold(lif, value, s_usd * 10**loan_dec),
                        )
                    if leg and leg.status == "ok":
                        row["g_pendle_leg"] = 1 - (
                            leg.amount_out * sy_rate / 1e18
                        ) * il.ORACLE_PRICE_SCALE / (amt * price)
                    g_txt = (
                        f"G={100 * row['g']:.3f}%"
                        if "g" in row
                        else status + (f" ({q.refusal[:50]})" if q.refusal else "")
                    )
                    print(f"  {phase:7s} {row['size_usd_at_oracle'] / 1e6:8.3f}M  {g_txt}")
                    return row

                done = {r["amount_in"] for r in rows}
                for phase, q in quotes:
                    if q.amount_in not in done:
                        rows.append(measure(phase, q))
                        save_checkpoint()

                def points() -> list[il.DepthPoint]:
                    # a timeout says nothing about the market: excluded, neither passing nor failing
                    return [
                        il.DepthPoint(r["amount_in"], r["status"], r["amount_out"], r["gas_used"])
                        for r in rows
                        if r["status"] != "timeout"
                    ]

                def thr_gas(pt_: il.DepthPoint) -> float:
                    r = next(x for x in rows if x["amount_in"] == pt_.amount_in)
                    return r.get("threshold_gas", thr)

                # 3. bisection towards q_max (gas-adjusted)
                for _ in range(int(p.get("bisect_steps", 6))):
                    lo, hi = il.q_max_bracket(points(), price, thr_gas)
                    if (
                        lo is None
                        or hi is None
                        or (hi.amount_in - lo.amount_in) / lo.amount_in <= float(p.get("rel_tol", 0.02))
                    ):
                        break
                    qb = quote(pt, usdc, (lo.amount_in + hi.amount_in) // 2, seller)
                    quotes.append(("bisect", qb))
                    rows.append(measure("bisect", qb))
                    save_checkpoint()

                pts = points()
                brackets = {
                    "bonus": il.q_max_bracket(pts, price, lambda _: thr),
                    "bonus_gas": il.q_max_bracket(pts, price, thr_gas),
                    "bonus_stress_gas": il.q_max_bracket(
                        pts,
                        price,
                        lambda x: next(r for r in rows if r["amount_in"] == x.amount_in).get(
                            "threshold_stress", thr
                        ),
                    ),
                }
                flash = flash_liquidity(w3, morpho_addr, usdc)
                sy_dec = int(w3.eth.contract(address=sy, abi=load_abi("ERC20")).functions.decimals().call())
            break
        except (AnvilError, requests.exceptions.ConnectionError, TimeoutError) as e:
            # the free endpoint dropped a connection: restart anvil at the same block; finished sizes are
            # kept in the checkpoint and skipped
            print(
                f"  fork failed ({type(e).__name__}); restarting at block {block} ({attempt + 1}/{retries})"
            )
            if attempt == retries - 1:
                raise
            time.sleep(10)

    # 5. position book at the same block
    book_cfg = cfg.model_copy(
        update={"fork": cfg.fork.model_copy(update={"block": block, "allow_recent_block": False})}
    )
    book = run_position_book(book_cfg, write_results=write_results)
    frame = book["_frame"]
    borrowers = frame[frame.borrow_shares_raw != "0"]

    lo, hi = brackets["bonus_gas"]
    shock_rows, override_exact, set_mismatch = [], True, 0
    e2e: dict[str, Any] = {}
    with AnvilFork(
        url, block, extra_args=cfg.fork.anvil_args, startup_timeout_s=cfg.fork.startup_timeout_s
    ) as fork:
        assert fork.w3 is not None
        w3 = fork.w3
        fork.set_block_interval(12)  # deterministic timestamps: fork block + 12 s per mined block
        morpho = MorphoBlue(w3, morpho_addr)
        accounts = list(borrowers.borrower)
        base_answer = price // 10**18  # base feed answer (18 dec) x SCALE_FACTOR (1e18) = price (1e36 scale)

        def shocked(delta: float) -> dict[str, Any]:
            answer = int(base_answer * (1 - delta))
            override_ojo_feed(fork, setup["ojo"], answer)
            p_shock = morpho.oracle_price(oracle)
            snap = read_health(w3, morpho_addr, cfg.market.market_id, accounts, accrue=True)
            liq = {a: s for a, s in snap.accounts.items() if s.borrowed > s.max_borrow}
            q_tot = sum(s.collateral for s in liq.values())
            q_seiz = sum(
                min(s.collateral, s.borrowed * lif * il.ORACLE_PRICE_SCALE // (p_shock * 10**18))
                for s in liq.values()
            )
            return {"answer": answer, "price": p_shock, "liq": liq, "q_tot": q_tot, "q_seiz": q_seiz}

        hf = dict(zip(borrowers.borrower, borrowers.health_factor, strict=True))
        for delta in [
            float(x) for x in p.get("shocks", [0.005, 0.01, 0.02, 0.03, 0.05, 0.075, 0.1, 0.15, 0.2])
        ]:
            with fork.branch():
                s = shocked(delta)
            override_exact &= s["price"] == s["answer"] * 10**18
            predicted = {a for a, h in hf.items() if h * (1 - delta) < 1}
            set_mismatch += len(predicted ^ set(s["liq"]))
            shock_rows.append(asdict(il.shock_row(delta, len(s["liq"]), s["q_tot"], s["q_seiz"], lo, hi)))

        # Delta*: walk the trigger shocks Delta_i = 1 - 1/HF_i in order; check each one with the override
        delta_star = None
        for trig in sorted({1 - 1 / h for h in hf.values() if h < float("inf") and h > 0}):
            if trig < 0:
                continue
            d = trig + 1e-9
            with fork.branch():
                s = shocked(d)
            if il.can_clear(s["q_seiz"], lo, hi) is not True:
                delta_star = {
                    "delta": d,
                    "n_liquidatable": len(s["liq"]),
                    "q_seizable_pt": s["q_seiz"],
                    "q_total_pt": s["q_tot"],
                    "verdict": il.can_clear(s["q_seiz"], lo, hi),
                }
                break

        # 7. end to end at Delta*: liquidate the largest liquidatable borrower, then sell the seized PT
        if delta_star and p.get("end_to_end", True):
            liquidator = Web3.to_checksum_address(Web3.keccak(text=f"lapeg-liquidator-{cfg.seed}")[-20:])
            with fork.branch():
                s = shocked(delta_star["delta"])
                target, acct = max(s["liq"].items(), key=lambda kv: kv[1].collateral)
                need = acct.borrowed + 10**loan_dec
                fork.set_eth_balance(liquidator, 10**20)
                set_erc20_balance(fork, usdc, liquidator, need)
                erc_pt = w3.eth.contract(address=Web3.to_checksum_address(pt), abi=load_abi("ERC20"))
                erc_usdc = w3.eth.contract(address=Web3.to_checksum_address(usdc), abi=load_abi("ERC20"))
                with fork.impersonated(liquidator):
                    erc_usdc.functions.approve(morpho_addr, need).transact({"from": liquidator})
                    rc = w3.eth.wait_for_transaction_receipt(
                        morpho.contract.functions.liquidate(
                            params.as_tuple(), target, 0, acct.borrow_shares, b""
                        ).transact({"from": liquidator, "gas": 3_000_000})
                    )
                seized = int(erc_pt.functions.balanceOf(liquidator).call())
                repaid = need - int(erc_usdc.functions.balanceOf(liquidator).call())
                sale_q = quote(pt, usdc, seized, liquidator)
                sales = [execute_route(fork, r, pt, usdc, seized) for r in sale_q.routes]
                ok = [x for x in sales if x.status == "ok"]
                sale = max(ok, key=lambda x: x.amount_out) if ok else None
                gas_total = int(rc["gasUsed"]) + (sale.gas_used if sale else 0)
                e2e = {
                    "borrower": target,
                    "liquidate_status": int(rc["status"]),
                    "liquidate_gas": int(rc["gasUsed"]),
                    "seized_pt": seized,
                    "repaid_usdc": repaid,
                    "sale_status": sale.status if sale else (sale_q.refusal or "reverted"),
                    "sale_usdc": sale.amount_out if sale else 0,
                    "gas_usd": gas_cost_usd(gas_total, gp),
                    "profit_usdc": ((sale.amount_out if sale else 0) - repaid) / 10**loan_dec
                    - gas_cost_usd(gas_total, gp),
                }

    # acceptance
    ok_rows = [r for r in rows if r["status"] == "ok"]
    smallest = min(ok_rows, key=lambda r: r["amount_in"]) if ok_rows else None
    within_qmax = [
        r
        for r in ok_rows
        if lo is not None and r["amount_in"] <= lo.amount_in and r.get("api_match") is not None
    ]
    viol = il.monotone_violations(points(), price, float(p.get("monotone_tol", 1e-4)))
    checks = {
        "depth_curve_has_points": len(ok_rows) >= 8,
        "g_near_zero_for_tiny_q": smallest is not None
        and abs(smallest["g"]) <= float(p.get("tiny_g_tol", 0.005)),
        "g_non_decreasing": not viol,
        "fork_matches_api_within_qmax": bool(within_qmax)
        and max(abs(r["api_match"]) for r in within_qmax) <= float(p.get("api_match_tol", 0.001)),
        "q_max_bracketed": lo is not None and hi is not None,
        "oracle_override_exact": override_exact,
        "shock_sets_match_position_book": set_mismatch == 0,
        "position_book_passed": bool(book["passed"]),
    }

    def bracket_out(b: tuple[il.DepthPoint | None, il.DepthPoint | None]) -> dict[str, Any]:
        def one(x: il.DepthPoint | None) -> dict[str, Any] | None:
            return (
                None
                if x is None
                else {
                    "amount_pt": x.amount_in / 10**6,
                    "usd_at_oracle": x.amount_in * price / il.ORACLE_PRICE_SCALE / 10**loan_dec,
                }
            )

        return {"last_ok": one(b[0]), "first_fail": one(b[1])}

    borrow_usd = float(borrowers.debt.sum())
    report: dict[str, Any] = {
        "experiment": cfg.name,
        "run_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ"),
        "rpc_source": rpc_source,
        "fork_block": block,
        "block_pinned": True,
        "market": {"name": cfg.market.name, "id": cfg.market.market_id},
        "oracle_price": price / il.ORACLE_PRICE_SCALE,
        "lif": lif / 1e18,
        "bonus_threshold": thr,
        "gas": {
            "base_fee_gwei": gp.base_fee_wei / 1e9,
            "eth_usd": gp.eth_usd,
            "eth_usd_feed": gp.feed,
            "stress_priority_fee_gwei": stress_fee / 1e9,
        },
        "q_max": {k: bracket_out(v) for k, v in brackets.items()},
        "q_max_share_of_borrow": (lo.amount_in * price / il.ORACLE_PRICE_SCALE / 10**loan_dec / borrow_usd)
        if lo
        else None,
        "flash_liquidity_usdc": flash / 10**loan_dec,
        "capacity_per_block_usd": bracket_out(brackets["bonus_gas"])["last_ok"],
        "delta_star": delta_star,
        "shocks": shock_rows,
        "end_to_end": e2e,
        "monotone_violations": viol,
        "n_points": len(rows),
        "n_routes_executed": len(route_rows),
        "sy": {"address": sy, "exchange_rate": str(sy_rate), "decimals": sy_dec},
        "position_book": {
            "n_borrowers": book["n_borrowers"],
            "min_health_factor": book["min_health_factor"],
            "parquet": book.get("parquet"),
        },
        "seconds": round(time.monotonic() - t0, 1),
        "checks": checks,
        "passed": all(checks.values()),
    }
    if write_results:
        out = cfg.path(cfg.results_dir)
        out.mkdir(parents=True, exist_ok=True)
        stem = f"{cfg.name}_{cfg.market.name}_{block}"
        pd.DataFrame(rows).to_parquet(out / f"{stem}_depth.parquet", index=False)
        pd.DataFrame(route_rows).to_parquet(
            out / f"{stem}_routes.parquet", index=False
        )  # calldata: replayable
        pd.DataFrame(shock_rows).to_parquet(out / f"{stem}_shocks.parquet", index=False)
        report["outputs"] = [f"{stem}_depth.parquet", f"{stem}_routes.parquet", f"{stem}_shocks.parquet"]
        (out / f"{cfg.name}_{report['run_utc']}.json").write_text(json.dumps(report, indent=1, default=str))
    report["_depth"] = pd.DataFrame(rows)
    return report
