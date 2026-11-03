"""Private single-user application. Production fails closed without authentication."""
from __future__ import annotations
import asyncio
import contextlib
import csv
import hashlib
import io
import json
import os
import re
import secrets
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
import httpx
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import JSONResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import URLSafeTimedSerializer, BadSignature
from pydantic import Field
from .models import Strict, Strategy, BacktestRequest, ResearchRequest, ImportRequest, PaperOrder, Schedule, now
from .engine import validate_rows
from .service import Services
from .providers import weather_forecast
from . import copilot

ROOT = Path(__file__).resolve().parent.parent


class Login(Strict):
    password: str = Field(max_length=1000)


class StrategySave(Strict):
    config: Strategy
    parent_id: str | None = None
    origin: str = Field(default="user", max_length=100)


class DatasetUpload(Strict):
    name: str = Field(min_length=1, max_length=160)
    rows: list[dict] = Field(min_length=2, max_length=50000)
    provenance: str = Field(min_length=5, max_length=4000)
    synthetic: bool = False


class ChatRequest(Strict):
    message: str = Field(min_length=1, max_length=4000)
    context: dict[str, str] = Field(default_factory=dict)
    session_id: str = Field(pattern=r"^[a-zA-Z0-9-]{8,80}$")


class Toggle(Strict):
    enabled: bool


class Deploy(Strict):
    strategy_id: str
    source: Literal["synthetic", "kalshi"]
    series: str = Field(default="", pattern=r"^[A-Z0-9-]{0,80}$")
    confirm: bool = False


class SandboxSettle(Strict):
    ticker: str = Field(pattern=r"^DEMO-[1-6]$")
    outcome: Literal["yes", "no"]


class RepoRequest(Strict):
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", max_length=200)


class ComboRequest(Strict):
    probabilities: list[float] = Field(min_length=2, max_length=8)


