"""Shared workbench services. Research, paper deployments and UI use the same records."""
from __future__ import annotations
import asyncio
import hashlib
import json
import logging
import math
import os
import threading
from datetime import datetime, timezone
from .store import Store
from .models import Strategy, BacktestRequest, ResearchRequest, ImportRequest, PaperOrder, Schedule, now
from .engine import simulate, validate_rows
from . import fixtures, paper
from .providers import Kalshi, parse_book


class CancelledJob(Exception):
    pass


class Services:
    def __init__(self, store: Store | None = None):
        self.store = store or Store()
        self.kalshi = Kalshi()
        self.lock = threading.RLock()
        self.paper_lock = asyncio.Lock()
        self.copilot_lock = asyncio.Lock()
        self.worker_heartbeat = now()
        self.initialize()

    def initialize(self):
        if not self.store.get("synthetic-v1"):
            self.store.write("dataset", fixtures.dataset(), "synthetic-v1")
        if not self.store.get("strategy-longshot-v1"):
            self.save_strategy(Strategy(), "native", "strategy-longshot-v1")
            self.save_strategy(Strategy(name="Independent forecast edge", family="model_edge", side="yes",
                min_probability=0, max_probability=1), "native", "strategy-forecast-v1")
        for source in ("synthetic", "kalshi"):
            id = "paper-"+source
            if not self.store.get(id):
                self.store.write("account", {**paper.account(source), "environment": self.kalshi.environment}, id)
            elif source == "kalshi" and self.store.get(id).get("environment") != self.kalshi.environment:
                raise ValueError("Use a separate database for a different Kalshi environment")
        if not self.store.get("schedule"):
            self.store.write("setting", Schedule().model_dump(), "schedule")
        for j in self.store.list("job", 1000):
            if j["status"] == "running":
                self.store.write("job", {**j, "status": "interrupted", "error": "Process restarted. Review and retry."}, j["id"])
        if not self.store.list("run", 1):
            self.backtest(BacktestRequest().model_dump(mode="json"))

    def audit(self, action: str, detail: dict):
        self.store.write("audit", {"action": action, "detail": detail})

    def dataset(self, id: str) -> dict:
        d = self.store.get(id)
        if not d or "rows" not in d:
            raise ValueError("Dataset not found")
        return d

    def save_strategy(self, config: Strategy, origin="user", id=None, parent_id=None):
        parent = self.store.get(parent_id) if parent_id else None
        saved = self.store.write("strategy", {"config": config.model_dump(), "version": (parent or {}).get("version", 0)+1,
            "parent_id": parent_id, "origin": origin, "status": "research"}, id)
        return saved

    def enqueue(self, job_type: str, payload: dict) -> dict:
        if job_type not in ("research", "backtest", "import"):
            raise ValueError("Unsupported job type")
        with self.lock:
            if sum(j["status"] == "queued" for j in self.store.list("job", 200)) >= 20:
                raise ValueError("Queue full; wait for a job to finish")
            return self.store.write("job", {"job_type": job_type, "payload": payload, "status": "queued",
                "stage": "Queued", "events": [], "result_id": None, "error": None})

    def stage(self, id: str, role: str, message: str, execution: str = "deterministic"):
        with self.lock:
            j = self.store.get(id)
            if j["status"] == "cancelled":
                raise CancelledJob()
            self.store.write("job", {**j, "stage": role, "events": j["events"]+[
                {"role": role, "message": message, "at": now(), "execution": execution}]}, id)

    def backtest(self, payload: dict) -> dict:
        req = BacktestRequest.model_validate(payload)
        d = self.dataset(req.dataset_id)
        result = simulate(d["rows"], req, d["source"])
        return self.store.write("run", {**result, "dataset_name": d["name"]})

    def research(self, id: str, payload: dict) -> dict:
        req = ResearchRequest.model_validate(payload)
        d = self.dataset(req.dataset_id)
        rows = validate_rows(d["rows"])
        self.stage(id, "Director", "Bounded hypothesis test using the selected strategy rules. The research question labels the experiment, not arbitrary code.")
        groups = {}
        for r in rows:
            g = groups.setdefault(r.event_id, {"start": r.available_at, "end": r.settled_at})
            g["start"], g["end"] = min(g["start"], r.available_at), max(g["end"], r.settled_at)
        timeline = sorted(groups, key=lambda k: groups[k]["start"])
        if len(timeline) < 10:
            raise ValueError("Research validation needs at least 10 distinct event IDs")
        first, second = [groups[timeline[int(len(timeline)*f)]]["start"] for f in (.6, .8)]
        partitions = {"training": {k for k, g in groups.items() if g["end"] < first},
            "validation": {k for k, g in groups.items() if g["start"] >= first and g["end"] < second},
            "test": {k for k, g in groups.items() if g["start"] >= second}}
        split = {name: [r.model_dump(mode="json") for r in rows if r.event_id in keys] for name, keys in partitions.items()}
        if any(len(v) < 2 for v in split.values()):
            raise ValueError("Insufficient observations after purging overlapping settlement horizons")
        purged = len(groups)-sum(len(v) for v in partitions.values())
        self.stage(id, "Scout", f"{len(groups)} event IDs; {purged} purged at chronological boundaries. No event ID crosses partitions.")
        candidates = [req.strategy]
        if req.strategy.family == "longshot":
            candidates = [req.strategy.model_copy(update={"max_probability": x}) for x in [.05, .10, .15, .25]
                if x >= req.strategy.min_probability] or [req.strategy]
        results = [simulate(split["training"], BacktestRequest(dataset_id=req.dataset_id, strategy=s), d["source"]) for s in candidates]
        best = max(results, key=lambda r: r["metrics"]["net_pnl"])
        selected = Strategy.model_validate(best["config"]["strategy"])
        self.stage(id, "Quant Analyst", f"Tested {len(results)} candidates on training data only. Locked the selected rules before testing.")
        validation = simulate(split["validation"], BacktestRequest(dataset_id=req.dataset_id, strategy=selected), d["source"])
        test = simulate(split["test"], BacktestRequest(dataset_id=req.dataset_id, strategy=selected), d["source"])
        stress = simulate(split["test"], BacktestRequest(dataset_id=req.dataset_id, strategy=selected, fee_coefficient=.14, slippage=.01), d["source"])
        self.stage(id, "Validator", "Applied untouched chronological test, doubled fee/slippage assumptions, event-cluster bootstrap and sample-size checks.")
        checks = [
            {"name": "Non-synthetic input", "passed": d["source"] != "synthetic"},
            {"name": "At least 30 held-out event IDs", "passed": test["metrics"]["independent_events"] >= 30},
            {"name": "Positive validation and test P&L", "passed": validation["metrics"]["net_pnl"] > 0 and test["metrics"]["net_pnl"] > 0},
            {"name": "Positive stressed test P&L", "passed": stress["metrics"]["net_pnl"] > 0},
            {"name": "Positive bootstrap lower bound", "passed": bool(test["metrics"]["event_pnl_ci95"] and test["metrics"]["event_pnl_ci95"][0] > 0)}]
        report = self.store.write("run", {**test, "dataset_name": d["name"]+" · held-out test"})
        self.stage(id, "Risk Review", "No automatic live eligibility. Historical depth, selection bias and multiple-testing review remain required.")
        return self.store.write("research", {"question": req.question, "dataset_id": req.dataset_id, "source": d["source"],
            "strategy": selected.model_dump(), "run_id": report["id"], "trials": len(results), "purged_events": purged,
            "candidate_results": [{"strategy": r["config"]["strategy"], "metrics": r["metrics"]} for r in results],
            "checks": checks, "status": "needs_execution_evidence" if all(c["passed"] for c in checks) else "not_validated",
            "partitions": {"training": best["metrics"], "validation": validation["metrics"], "test": test["metrics"], "stress": stress["metrics"]},
            "limitations": ["Bounded template research, not a general autonomous forecasting desk.",
                "Repeated tests and hidden event correlations require additional review.", "No live eligibility can be granted by this release."]})

    async def markets(self, source="synthetic", series="", cursor=""):
        if source == "synthetic":
            rows = fixtures.markets()
            settled = {s["ticker"]: s for s in self.store.list("sandbox_settlement", 100)}
            rows = [{**m, **settled.get(m["ticker"], {})} for m in rows]
            return {"markets": rows, "cursor": "", "source": source, "fetched_at": now(), "coverage": "Six explicitly synthetic fixtures"}
        if source != "kalshi":
            raise ValueError("Unknown source")
        result = await self.kalshi.markets(series, cursor)
        self.store.write("snapshot", result)
        return result

    async def quote(self, ticker: str, source: str):
        if source == "synthetic":
            market = next((m for m in (await self.markets())["markets"] if m["ticker"] == ticker), None)
            if not market:
                raise ValueError("Synthetic ticker not found")
            book = parse_book({"orderbook_fp": {"yes_dollars": [[market["yes_bid"], 200]],
                "no_dollars": [[round(1-market["yes_ask"], 6), 200]]}})
        elif source == "kalshi":
            market = await self.kalshi.market(ticker)
            book = await self.kalshi.book(ticker)
            self.store.write("quote", {"ticker": ticker, "source": source, "market": market, "book": book})
        else:
            raise ValueError("Unknown source")
        return {"market": market, "book": book}

    async def order(self, request: PaperOrder):
        async with self.paper_lock:
            existing = self.store.get("order-"+request.client_order_id)
            if existing:
                digest = hashlib.sha256(json.dumps(request.model_dump(), sort_keys=True).encode()).hexdigest()
                if existing.get("request_digest") != digest:
                    raise ValueError("Order ID already used for a different request")
                return existing
            q = await self.quote(request.ticker, request.source)
            state, order = paper.execute(self.store.get("paper-"+request.source), request, q["market"], q["book"])
            saved = self.store.write_many([("account", state, "paper-"+request.source),
                ("paper_order", order, "order-"+request.client_order_id)])
            self.audit("paper_order", {"id": request.client_order_id, "source": request.source, "status": order["status"]})
            return saved[1]

    async def reconcile(self, source: str):
        async with self.paper_lock:
            state = self.store.get("paper-"+source)
            if not state:
                raise ValueError("Unknown paper account")
            values, errors = {}, []
            for t in {p["ticker"] for p in state["positions"]}:
                try:
                    values[t] = (await self.quote(t, source))["market"] if source == "synthetic" else await self.kalshi.market(t)
                except ValueError as exc:
                    errors.append({"ticker": t, "error": str(exc)})
            updated, settlements = paper.settle(state, values)
            self.store.write_many([("account", updated, "paper-"+source)]+[("settlement", s, None) for s in settlements])
            return {"settled": len(settlements), "errors": errors, "account": updated}

    async def scan_deployments(self):
        for dep in self.store.list("deployment", 100):
            if not dep["enabled"]:
                continue
            try:
                strategy = Strategy.model_validate(dep["strategy"])
                data = await self.markets(dep["source"], dep.get("series", ""))
                orders = []
                for m in data["markets"]:
                    if not m.get("binary_supported") or m["status"] not in ("open", "active") or m["yes_ask"] is None:
                        continue
                    if strategy.category != "All" and m["category"] != strategy.category:
                        continue
                    if not strategy.min_probability <= m["yes_ask"] <= strategy.max_probability or m["volume"] < strategy.min_volume:
                        continue
                    oid = "auto-"+hashlib.sha256((dep["id"]+m["ticker"]).encode()).hexdigest()[:40]
                    account = self.store.get("paper-"+dep["source"])
                    if self.store.get("order-"+oid) or any(p["ticker"] == m["ticker"] for p in account["positions"]):
                        continue
                    price = m["yes_ask"] if strategy.side == "yes" else 1-m["yes_bid"] if m["yes_bid"] is not None else None
                    if price is None or not 0 < price < 1:
                        continue
                    event_cost = sum(p["cost"] for p in account["positions"] if p["event_id"] == m["event_id"])
                    total_cost = sum(p["cost"] for p in account["positions"])
                    budget = min(account["cash"], account["initial_capital"]*min(strategy.risk_fraction, .01),
                        account["initial_capital"]*strategy.event_cap-event_cost,
                        account["initial_capital"]*strategy.total_cap-total_cost)
                    n = math.floor(max(0, budget)/(price+.0175))
                    if n < 1:
                        continue
                    order = await self.order(PaperOrder(client_order_id=oid, ticker=m["ticker"], side=strategy.side,
                        quantity=min(n, 10000), limit_price=price, source=dep["source"], confirm=True))
                    orders.append(order["id"])
                    if len(orders) >= 5:
                        break
                latest = self.store.get(dep["id"])
                self.store.write("deployment", {**latest, "last_scan": now(), "last_orders": orders, "error": None,
                    "coverage": data["coverage"]}, dep["id"])
            except Exception as exc:
                latest = self.store.get(dep["id"])
                self.store.write("deployment", {**latest, "last_scan": now(), "error": str(exc)[:500]}, dep["id"])

    def overview(self):
        datasets = [{k: v for k, v in d.items() if k not in ("rows", "rules")} | {"row_count": len(d["rows"])} for d in self.store.list("dataset", 100)]
        runs = [{k: v for k, v in r.items() if k not in ("trades", "open_positions", "equity_curve")} for r in self.store.list("run", 40)]
        return {"version": "0.2.0", "strategies": self.store.list("strategy"), "datasets": datasets, "runs": runs,
            "jobs": self.store.list("job", 50), "research": self.store.list("research", 30), "accounts": self.store.list("account"),
            "orders": self.store.list("paper_order", 100), "settlements": self.store.list("settlement", 100),
            "integrations": self.store.list("integration"), "deployments": self.store.list("deployment"),
            "schedule": self.store.get("schedule"), "audit": self.store.list("audit", 30), "worker_heartbeat": self.worker_heartbeat,
            "capabilities": {"live_execution": False, "native_combos": False, "copilot": bool(os.getenv("OPENAI_API_KEY")),
                "agent_llm": bool(os.getenv("OPENAI_API_KEY")) and os.getenv("AGENT_LLM_ENABLED", "false").lower() == "true",
                "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"), "kalshi_environment": self.kalshi.environment,
                "kalshi_credentials_configured": bool(self.kalshi.key), "autonomy": "Bounded template research and opt-in paper scans",
                "paper": "IOC taker simulation; hold to settlement"}}

    def maybe_schedule(self):
        with self.lock:
            config = self.store.get("schedule")
            if not config["enabled"]:
                return
            current = datetime.now(timezone.utc)
            if config.get("last_checked") and (current-datetime.fromisoformat(config["last_checked"])).total_seconds() < config["interval_minutes"]*60:
                return
            jobs = [j for j in self.store.list("job", 2000) if j["created_at"][:10] == current.date().isoformat() and j["payload"].get("question", "").startswith("Scheduled")]
            d = self.dataset(config["dataset_id"])
            fingerprint = hashlib.sha256(json.dumps(d["rows"], sort_keys=True).encode()).hexdigest()
            updates = {**config, "last_checked": now()}
            if len(jobs) < config["max_jobs_daily"] and fingerprint != config.get("last_dataset_hash"):
                self.enqueue("research", ResearchRequest(question="Scheduled longshot calibration review", dataset_id=config["dataset_id"]).model_dump(mode="json"))
                updates.update(last_dataset_hash=fingerprint, last_action="Queued review of changed dataset")
            else:
                updates["last_action"] = "No new dataset content or daily budget reached"
            self.store.write("setting", updates, "schedule")

    async def worker(self):
        last_tick = 0.
        while True:
            try:
                self.worker_heartbeat = now()
                if asyncio.get_running_loop().time()-last_tick > 60:
                    self.maybe_schedule()
                    await self.scan_deployments()
                    last_tick = asyncio.get_running_loop().time()
                queued = [j for j in self.store.list("job", 1000) if j["status"] == "queued"]
                if not queued:
                    await asyncio.sleep(1)
                    continue
                job = queued[-1]
                with self.lock:
                    job = self.store.get(job["id"])
                    if job["status"] != "queued":
                        continue
                    self.store.write("job", {**job, "status": "running", "started_at": now()}, job["id"])
                try:
                    if job["job_type"] == "import":
                        self.stage(job["id"], "Data Collector", "Fetching requested histories from live/archive endpoints.")
                        d = await self.kalshi.import_history(ImportRequest.model_validate(job["payload"]))
                        self.stage(job["id"], "Data Collector", f"Validated {len(d['rows'])} observations. Coverage/errors retained.")
                        result = self.store.write("dataset", d)
                    elif job["job_type"] == "research":
                        from .agents import plan, review, enabled
                        payload = await plan(self, job) if enabled() else job["payload"]
                        result = await asyncio.to_thread(self.research, job["id"], payload)
                        if enabled():
                            result = await review(self, job["id"], result)
                    else:
                        self.stage(job["id"], "Backtester", "Running deterministic next-observation simulation.")
                        result = await asyncio.to_thread(self.backtest, job["payload"])
                    with self.lock:
                        current = self.store.get(job["id"])
                        if current["status"] != "cancelled":
                            self.store.write("job", {**current, "status": "completed", "result_id": result["id"], "finished_at": now()}, job["id"])
                except CancelledJob:
                    pass
                except Exception as exc:
                    with self.lock:
                        current = self.store.get(job["id"])
                        if current["status"] != "cancelled":
                            self.store.write("job", {**current, "status": "failed", "error": str(exc)[:1600], "finished_at": now()}, job["id"])
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.exception("Research worker error")
                await asyncio.sleep(3)
