"""Deterministic binary-contract, next-observation, hold-to-settlement simulator.
No strategy receives settlement results. Historical fills are assumptions, not observations.
"""
from __future__ import annotations
from collections import defaultdict
from decimal import Decimal, ROUND_CEILING
from hashlib import sha256
import json
import math
import random
from .models import Observation, Strategy, BacktestRequest

ENGINE_VERSION = "0.1.0"


def fee(quantity: int, price: float, coefficient: float = .07) -> float:
    p = Decimal(str(price))
    return float((Decimal(str(coefficient)) * quantity * p * (1-p)).quantize(Decimal(".01"), rounding=ROUND_CEILING))


def validate_rows(raw: list[dict]) -> list[Observation]:
    if not 2 <= len(raw) <= 50000:
        raise ValueError("A dataset must contain 2 to 50,000 observations")
    rows = [Observation.model_validate(r) for r in raw]
    seen, contracts = set(), {}
    for r in rows:
        key = (r.ticker, r.available_at)
        if key in seen:
            raise ValueError(f"Duplicate timestamp for {r.ticker}")
        seen.add(key)
        definition = (r.outcome, r.settled_at, r.event_id, r.category)
        if r.ticker in contracts and contracts[r.ticker] != definition:
            raise ValueError(f"Inconsistent settlement or event metadata for {r.ticker}")
        contracts[r.ticker] = definition
    return sorted(rows, key=lambda x: (x.available_at, x.ticker))


def signal(row: Observation, s: Strategy, coefficient: float) -> bool:
    # Explicit feature selection: do not expose outcome or settlement time to strategy logic.
    if s.category != "All" and row.category != s.category:
        return False
    if row.volume < s.min_volume:
        return False
    if not s.min_probability <= row.yes_ask <= s.max_probability:
        return False
    if s.family == "model_edge":
        if row.model_probability is None:
            return False
        p = row.model_probability if s.side == "yes" else 1-row.model_probability
        price = row.yes_ask if s.side == "yes" else 1-row.yes_bid
        return p-price-coefficient*price*(1-price) >= s.min_edge
    return True


def bootstrap_events(trades: list[dict], seed: int = 1047) -> list[float] | None:
    grouped = defaultdict(float)
    for t in trades:
        grouped[t["event_id"]] += t["pnl"]
    values = list(grouped.values())
    if len(values) < 2:
        return None
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(values, k=len(values))) / len(values) for _ in range(800))
    return [round(means[20], 4), round(means[779], 4)]