def create_app(services: Services | None = None):
    production = os.getenv("APP_ENV", "production") != "development"
    password = os.getenv("APP_PASSWORD", "")
    secret = os.getenv("SESSION_SECRET", "")
    if production and (len(password) < 16 or len(secret) < 32):
        raise RuntimeError("Production requires APP_PASSWORD (16+ characters) and SESSION_SECRET (32+ characters)")
    signer = URLSafeTimedSerializer(secret or secrets.token_hex(32), salt="stonks-login-v1")
    attempts = defaultdict(list)
    s = services or Services()

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(s.worker())
        app.state.worker = task
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    app = FastAPI(title="By Order of Stonks", version="0.2.0", lifespan=lifespan,
        docs_url=None, redoc_url=None, openapi_url=None)
    app.state.services = s

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/"):
            if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-stonks-request") != "1":
                return JSONResponse({"detail": "Same-origin action header required"}, 403)
            if request.headers.get("origin"):
                allowed = os.getenv("PUBLIC_ORIGIN") or str(request.base_url).rstrip("/")
                if request.headers["origin"].rstrip("/") != allowed.rstrip("/"):
                    return JSONResponse({"detail": "Origin not allowed"}, 403)
            if int(request.headers.get("content-length", "0")) > 25_000_000:
                return JSONResponse({"detail": "Request exceeds 25 MB"}, 413)
            if path not in ("/api/session", "/api/login") and (production or password):
                try:
                    data = signer.loads(request.cookies.get("stonks_session", ""), max_age=28800)
                    if data != {"user": "owner"}:
                        raise BadSignature("Invalid identity")
                except BadSignature:
                    return JSONResponse({"detail": "Sign in required"}, 401)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store" if path.startswith("/api/") else "no-cache"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"detail": str(exc)[:2000]}, 400)

    @app.get("/healthz")
    async def health():
        worker = getattr(app.state, "worker", None)
        return JSONResponse({"status": "ok" if worker and not worker.done() else "starting", "version": "0.2.0"},
            status_code=200 if worker and not worker.done() else 503)

    @app.get("/api/session")
    async def session(request: Request):
        authenticated = not (production or password)
        try:
            authenticated |= signer.loads(request.cookies.get("stonks_session", ""), max_age=28800) == {"user": "owner"}
        except BadSignature:
            pass
        return {"authenticated": authenticated, "local_dev": not production}

    @app.post("/api/login")
    async def login(body: Login, request: Request):
        ip = request.client.host
        attempts[ip] = [t for t in attempts[ip] if time.monotonic()-t < 600]
        if len(attempts[ip]) >= 10:
            raise HTTPException(429, "Too many attempts. Try again in 10 minutes.")
        attempts[ip].append(time.monotonic())
        if not password or not secrets.compare_digest(body.password, password):
            raise HTTPException(401, "Incorrect password")
        attempts[ip].clear()
        response = JSONResponse({"authenticated": True})
        response.set_cookie("stonks_session", signer.dumps({"user": "owner"}), httponly=True,
            secure=production, samesite="strict", max_age=28800)
        return response

    @app.post("/api/logout")
    async def logout():
        response = JSONResponse({"ok": True})
        response.delete_cookie("stonks_session")
        return response

    @app.get("/api/overview")
    async def overview():
        return s.overview()

    @app.get("/api/records/{id}")
    async def record(id: str):
        result = s.store.get(id)
        if not result:
            raise HTTPException(404, "Record not found")
        return result

    @app.post("/api/strategies")
    async def save_strategy(body: StrategySave):
        result = s.save_strategy(body.config, body.origin, parent_id=body.parent_id)
        s.audit("strategy_saved", {"id": result["id"], "parent_id": body.parent_id})
        return result

    @app.post("/api/backtests", status_code=202)
    async def backtest(body: BacktestRequest):
        s.dataset(body.dataset_id)
        return s.enqueue("backtest", body.model_dump(mode="json"))

    @app.post("/api/research", status_code=202)
    async def research(body: ResearchRequest):
        s.dataset(body.dataset_id)
        return s.enqueue("research", body.model_dump(mode="json"))

    @app.post("/api/jobs/{id}/cancel")
    async def cancel(id: str):
        with s.lock:
            j = s.store.get(id)
            if not j or "job_type" not in j:
                raise HTTPException(404, "Job not found")
            if j["status"] in ("queued", "running"):
                j = s.store.write("job", {**j, "status": "cancelled", "finished_at": now()}, id)
            return j

    @app.post("/api/jobs/{id}/retry", status_code=202)
    async def retry(id: str):
        j = s.store.get(id)
        if not j or "job_type" not in j:
            raise HTTPException(404, "Job not found")
        return s.enqueue(j["job_type"], j["payload"])

    @app.post("/api/schedule")
    async def schedule(body: Schedule):
        s.dataset(body.dataset_id)
        s.audit("research_schedule", body.model_dump())
        return s.store.write("setting", body.model_dump(), "schedule")

    @app.post("/api/datasets")
    async def upload(body: DatasetUpload):
        rows = await asyncio.to_thread(validate_rows, body.rows)
        return s.store.write("dataset", {"name": body.name, "source": "synthetic" if body.synthetic else "upload_unverified",
            "rows": [r.model_dump(mode="json") for r in rows], "description": body.provenance,
            "warnings": ["User-provided provenance is not independently verified."],
            "coverage": {"start": rows[0].available_at.isoformat(), "end": rows[-1].available_at.isoformat(),
                "contracts": len({r.ticker for r in rows})}})

    @app.post("/api/import/kalshi", status_code=202)
    async def import_kalshi(body: ImportRequest):
        return s.enqueue("import", body.model_dump(mode="json"))

    @app.get("/api/export/{id}")
    async def export(id: str, format: Literal["json", "csv"] = "json"):
        r = s.store.get(id)
        if not r:
            raise HTTPException(404, "Record not found")
        if format == "json":
            content, media = json.dumps(r, indent=2), "application/json"
        else:
            rows = r.get("trades", r.get("rows", []))
            if not rows:
                raise ValueError("No tabular rows available")
            f = io.StringIO()
            writer = csv.DictWriter(f, fieldnames=list(rows[0]), extrasaction="ignore")
            writer.writeheader()
            # Neutralize spreadsheet formula injection in user/exchange text.
            writer.writerows({k: ("'"+v if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v) for k, v in row.items()} for row in rows)
            content, media = f.getvalue(), "text/csv"
        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", id)
        return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{safe}.{format}"'})

    @app.get("/api/kalshi/diagnostics")
    async def kalshi_diagnostics():
        return await s.kalshi.diagnostics()

    @app.get("/api/markets")
    async def markets(source: Literal["synthetic", "kalshi"] = "synthetic",
        series: str = Query(default="", pattern=r"^[A-Z0-9-]{0,80}$"), cursor: str = Query(default="", max_length=1000)):
        return await s.markets(source, series, cursor)

    @app.get("/api/quote/{ticker}")
    async def quote(ticker: str, source: Literal["synthetic", "kalshi"] = "synthetic"):
        if not re.fullmatch(r"[A-Z0-9.-]{1,160}", ticker):
            raise ValueError("Invalid ticker")
        return await s.quote(ticker, source)

    @app.post("/api/paper/orders")
    async def order(body: PaperOrder):
        return await s.order(body)

    @app.post("/api/paper/{source}/halt")
    async def halt(source: Literal["synthetic", "kalshi"], body: Toggle):
        async with s.paper_lock:
            state = s.store.get("paper-"+source)
            s.audit("paper_halt", {"source": source, "halted": body.enabled})
            return s.store.write("account", {**state, "halted": body.enabled}, state["id"])

    @app.post("/api/paper/{source}/reconcile")
    async def reconcile(source: Literal["synthetic", "kalshi"]):
        return await s.reconcile(source)

    @app.post("/api/paper/sandbox-settle")
    async def sandbox(body: SandboxSettle):
        value = {"ticker": body.ticker, "status": "settled", "result": body.outcome,
            "settlement_value": 1 if body.outcome == "yes" else 0, "settlement_ts": now()}
        s.store.write("sandbox_settlement", value, "sandbox-"+body.ticker)
        return await s.reconcile("synthetic")

    @app.post("/api/deployments")
    async def deploy(body: Deploy):
        if not body.confirm:
            raise ValueError("Confirm automatic PAPER-only orders")
        row = s.store.get(body.strategy_id)
        if not row or "config" not in row:
            raise ValueError("Strategy not found")
        strategy = Strategy.model_validate(row["config"])
        if strategy.family != "longshot":
            raise ValueError("Automated forward scanning currently supports longshot rules only; model-edge needs a point-in-time live forecast adapter")
        if len(s.store.list("deployment", 100)) >= 10:
            raise ValueError("At most 10 paper deployments in this release")
        dep = s.store.write("deployment", {**body.model_dump(), "strategy": strategy.model_dump(), "enabled": True,
            "last_scan": None, "last_orders": [], "mode": "paper", "error": None})
        s.audit("paper_deployment", {"id": dep["id"], "strategy_id": body.strategy_id, "source": body.source})
        return dep

    @app.post("/api/deployments/{id}")
    async def deployment_toggle(id: str, body: Toggle):
        dep = s.store.get(id)
        if not dep or "last_scan" not in dep:
            raise ValueError("Deployment not found")
        return s.store.write("deployment", {**dep, "enabled": body.enabled}, id)

    @app.get("/api/weather")
    async def weather(latitude: float = Query(ge=-90, le=90), longitude: float = Query(ge=-180, le=180)):
        result = await weather_forecast(latitude, longitude)
        return s.store.write("weather", result)

    @app.post("/api/integrations/inspect")
    async def inspect_repo(body: RepoRequest):
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "ByOrderOfStonks/0.2"}
        if os.getenv("GITHUB_READ_TOKEN"):
            headers["Authorization"] = "Bearer "+os.environ["GITHUB_READ_TOKEN"]
        async with httpx.AsyncClient(timeout=20, follow_redirects=False, headers=headers) as client:
            try:
                r = await client.get("https://api.github.com/repos/"+body.repository)
                r.raise_for_status()
                repo = r.json()
                commit = await client.get("https://api.github.com/repos/"+body.repository+"/commits", params={"per_page": 1})
                commit.raise_for_status()
            except httpx.HTTPError as exc:
                raise ValueError("Repository lookup failed. Check visibility and optional server-side read token.") from exc
        result = {"repository": repo["full_name"], "url": repo["html_url"], "description": repo.get("description"),
            "license": (repo.get("license") or {}).get("spdx_id", "UNVERIFIED"), "pinned_commit": commit.json()[0]["sha"],
            "updated_at": repo.get("pushed_at"), "archived": repo.get("archived"), "status": "review_required",
            "note": "Metadata inspection only. No code executed or installed. License/dependency/security/methodology review required."}
        return s.store.write("integration", result)

    @app.post("/api/combo/analyze")
    async def combo(body: ComboRequest):
        import math
        if any(not 0 <= p <= 1 or not math.isfinite(p) for p in body.probabilities):
            raise ValueError("Probabilities must be finite and between zero and one")
        p = body.probabilities
        return {"lower_bound": max(0, sum(p)-(len(p)-1)), "upper_bound": min(p), "independence_scenario": math.prod(p),
            "executable": False, "warning": "User assumptions, not estimated probabilities. Product assumes independence and is not a joint forecast. No native combo quote or order."}

    @app.post("/api/copilot")
    async def assistant(body: ChatRequest):
        return await copilot.chat(s, body.message, body.context, body.session_id)

    @app.post("/api/live/orders")
    async def no_live_orders():
        raise HTTPException(403, "Real-money execution is deliberately absent from this release. No environment flag can enable it.")

    app.mount("/assets", StaticFiles(directory=ROOT/"frontend"), name="assets")

    @app.get("/")
    async def index():
        return FileResponse(ROOT/"frontend"/"index.html")

    return app
