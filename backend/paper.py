"""Cash-only, IOC paper simulator. No real exchange orders. Serialized by the API."""
from __future__ import annotations
import hashlib
import json
import math
from datetime import datetime, timezone
from .models import PaperOrder, now
from .engine import fee


def account(source: str) -> dict:
    return {"source": source, "initial_capital": 10000., "cash": 10000., "positions": [],
        "realized_pnl": 0., "fees": 0., "consumed": {}, "halted": False,
        "limits": {"contract_fraction": .02, "event_fraction": .05, "total_fraction": .3},
        "mode": "paper"}


def execute(state: dict, request: PaperOrder, market: dict, book: dict) -> tuple[dict, dict]:
    if not request.confirm:
        raise ValueError("Explicit paper-order confirmation required")
    if state["halted"]:
        raise ValueError("Paper trading is paused")
    if request.source != state["source"] or market["source"] != state["source"]:
        raise ValueError("Data sources cannot be mixed in one paper account")
    if market["ticker"] != request.ticker or market["status"] not in ("open", "active"):
        raise ValueError("Market is not open")
    if market.get("close_time") and datetime.fromisoformat(market["close_time"].replace("Z", "+00:00")) <= datetime.now(timezone.utc):
        raise ValueError("Market close time has passed")
    if not market.get("binary_supported"):
        raise ValueError("Only ordinary $1 binary markets supported. Combos and other payouts are blocked.")
    age = (datetime.now(timezone.utc)-datetime.fromisoformat(book["received_at"].replace("Z", "+00:00"))).total_seconds()
    if not 0 <= age <= 10:
        raise ValueError("Quote snapshot is stale; request a fresh book")
    # Copy state so any failure leaves the persisted account untouched.
    state = json.loads(json.dumps(state))
    positions = state["positions"]
    contract_cost = sum(p["cost"] for p in positions if p["ticker"] == request.ticker)
    event_cost = sum(p["cost"] for p in positions if p["event_id"] == market["event_id"])
    total_cost = sum(p["cost"] for p in positions)
    limits, initial = state["limits"], state["initial_capital"]
    worst_fee = math.ceil(.07*request.quantity*.25*100)/100
    reserve = request.quantity*request.limit_price+worst_fee
    if reserve > min(state["cash"], initial*limits["contract_fraction"]-contract_cost,
                     initial*limits["event_fraction"]-event_cost, initial*limits["total_fraction"]-total_cost)+1e-9:
        raise ValueError("Order exceeds available cash or contract/event/portfolio exposure limits")
    key = request.ticker+":"+request.side
    consumed = state["consumed"].get(key, {})
    used = consumed.get("levels", {}) if consumed.get("fingerprint") == book["fingerprint"] else {}
    remaining, fills = request.quantity, []
    for price, available in book[request.side]:
        if price <= 0 or price >= 1 or price > request.limit_price or remaining <= 0:
            continue
        level_key = f"{price:.6f}"
        size = min(remaining, max(0, math.floor(available)-used.get(level_key, 0)))
        if not size:
            continue
        f = fee(size, price)
        fills.append({"price": price, "quantity": size, "fee": f, "cost": round(size*price+f, 8)})
        remaining -= size
        used[level_key] = used.get(level_key, 0)+size
    cost = round(sum(f["cost"] for f in fills), 8)
    total_fee = round(sum(f["fee"] for f in fills), 4)
    # Per-level rounding can exceed the conservative reservation for fragmented fills.
    if cost > min(state["cash"], initial*limits["contract_fraction"]-contract_cost,
                  initial*limits["event_fraction"]-event_cost, initial*limits["total_fraction"]-total_cost)+1e-9:
        raise ValueError("Actual modeled fill fees would breach a risk limit")
    quantity = request.quantity-remaining
    state["cash"] = round(state["cash"]-cost, 8)
    state["fees"] = round(state["fees"]+total_fee, 4)
    state["consumed"][key] = {"fingerprint": book["fingerprint"], "levels": used}
    if quantity:
        positions.append({"order_id": request.client_order_id, "ticker": request.ticker,
            "event_id": market["event_id"], "title": market["title"], "side": request.side,
            "quantity": quantity, "cost": cost, "fee": total_fee, "entered_at": now(), "source": request.source})
    digest = hashlib.sha256(json.dumps(request.model_dump(), sort_keys=True).encode()).hexdigest()
    order = {**request.model_dump(), "request_digest": digest, "mode": "paper", "time_in_force": "IOC",
        "status": "filled" if remaining == 0 else "partially_filled" if quantity else "unfilled",
        "filled_quantity": quantity, "cancelled_quantity": remaining, "cost": cost, "fees": total_fee,
        "fills": fills, "received_at": book["received_at"], "executed_at": now(),
        "warning": "Simulated taker fills at fetched displayed depth. No queue, latency or hidden-liquidity model. Fees estimated, not exchange-confirmed."}
    return state, order


def settle(state: dict, markets: dict[str, dict]) -> tuple[dict, list[dict]]:
    state = json.loads(json.dumps(state))
    remaining, settlements = [], []
    for p in state["positions"]:
        m = markets.get(p["ticker"], {})
        if m.get("status") not in ("settled", "finalized") or m.get("result") not in ("yes", "no"):
            remaining.append(p)
            continue
        value = m.get("settlement_value")
        expected = 1 if m["result"] == "yes" else 0
        if not m.get("binary_supported") or value != expected:
            remaining.append(p)
            continue
        payout = p["quantity"] if p["side"] == m["result"] else 0
        pnl = round(payout-p["cost"], 8)
        state["cash"] = round(state["cash"]+payout, 8)
        state["realized_pnl"] = round(state["realized_pnl"]+pnl, 8)
        settlements.append({**p, "payout": payout, "pnl": pnl, "settled_at": m.get("settlement_ts"), "reconciled_at": now()})
    state["positions"] = remaining
    return state, settlements
