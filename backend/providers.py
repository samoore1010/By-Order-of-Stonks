"""Allowlisted, read-only provider adapters. No code here can submit exchange orders."""
from __future__ import annotations
import asyncio
import base64
import hashlib
import json
import math
import os
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit
import httpx
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa, padding
from .models import ImportRequest, now
from .engine import validate_rows

BASES = {
    "production": "https://external-api.kalshi.com/trade-api/v2",
    "demo": "https://external-api.demo.kalshi.co/trade-api/v2",
}


def price_field(data: dict, key: str) -> float | None:
    """Current *_dollars, archived dollar strings, and legacy integer-cent fields."""
    value = data.get(key+"_dollars")
    if value is not None:
        return float(value)
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, str) and "." in value:
        return float(value)
    return float(value)/100


def normalize_market(m: dict, category: str = "Unclassified") -> dict:
    bid, ask = price_field(m, "yes_bid"), price_field(m, "yes_ask")
    notional = price_field(m, "notional_value")
    return {"ticker": m["ticker"], "event_id": m.get("event_ticker", m["ticker"]),
        "title": m.get("title") or m.get("yes_sub_title") or m["ticker"],
        "category": m.get("category") or category, "yes_bid": bid, "yes_ask": ask if ask else None,
        "volume": float(m.get("volume_fp", m.get("volume", 0)) or 0),
        "status": m.get("status", "unknown"), "source": "kalshi", "observed_at": now(),
        "close_time": m.get("close_time"), "rules": m.get("rules_primary", "")+"\n"+m.get("rules_secondary", ""),
        "result": m.get("result"), "settlement_ts": m.get("settlement_ts"),
        "settlement_value": price_field(m, "settlement_value"),
        "binary_supported": notional == 1 and not m.get("mve_collection_ticker")
            and m.get("market_type", "binary") == "binary"}


def parse_book(data: dict) -> dict:
    new = data.get("orderbook_fp")
    if new is not None:
        yes = [(float(p), float(q)) for p, q in (new.get("yes_dollars") or [])]
        no = [(float(p), float(q)) for p, q in (new.get("no_dollars") or [])]
    elif "orderbook" in data:
        old = data["orderbook"]
        yes = [(float(p)/100, float(q)) for p, q in (old.get("yes") or [])]
        no = [(float(p)/100, float(q)) for p, q in (old.get("no") or [])]
    else:
        raise ValueError("Unrecognized order-book schema; paper orders blocked")
    for p, q in yes+no:
        if not 0 <= p <= 1 or not math.isfinite(q) or q < 0:
            raise ValueError("Invalid order-book level")
    book = {"yes": sorted([[round(1-p, 6), q] for p, q in no]),
            "no": sorted([[round(1-p, 6), q] for p, q in yes])}
    book["fingerprint"] = hashlib.sha256(json.dumps(book, sort_keys=True).encode()).hexdigest()
    book["received_at"] = now()
    return book