def simulate(raw: list[dict], request: BacktestRequest, source: str = "upload") -> dict:
    rows = validate_rows(raw)
    cash = float(request.capital)
    s = request.strategy
    positions, previous, traded, trades, curve = {}, {}, set(), [], []
    capital_peak, max_drawdown, fees_paid, skipped = cash, 0., 0., 0
    begin = request.start or rows[0].available_at
    finish = request.end or max(r.settled_at for r in rows)
    events, settlements = [], {}
    for r in rows:
        if begin <= r.available_at <= finish:
            events.append((r.available_at, 1, r.ticker, r))
            settlements[r.ticker] = r
    for ticker, r in settlements.items():
        if r.settled_at <= finish:
            events.append((r.settled_at, 0, ticker, r))
    events.sort(key=lambda e: (e[0], e[1], e[2]))
    curve.append({"time": begin.isoformat(), "equity": cash, "cash": cash, "committed": 0})
    for when, kind, ticker, r in events:
        if kind == 0:
            if ticker in positions:
                pos = positions.pop(ticker)
                payout = pos["quantity"] if r.outcome == s.side else 0
                cash = round(cash+payout, 8)
                trades.append({**pos, "settled_at": when.isoformat(), "outcome": r.outcome,
                    "payout": payout, "pnl": round(payout-pos["cost"], 4)})
        else:
            if ticker in positions:
                positions[ticker]["mark"] = r.yes_bid if s.side == "yes" else 1-r.yes_ask
            prev = previous.get(ticker)
            previous[ticker] = r
            # Signals use ONLY the earlier completed observation. No same-bar execution.
            if prev and ticker not in traded and signal(prev, s, request.fee_coefficient):
                if (r.available_at-prev.available_at).total_seconds() > 86400:
                    skipped += 1
                    continue
                price = round((r.yes_ask if s.side == "yes" else 1-r.yes_bid)+request.slippage, 6)
                if not 0 < price < 1:
                    skipped += 1
                    continue
                open_cost = sum(p["cost"] for p in positions.values())
                event_cost = sum(p["cost"] for p in positions.values() if p["event_id"] == r.event_id)
                # Fixed starting-capital risk budgets avoid sizing off unknown settlement results.
                fraction = s.risk_fraction
                if s.sizing == "quarter_kelly":
                    probability = prev.model_probability if s.side == "yes" else 1-prev.model_probability
                    fraction = min(fraction, max(0., .25*(probability-price-request.fee_coefficient*price*(1-price))/(1-price)))
                budget = min(cash, request.capital*fraction, request.capital*s.event_cap-event_cost,
                    request.capital*s.total_cap-open_cost)
                # A volume participation cap is a proxy, NOT observed available resting depth.
                capacity = math.floor(r.quote_size if r.quote_size is not None else r.volume*request.participation)
                quantity = min(capacity, math.floor(max(0., budget)/price))
                while quantity > 0 and quantity*price+fee(quantity, price, request.fee_coefficient) > budget+1e-9:
                    quantity -= 1
                if quantity <= 0:
                    skipped += 1
                    continue
                cost_fee = fee(quantity, price, request.fee_coefficient)
                cost = round(quantity*price+cost_fee, 8)
                cash = round(cash-cost, 8)
                fees_paid += cost_fee
                positions[ticker] = {"ticker": ticker, "event_id": r.event_id, "category": r.category,
                    "side": s.side, "quantity": quantity, "price": price, "fee": cost_fee, "cost": cost,
                    "signal_at": prev.available_at.isoformat(), "entered_at": when.isoformat(),
                    "mark": r.yes_bid if s.side == "yes" else 1-r.yes_ask}
                traded.add(ticker)
        equity = cash+sum(p["quantity"]*p["mark"] for p in positions.values())
        capital_peak = max(capital_peak, equity)
        max_drawdown = max(max_drawdown, (capital_peak-equity)/capital_peak)
        curve.append({"time": when.isoformat(), "equity": round(equity, 4), "cash": round(cash, 4),
            "committed": round(sum(p["cost"] for p in positions.values()), 4)})
    wins = sum(t["pnl"] > 0 for t in trades)
    losses = sum(t["pnl"] for t in trades if t["pnl"] < 0)
    gains = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    final = curve[-1]["equity"]
    warnings = [
        "Research simulation, not evidence of executable historical profit.",
        "Next-observation fills, hold to settlement; no queue position, latency, or market impact model.",
        "Fee coefficient is a configurable estimate. Verify historical series-specific schedules.",
        "Equity is marked to observed bids, before hypothetical exit fees; risk caps use starting capital.",
        "Settled-contract datasets have selection bias. Imported market rules may be present-day revisions.",
        "Bootstrap intervals cluster by event, not shared weather systems, teams or other hidden dependencies."]
    if source == "synthetic":
        warnings.insert(0, "SYNTHETIC FIXTURE: every observation and outcome was generated. No investment evidence.")
    if any(r.quote_size is None for r in rows):
        warnings.append("No historical depth: available quantity is approximated by bar-volume participation.")
    if len({t["event_id"] for t in trades}) < 30:
        warnings.append("Fewer than 30 independent event IDs; insufficient sample for a reliable edge claim.")
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    # Keep endpoints even when downsampling visual history.
    step = max(1, len(curve)//600)
    displayed = curve[::step]
    if displayed[-1] != curve[-1]:
        displayed.append(curve[-1])
    return {"engine_version": ENGINE_VERSION, "dataset_hash": sha256(canonical.encode()).hexdigest(),
        "source": source, "config": request.model_dump(mode="json"), "warnings": warnings,
        "metrics": {"starting_capital": request.capital, "ending_equity": round(final, 4),
            "net_pnl": round(final-request.capital, 4), "return_pct": round(100*(final/request.capital-1), 4),
            "max_drawdown_pct": round(100*max_drawdown, 4), "closed_trades": len(trades),
            "open_positions": len(positions), "win_rate": round(wins/len(trades)*100, 2) if trades else None,
            "fees": round(fees_paid, 4), "profit_factor": round(gains/abs(losses), 3) if losses else None,
            "independent_events": len({t["event_id"] for t in trades}), "skipped_entries": skipped,
            "event_pnl_ci95": bootstrap_events(trades)}, "equity_curve": displayed,
        "trades": trades, "open_positions": list(positions.values())}
