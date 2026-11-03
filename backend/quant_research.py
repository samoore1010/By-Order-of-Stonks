"""Generic, reproducible historical calibration and event-driven trading studies.

This is a hypothesis evaluation engine, not a predictive alpha model.
Never claim historical candle quotes were actually executable.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import math
import random

from .engine import fee

MODELS = {
    "buy_yes": "Buy YES at the observed ask",
    "buy_no": "Buy NO at the complement of the observed YES bid",
    "against_longshots": "Buy NO against YES quotes priced 2–15 cents",
    "buy_longshots": "Buy YES quotes priced 2–15 cents",
    "buy_favorites": "Buy YES quotes priced 70–95 cents",
}
DEFAULT_DAYS_BEFORE = 2
MIN_EVENTS_FOR_INFERENCE = 30


def subtype(market: dict) -> tuple[str, str]:
    """Identify concepts without requiring any domain-specific preset for selection.

    These tags are hints inferred from series titles. Never promote them to fact.
    """
    metadata = market.get("raw") or {}
    text = " ".join(str(x or "") for x in (
        market.get("title"), market.get("event_title"),
        metadata.get("series_title"), metadata.get("title"),
        metadata.get("subtitle"), metadata.get("yes_sub_title"),
        metadata.get("market_ticker"),
    )).lower()
    if any(w in text for w in ("passing yards", "rushing yards", "receiving yards",
                                "player prop", "touchdowns", "strikeouts", "rebounds",
                                "player points", "assists", "shots on goal")):
        return "Player performance", "inferred"
    if any(w in text for w in ("spread", "point differential", "margin of victory", "win by")):
        return "Margin / spread", "inferred"
    if any(w in text for w in ("moneyline", "match winner", "game winner", "to win the game")):
        return "Match winner", "inferred"
    return (market.get("category") or "Unclassified"), "provider category"


def entry_snapshot(market: dict, days_before: int = DEFAULT_DAYS_BEFORE):
    """Select a historical quote before decision time; refuse too-stale observations."""
    if market.get("result") not in ("yes", "no"):
        return None
    settled = market.get("settled_at")
    if not settled:
        return None
    settlement = datetime.fromisoformat(settled)
    target = settlement - timedelta(days=days_before)
    selected = None
    for bar in market.get("bars", []):
        at = datetime.fromisoformat(bar["asof"])
        if at <= target and (selected is None or at > datetime.fromisoformat(selected["asof"])):
            selected = bar
    if selected is None:
        return None
    age = (target - datetime.fromisoformat(selected["asof"])).total_seconds()
    # One daily quote may be 24h old. Three days is a bounded staleness tolerance.
    if age > 72 * 3600:
        return None
    bid, ask = selected.get("yes_bid"), selected.get("yes_ask")
    if bid is None or ask is None or not (0 <= bid <= ask <= 1):
        return None
    mark = (bid + ask) / 2
    group, provenance = subtype(market)
    return {
        "ticker": market["ticker"],
        "event_id": market["event_id"],
        "series_ticker": market["series_ticker"],
        "category": market.get("category") or "Unclassified",
        "type": group,
        "type_provenance": provenance,
        "title": market["title"],
        "result": market["result"],
        "yes_bid": bid,
        "yes_ask": ask,
        "mid": mark,
        "volume": selected.get("volume") or 0,
        "available_at": selected["asof"],
        "settled_at": settled,
        "age_hours": round(age / 3600, 2),
    }


def samples(markets: list[dict], days_before=DEFAULT_DAYS_BEFORE):
    return sorted(
        [r for m in markets if (r := entry_snapshot(m, days_before)) is not None],
        key=lambda row: (row["available_at"], row["ticker"])
    )


def _group_confidence(observations, seed=1709):
    by_event = defaultdict(list)
    for x in observations:
        by_event[x["event_id"]].append(x["actual"] - x["mid"])
    values = [sum(xs)/len(xs) for xs in by_event.values()]
    if len(values) < 2:
        return None
    rng = random.Random(seed)
    draws = sorted(sum(rng.choices(values, k=len(values))) / len(values)
                   for _ in range(800))
    return [round(draws[19], 4), round(draws[779], 4)]


def calibration(rows: list[dict]) -> dict:
    """Empirical event frequencies versus observed historical midprices."""
    bins = []
    for i in range(10):
        segment = [r for r in rows if i/10 <= r["mid"] <
                   ((i+1)/10 if i < 9 else 1.00001)]
        if not segment:
            continue
        n = len(segment)
        actual = sum(r["result"] == "yes" for r in segment)/n
        implied = sum(r["mid"] for r in segment)/n
        bins.append({
            "range": f"{i*10}–{(i+1)*10}%",
            "contracts": n,
            "events": len({r["event_id"] for r in segment}),
            "mean_quoted_probability": round(implied, 4),
            "observed_yes_frequency": round(actual, 4),
            "calibration_gap": round(actual-implied, 4),
        })
    tagged = [{**r, "actual": int(r["result"] == "yes")} for r in rows]
    brier = sum((r["mid"] - (r["result"] == "yes"))**2 for r in rows)/len(rows) if rows else None
    return {
        "bins": bins,
        "brier_score": round(brier, 5) if brier is not None else None,
        "contracts": len(rows),
        "events": len({r["event_id"] for r in rows}),
        "observed_minus_quoted_ci95": _group_confidence(tagged),
        "note": "Quote midpoints are calibration reference values, not executable prices. Event clusters are used in uncertainty estimates.",
    }


def choose(row: dict, model: str, minimum: float, maximum: float) -> bool:
    yes_ask = row["yes_ask"]
    if model == "against_longshots":
        return .02 <= yes_ask <= .15
    if model == "buy_longshots":
        return .02 <= yes_ask <= .15
    if model == "buy_favorites":
        return .70 <= yes_ask <= .95
    return minimum <= yes_ask <= maximum


def side_for(model: str) -> str:
    return "no" if model in ("buy_no", "against_longshots") else "yes"


def simulate(rows: list[dict], model="buy_yes", capital=10000,
             min_price=0., max_price=1., stake_pct=.01,
             event_cap_pct=.05, portfolio_cap_pct=.30,
             fee_coefficient=.07, slippage=.005,
             participation=.05, min_volume=0) -> dict:
    if model not in MODELS:
        raise ValueError("Unsupported historical trading rule")
    if not (100 <= capital <= 10_000_000 and 0 < stake_pct <= event_cap_pct <= portfolio_cap_pct <= 1):
        raise ValueError("Invalid capital/risk configuration")
    if not (0 <= slippage <= .1 and 0 <= fee_coefficient <= 1 and 0 < participation <= 1):
        raise ValueError("Invalid execution assumptions")
    events = []
    for r in rows:
        if r["volume"] >= min_volume and choose(r, model, min_price, max_price):
            events.append((r["available_at"], 1, r))
            events.append((r["settled_at"], 0, r))
    events.sort(key=lambda e: (e[0], e[1], e[2]["ticker"]))
    cash, open_positions, trades, equity, skipped = float(capital), {}, [], [], defaultdict(int)
    high, drawdown, total_fees = capital, 0., 0.
    for at, kind, r in events:
        if kind == 0:
            pos = open_positions.pop(r["ticker"], None)
            if pos:
                payout = pos["quantity"] if r["result"] == pos["side"] else 0.
                cash += payout
                trades.append({**pos, "payout": payout,
                               "pnl": round(payout - pos["cost"], 4),
                               "result": r["result"], "settled_at": at})
        else:
            if r["ticker"] in open_positions:
                continue
            side = side_for(model)
            price = (r["yes_ask"] if side == "yes" else 1-r["yes_bid"]) + slippage
            if not 0 < price < 1:
                skipped["invalid_price"] += 1
                continue
            # Bar volume is NOT historical resting depth. Conservative proxy only.
            capacity = int(math.floor(r["volume"] * participation))
            if capacity == 0:
                skipped["no_observed_volume"] += 1
                continue
            committed = sum(p["cost"] for p in open_positions.values())
            event_committed = sum(p["cost"] for p in open_positions.values()
                                  if p["event_id"] == r["event_id"])
            budget = min(cash, capital*stake_pct,
                         capital*event_cap_pct-event_committed,
                         capital*portfolio_cap_pct-committed)
            quantity = min(capacity, int(max(0, budget)//price))
            while quantity and quantity*price+fee(quantity, price, fee_coefficient) > budget:
                quantity -= 1
            if not quantity:
                skipped["capital_or_risk_limit"] += 1
                continue
            charge = fee(quantity, price, fee_coefficient)
            cost = quantity*price+charge
            cash -= cost
            total_fees += charge
            open_positions[r["ticker"]] = {
                "ticker": r["ticker"], "event_id": r["event_id"],
                "series_ticker": r["series_ticker"],
                "category": r["category"], "type": r["type"],
                "side": side, "quantity": quantity, "price": round(price, 6),
                "cost": round(cost, 4), "fees": charge, "entered_at": at,
            }
        # No future outcome is used to mark an open position as profitable.
        # Conservative ledger shows cash and committed cost, not synthetic marks.
        book_value = cash + sum(p["cost"] for p in open_positions.values())
        high = max(high, book_value)
        drawdown = max(drawdown, (high-book_value)/high if high else 0)
        equity.append({"time": at, "equity_at_cost": round(book_value, 2),
                       "cash": round(cash, 2),
                       "committed": round(book_value-cash, 2)})
    total = sum(t["pnl"] for t in trades)
    by_event = defaultdict(float)
    for t in trades:
        by_event[t["event_id"]] += t["pnl"]
    values = list(by_event.values())
    ci = None
    if len(values) > 1:
        rng = random.Random(113)
        boot = sorted(sum(rng.choices(values, k=len(values)))/len(values)
                      for _ in range(800))
        ci = [round(boot[19], 4), round(boot[779], 4)]
    return {
        "model": model, "description": MODELS[model],
        "trades": trades[-250:],
        "total_trades": len(trades),
        "event_count": len(by_event),
        "net_pnl": round(total, 2),
        "pnl_pct_of_starting_capital": round(100*total/capital, 3),
        "fees": round(total_fees, 2),
        "committed_open": round(sum(p["cost"] for p in open_positions.values()), 2),
        "ending_cash": round(cash, 2),
        "win_rate": round(sum(t["pnl"]>0 for t in trades)/len(trades)*100, 2) if trades else None,
        "drawdown_at_cost_pct": round(100*drawdown, 3),
        "event_pnl_mean_ci95": ci,
        "skipped": dict(skipped),
        "equity": equity[::max(1, len(equity)//250)][-250:],
        "warning": "Hypothetical next-bar-style resting quote fill. No historical depth, queues, impact, maker rebates or verified fill. Costs are estimates. Open commitments shown at cost, not marked-to-market; drawdown is not economic liquidation drawdown.",
    }


def study(markets: list[dict], model="against_longshots", compare_by="market_type",
          days_before=2, capital=10000, min_price=0., max_price=1., min_volume=0.) -> dict:
    rows = [r for r in samples(markets, days_before=days_before)
            if r["volume"] >= min_volume and min_price <= r["yes_ask"] <= max_price]
    if not rows:
        return {
            "status": "insufficient_data", "observations": 0,
            "limitations": ["No valid historical quotes available at the chosen decision horizon.",
                            "Only finalized binary settlements with usable bid/ask candle quotes can be studied."],
            "groups": [], "overall": None,
        }
    groups = defaultdict(list)
    for r in rows:
        key = (r["type"] if compare_by == "market_type" else
               r["category"] if compare_by == "category" else
               r["series_ticker"])
        groups[key].append(r)
    summaries = []
    for group, values in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        cal = calibration(values)
        perf = simulate(values, model=model, capital=capital, min_price=min_price,
                        max_price=max_price, min_volume=min_volume)
        summaries.append({
            "group": group,
            "classification": sorted({r["type_provenance"] for r in values}),
            "n_contracts": len(values),
            "n_events": cal["events"],
            "calibration": cal,
            "simulation": {k: v for k, v in perf.items() if k not in ("trades", "equity")},
            "quality": "limited" if cal["events"] < MIN_EVENTS_FOR_INFERENCE else "descriptive",
        })
    overall_cal = calibration(rows)
    overall_sim = simulate(rows, model=model, capital=capital, min_price=min_price,
                           max_price=max_price, min_volume=min_volume)
    return {
        "status": "descriptive" if overall_cal["events"] >= MIN_EVENTS_FOR_INFERENCE else "limited_sample",
        "observations": len(rows),
        "independent_event_ids": overall_cal["events"],
        "model": model,
        "price_band": [min_price, max_price], "minimum_observed_volume": min_volume,
        "strategy_description": MODELS[model],
        "entry_rule": f"Latest daily candle no later than {days_before} day(s) before settlement, max 72h staleness",
        "compare_by": compare_by,
        "groups": summaries,
        "overall": {"calibration": overall_cal, "simulation": overall_sim},
        "limitations": [
            "Descriptive comparisons cannot prove a trading edge, and markets in the sample may not represent the whole exchange.",
            "Market-type labels may be inferred from contract text. Unclassified markets remain visible.",
            "Event IDs are not fully independent where events share underlying causes.",
            "Historical quote candles do not prove that a fill was available at the simulated price or size.",
            "Results exclude canceled, missing and nonstandard settlements; this selection can bias returns.",
            "The same strategy settings apply to all groups; profitability of market types depends on the strategy.",
            "Historical fee schedules and spread availability may differ from the model assumptions.",
        ],
    }