class Kalshi:
    def __init__(self):
        self.environment = os.getenv("KALSHI_ENV", "production")
        if self.environment not in BASES:
            raise ValueError("KALSHI_ENV must be production or demo")
        self.base = BASES[self.environment]
        self.key_id = os.getenv("KALSHI_API_KEY_ID", "")
        self.key = None
        pem = os.getenv("KALSHI_PRIVATE_KEY_PEM", "").replace("\\n", "\n")
        if self.key_id and pem:
            self.key = serialization.load_pem_private_key(pem.encode(), password=None)
            if not isinstance(self.key, (ed25519.Ed25519PrivateKey, rsa.RSAPrivateKey)):
                raise ValueError("Unsupported Kalshi private key type")

    def headers(self, path: str) -> dict:
        h = {"Accept": "application/json", "User-Agent": "ByOrderOfStonks/0.1"}
        if self.key:
            ts = str(int(time.time()*1000))
            message = (ts+"GET"+"/trade-api/v2"+path.split("?")[0]).encode()
            if isinstance(self.key, ed25519.Ed25519PrivateKey):
                signature = self.key.sign(message)
            else:
                signature = self.key.sign(message, padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256())
            h.update({"KALSHI-ACCESS-KEY": self.key_id, "KALSHI-ACCESS-TIMESTAMP": ts,
                "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode()})
        return h

    async def get(self, path: str, params: dict | None = None) -> dict:
        if not path.startswith(("/markets", "/historical", "/series", "/events", "/portfolio/balance")):
            raise ValueError("Read-only endpoint not allowed")
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            for attempt in range(3):
                try:
                    # Public market/history routes must not depend on the account key.
                    # A malformed or unauthorized key must not block public research.
                    headers = self.headers(path) if path.startswith("/portfolio/") else {
                        "Accept": "application/json", "User-Agent": "ByOrderOfStonks/0.1"}
                    r = await client.get(self.base+path, params=params, headers=headers)
                except httpx.RequestError as exc:
                    raise ValueError("Kalshi could not be reached. No sample data substituted.") from exc
                if r.status_code in (429, 502, 503, 504) and attempt < 2:
                    await asyncio.sleep(1+attempt*2)
                    continue
                if r.status_code >= 400:
                    raise ValueError(f"Kalshi returned HTTP {r.status_code}. Check permissions, ticker, and availability.")
                return r.json()
        raise ValueError("Kalshi retry budget exhausted")

    async def diagnostics(self) -> dict:
        """Test public market access independently of private account credentials.

        Never return key material or account balances to the caller.
        """
        result = {"environment": self.environment,
                  "credentials_configured": bool(self.key_id and self.key),
                  "public_markets": {"ok": False},
                  "private_account": {"ok": False, "status": "not_configured"}}
        try:
            data = await self.get("/markets", {"limit": 1, "status": "open"})
            result["public_markets"] = {"ok": isinstance(data.get("markets"), list),
                                        "returned_markets": len(data.get("markets", []))}
        except (ValueError, KeyError, TypeError) as exc:
            result["public_markets"] = {"ok": False, "error": str(exc)[:250]}
        if self.key_id and self.key:
            try:
                await self.get("/portfolio/balance")
                result["private_account"] = {"ok": True, "status": "authenticated"}
            except (ValueError, KeyError, TypeError) as exc:
                result["private_account"] = {"ok": False, "status": "authentication_failed",
                                             "error": str(exc)[:250]}
        return result

    async def markets(self, series: str = "", cursor: str = "") -> dict:
        params = {"limit": 100, "status": "open", "mve_filter": "exclude"}
        if series:
            params["series_ticker"] = series
        if cursor:
            params["cursor"] = cursor
        category = "Unclassified"
        if series:
            info = await self.get("/series/"+quote(series, safe=""))
            category = info.get("series", {}).get("category", category)
        payload = await self.get("/markets", params)
        return {"markets": [normalize_market(m, category) for m in payload.get("markets", [])],
            "cursor": payload.get("cursor", ""), "source": "kalshi", "environment": self.environment,
            "fetched_at": now(), "coverage": "One API page; load more to continue. Not an exchange-wide scan."}

    async def market(self, ticker: str) -> dict:
        path = quote(ticker, safe="")
        try:
            raw = await self.get("/markets/"+path)
        except ValueError:
            raw = await self.get("/historical/markets/"+path)
        return normalize_market(raw["market"])

    async def book(self, ticker: str) -> dict:
        return parse_book(await self.get("/markets/"+quote(ticker, safe="")+"/orderbook", {"depth": 20}))

    async def import_history(self, request: ImportRequest) -> dict:
        cutoff = await self.get("/historical/cutoff")
        series = (await self.get("/series/"+quote(request.series, safe=""))).get("series", {})
        category = series.get("category", "Unclassified")
        rows, rejected, rules, errors = [], [], {}, []
        for ticker in request.tickers:
            try:
                archived = False
                try:
                    raw = (await self.get("/markets/"+quote(ticker, safe="")))["market"]
                except ValueError:
                    raw = (await self.get("/historical/markets/"+quote(ticker, safe="")))["market"]
                    archived = True
                m = normalize_market(raw, category)
                if not raw.get("event_ticker", "").startswith(request.series+"-"):
                    raise ValueError("Ticker does not belong to the requested series")
                if not m["binary_supported"] or m["result"] not in ("yes", "no") or raw.get("status") not in ("settled", "finalized"):
                    raise ValueError("Only final, ordinary $1 binary settlements supported")
                settled = raw.get("settlement_ts")
                if not settled:
                    raise ValueError("Actual settlement timestamp missing; expiration is not substituted")
                settled_dt = datetime.fromisoformat(settled.replace("Z", "+00:00"))
                if cutoff.get("market_settled_ts"):
                    archived |= settled_dt < datetime.fromisoformat(cutoff["market_settled_ts"].replace("Z", "+00:00"))
                path = (f"/historical/markets/{ticker}/candlesticks" if archived else
                        f"/series/{request.series}/markets/{ticker}/candlesticks")
                start, end = int(request.start.timestamp()), int(min(request.end, settled_dt).timestamp())
                candles = []
                width = 400*request.interval*60
                for left in range(start, end, width):
                    data = await self.get(path, {"start_ts": left, "end_ts": min(end, left+width),
                        "period_interval": request.interval})
                    candles.extend(data.get("candlesticks", []))
                    await asyncio.sleep(.12)
                unique = {c["end_period_ts"]: c for c in candles}
                count = 0
                for ts, c in sorted(unique.items()):
                    observed = datetime.fromtimestamp(ts, timezone.utc)
                    bid, ask = price_field(c.get("yes_bid", {}), "close"), price_field(c.get("yes_ask", {}), "close")
                    if not request.start <= observed <= request.end or observed >= settled_dt:
                        continue
                    if bid is None or ask is None or ask <= 0 or bid > ask:
                        rejected.append({"ticker": ticker, "timestamp": ts, "reason": "Missing/invalid bid-ask candle"})
                        continue
                    rows.append({"ticker": ticker, "event_id": raw["event_ticker"], "category": category,
                        "observed_at": observed.isoformat(), "available_at": observed.isoformat(),
                        "yes_bid": bid, "yes_ask": ask, "volume": float(c.get("volume_fp", c.get("volume", 0)) or 0),
                        "outcome": m["result"], "settled_at": settled_dt.isoformat()})
                    count += 1
                rules[ticker] = {"rules": m["rules"], "retrieved_at": now(), "archived": archived}
                if count < 2:
                    errors.append({"ticker": ticker, "error": "Fewer than two usable observations"})
            except (ValueError, KeyError, TypeError) as exc:
                errors.append({"ticker": ticker, "error": str(exc)[:300]})
        if len(rows) < 2:
            raise ValueError("No usable history. "+json.dumps(errors)[:1500])
        validated = validate_rows(rows)
        return {"name": f"Kalshi {request.series} · {len({r.ticker for r in validated})} contracts",
            "source": "kalshi_candles", "rows": [r.model_dump(mode="json") for r in validated],
            "description": "User-selected contracts; partial import and selection bias must be reviewed.",
            "cutoff": cutoff, "rules": rules, "import_request": request.model_dump(mode="json"),
            "errors": errors, "rejected_count": len(rejected), "rejected_preview": rejected[:20],
            "coverage": {"start": validated[0].available_at.isoformat(), "end": validated[-1].available_at.isoformat(),
                "contracts": len({r.ticker for r in validated})},
            "warnings": ["Candle closing quotes are not historical executable depth.",
                "Availability is approximated by candle end. Exact dissemination latency is unknown.",
                "Selected settled contracts are not a complete point-in-time market universe.",
                "Market rules were retrieved now, not proven unchanged historically."]}


async def weather_forecast(lat: float, lon: float) -> dict:
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("Invalid coordinates")
    headers = {"User-Agent": os.getenv("NWS_USER_AGENT", "ByOrderOfStonks-research/0.1"), "Accept": "application/geo+json"}
    async with httpx.AsyncClient(timeout=20, headers=headers, follow_redirects=False) as c:
        try:
            points = await c.get(f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}")
            points.raise_for_status()
            url = points.json()["properties"]["forecast"]
            if urlsplit(url).hostname != "api.weather.gov" or urlsplit(url).scheme != "https":
                raise ValueError("Forecast URL not allowlisted")
            r = await c.get(url)
            r.raise_for_status()
        except (httpx.HTTPError, KeyError) as exc:
            raise ValueError("NWS forecast unavailable for these coordinates") from exc
    data = r.json()["properties"]
    return {"source": "NWS", "url": url, "retrieved_at": now(), "issued_at": data.get("updateTime"),
        "periods": data.get("periods", []), "warning": "Current forecast context only. Not a calibrated probability model or historical forecast archive. Confirm the contract's exact settlement station."}
