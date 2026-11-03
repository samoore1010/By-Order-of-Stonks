"""Indexed, provider-grounded Kalshi market intelligence.

No invented sample markets. All network work is bounded, cached and auditable.
Data models retain original provider fields and explicit source timestamps.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote
from sqlalchemy import (
    Table, Column, MetaData, String, Float, Integer, JSON, Index,
    select, func, or_, and_
)
from .models import now
from .providers import Kalshi, price_field, normalize_market

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "best", "by", "can", "compare",
    "do", "for", "from", "have", "how", "i", "in", "is", "it", "me", "of",
    "on", "or", "our", "should", "show", "that", "the", "their", "there",
    "these", "this", "to", "trade", "trading", "want", "what", "which",
    "where", "with", "would", "you", "better", "profitable", "markets",
    "market", "prediction", "kalshi", "historical", "history", "strategy",
    "strategies", "test", "backtest", "find", "ideas", "research", "look",
}
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]{2,}")
TICKER_PATTERN = re.compile(r"^[A-Z0-9.-]{1,160}$")


def tokens(value: str) -> list[str]:
    return list(dict.fromkeys(
        token for token in (t.lower() for t in TOKEN_PATTERN.findall(value))
        if token not in STOPWORDS
    ))[:16]


def iso(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, (float, int)):
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d.astimezone(timezone.utc).isoformat() if d.tzinfo else None
    except ValueError:
        return None


class MarketCatalog:
    def __init__(self, engine, kalshi: Kalshi):
        self.engine = engine
        self.kalshi = kalshi
        metadata = MetaData()
        self.series = Table(
            "desk_series", metadata,
            Column("ticker", String(120), primary_key=True),
            Column("title", String(500), nullable=False),
            Column("category", String(140)),
            Column("tags", JSON),
            Column("raw", JSON),
            Column("refreshed_at", String(45)),
        )
        self.markets = Table(
            "desk_markets", metadata,
            Column("ticker", String(180), primary_key=True),
            Column("series_ticker", String(120), index=True),
            Column("event_id", String(180), index=True),
            Column("title", String(900)),
            Column("event_title", String(900)),
            Column("category", String(140), index=True),
            Column("status", String(40), index=True),
            Column("result", String(40)),
            Column("settled_at", String(45)),
            Column("created_at", String(45)),
            Column("close_time", String(45)),
            Column("yes_bid", Float),
            Column("yes_ask", Float),
            Column("volume", Float),
            Column("raw", JSON),
            Column("retrieved_at", String(45)),
            Column("origin", String(50)),
        )
        self.bars = Table(
            "desk_bars", metadata,
            Column("ticker", String(180), primary_key=True),
            Column("asof", String(45), primary_key=True),
            Column("yes_bid", Float),
            Column("yes_ask", Float),
            Column("volume", Float),
            Column("source", String(50)),
        )
        Index("ix_desk_series_title", self.series.c.title)
        metadata.create_all(self.engine)

    def _upsert(self, table, records: list[dict], pk: str = "ticker") -> int:
        count = 0
        with self.engine.begin() as con:
            for row in records:
                key = row[pk]
                existing = con.execute(select(table.c[pk]).where(table.c[pk] == key)).first()
                if existing:
                    con.execute(table.update().where(table.c[pk] == key).values(**row))
                else:
                    con.execute(table.insert().values(**row))
                count += 1
        return count

    def _store_bars(self, bars: list[dict]) -> int:
        with self.engine.begin() as con:
            for row in bars:
                existing = con.execute(select(self.bars.c.ticker).where(
                    and_(self.bars.c.ticker == row["ticker"],
                         self.bars.c.asof == row["asof"]))).first()
                if not existing:
                    con.execute(self.bars.insert().values(**row))
        return len(bars)

    def put_series(self, raw: list[dict]) -> int:
        rows = []
        for s in raw:
            ticker = str(s.get("ticker") or "")
            if not TICKER_PATTERN.fullmatch(ticker):
                continue
            rows.append({
                "ticker": ticker,
                "title": str(s.get("title") or ticker)[:500],
                "category": str(s.get("category") or "Other")[:140],
                "tags": s.get("tags") or [],
                "raw": s,
                "refreshed_at": now(),
            })
        return self._upsert(self.series, rows)

    def put_markets(self, raw: list[dict], origin: str) -> int:
        rows = []
        for m in raw:
            ticker = str(m.get("ticker") or "")
            if not TICKER_PATTERN.fullmatch(ticker):
                continue
            event_id = str(m.get("event_ticker") or ticker)
            series_ticker = str(m.get("series_ticker") or event_id.split("-")[0])
            category = str(m.get("_category") or m.get("category") or "Unclassified")
            norm = normalize_market(m, category)
            rows.append({
                "ticker": ticker,
                "series_ticker": series_ticker[:120],
                "event_id": event_id[:180],
                "title": str(m.get("title") or ticker)[:900],
                "event_title": str(m.get("_event_title") or "")[:900],
                "category": category[:140],
                "status": str(m.get("status") or "unknown")[:40],
                "result": str(m.get("result") or "")[:40],
                "settled_at": iso(m.get("settlement_ts")),
                "created_at": iso(m.get("created_time")),
                "close_time": iso(m.get("close_time")),
                "yes_bid": norm.get("yes_bid"),
                "yes_ask": norm.get("yes_ask"),
                "volume": norm.get("volume"),
                "raw": m,
                "retrieved_at": now(),
                "origin": origin,
            })
        return self._upsert(self.markets, rows)

    async def refresh_series(self) -> dict:
        data = await self.kalshi.get("/series")
        raw = data.get("series")
        if not isinstance(raw, list):
            raise ValueError("Unexpected Kalshi series response")
        return {"series_count": self.put_series(raw), "fetched_at": now(),
                "source": "Kalshi /series", "coverage": "Provider series listing"}

    async def index_current(self, max_pages=3) -> dict:
        pages, count, cursor = 0, 0, ""
        for _ in range(min(max_pages, 5)):
            params = {"limit": 500, "status": "open", "mve_filter": "exclude"}
            if cursor:
                params["cursor"] = cursor
            data = await self.kalshi.get("/markets", params)
            raw = data.get("markets")
            if not isinstance(raw, list):
                raise ValueError("Unexpected Kalshi markets response")
            count += self.put_markets(raw, "kalshi-open")
            pages += 1
            new_cursor = data.get("cursor") or ""
            if not new_cursor or new_cursor == cursor:
                cursor = ""
                break
            cursor = new_cursor
            await asyncio.sleep(.12)
        return {"pages": pages, "retrieved": count, "has_more": bool(cursor),
                "source": "Kalshi current open markets", "fetched_at": now(),
                "coverage": "Bounded paginated scan, never claimed exhaustive"}

    def search_series(self, query: str, limit=12) -> list[dict]:
        words = tokens(query)
        with self.engine.connect() as con:
            rows = [dict(r._mapping) for r in con.execute(select(self.series))]
        ranked = []
        for row in rows:
            hay = " ".join([row["ticker"], row["title"], row["category"],
                            " ".join(str(t) for t in (row["tags"] or []))]).lower()
            score = sum(4 if t in row["title"].lower() else 2 if t in hay else 0 for t in words)
            if (not words) or score:
                ranked.append((score, row))
        ranked.sort(key=lambda item: (-item[0], item[1]["title"]))
        return [{k: v for k, v in row.items() if k != "raw"} for _, row in ranked[:limit]]

    def search_markets(self, query: str = "", category: str = "", status: str = "",
                       series: str = "", limit: int = 100, offset: int = 0) -> dict:
        clauses = []
        if query:
            words = tokens(query)
            if words:
                clauses.append(or_(*[
                    or_(func.lower(self.markets.c.title).like(f"%{t}%"),
                        func.lower(self.markets.c.event_title).like(f"%{t}%"),
                        func.lower(self.markets.c.ticker).like(f"%{t}%"),
                        func.lower(self.markets.c.series_ticker).like(f"%{t}%"))
                    for t in words]))
        if category:
            clauses.append(func.lower(self.markets.c.category) == category.lower())
        if status:
            clauses.append(self.markets.c.status == status)
        if series:
            clauses.append(self.markets.c.series_ticker == series)
        where = and_(*clauses) if clauses else True
        stmt = (select(self.markets).where(where)
                .order_by(self.markets.c.volume.desc()).limit(min(limit, 200)).offset(max(0, offset)))
        with self.engine.connect() as con:
            items = [{k: v for k, v in dict(r._mapping).items() if k != "raw"}
                     for r in con.execute(stmt)]
            total = con.execute(select(func.count()).select_from(self.markets).where(where)).scalar_one()
        return {"markets": items, "count": total, "offset": offset,
                "returned": len(items), "source": "indexed Kalshi records",
                "warning": "Only indexed records are searchable; indexing coverage is shown separately."}

    def overview(self) -> dict:
        with self.engine.connect() as con:
            return {
                "series_indexed": con.execute(select(func.count()).select_from(self.series)).scalar_one(),
                "markets_indexed": con.execute(select(func.count()).select_from(self.markets)).scalar_one(),
                "candles_indexed": con.execute(select(func.count()).select_from(self.bars)).scalar_one(),
                "latest_indexed": con.execute(select(func.max(self.markets.c.retrieved_at))).scalar_one(),
                "source": "Kalshi REST + stored observations",
            }

    def top_active_series(self, limit: int = 8) -> list[dict]:
        """Select liquid, diverse series for bounded unattended research."""
        from sqlalchemy import desc
        with self.engine.connect() as con:
            ranked = con.execute(
                select(self.markets.c.series_ticker,
                       func.sum(self.markets.c.volume).label("volume"))
                .where(self.markets.c.status == "open")
                .group_by(self.markets.c.series_ticker)
                .order_by(desc("volume")).limit(80)
            ).all()
            series_rows = {r["ticker"]: r for r in
                (dict(x._mapping) for x in con.execute(select(self.series)))}
        selected, counts = [], {}
        for ticker, volume in ranked:
            row = series_rows.get(ticker)
            if not row:
                continue
            category = row["category"] or "Other"
            if counts.get(category, 0) >= 2:
                continue
            counts[category] = counts.get(category, 0) + 1
            selected.append({"ticker": ticker, "title": row["title"],
                             "category": category, "volume_proxy": float(volume or 0)})
            if len(selected) >= limit:
                break
        return selected

    def get_market(self, ticker: str) -> dict | None:
        with self.engine.connect() as con:
            row = con.execute(select(self.markets).where(self.markets.c.ticker == ticker)).first()
            return dict(row._mapping) if row else None

    async def discover_history(self, series: list[dict], per_series=40,
                               max_markets=80) -> dict:
        """Discover settled contracts without demanding their tickers from the user.

        Both current and archive stores are queried. Partial coverage is reported.
        """
        found, issues, pages, incomplete = [], [], 0, []
        for s in series[:12]:
            if len(found) >= max_markets:
                incomplete.append("Global market cap reached")
                break
            ticker = s["ticker"]
            for endpoint in ("/markets", "/historical/markets"):
                cursor, fetched_for_series = "", 0
                for _ in range(3):
                    params = {"series_ticker": ticker, "limit": min(per_series, 100),
                              "mve_filter": "exclude"}
                    if endpoint == "/markets":
                        params["status"] = "settled"
                    if cursor:
                        params["cursor"] = cursor
                    try:
                        data = await self.kalshi.get(endpoint, params)
                    except ValueError as exc:
                        issues.append({"series": ticker, "endpoint": endpoint,
                                       "error": str(exc)[:180]})
                        break
                    pages += 1
                    raw = data.get("markets") or []
                    for item in raw:
                        if item.get("result") not in ("yes", "no"):
                            continue
                        if not item.get("settlement_ts"):
                            continue
                        if not TICKER_PATTERN.fullmatch(str(item.get("ticker") or "")):
                            continue
                        m = dict(item)
                        m["series_ticker"] = ticker
                        m["_category"] = s.get("category", "Other")
                        found.append(m)
                        fetched_for_series += 1
                        if len(found) >= max_markets or fetched_for_series >= per_series:
                            break
                    if len(found) >= max_markets or fetched_for_series >= per_series:
                        if data.get("cursor"):
                            incomplete.append(f"{ticker} {endpoint} truncated")
                        break
                    next_cursor = data.get("cursor") or ""
                    if not next_cursor or next_cursor == cursor:
                        break
                    cursor = next_cursor
                    await asyncio.sleep(.1)
                if len(found) >= max_markets:
                    break
        unique = list({m["ticker"]: m for m in found}.values())
        self.put_markets(unique, "kalshi-settled")
        return {"markets": unique, "pages": pages, "issues": issues,
                "truncation": incomplete, "discovered": len(unique),
                "series_requested": [x["ticker"] for x in series[:12]]}

    async def collect_candles(self, market: dict, days=365, interval=1440) -> dict:
        ticker = str(market["ticker"])
        series = str(market["series_ticker"])
        settled = iso(market.get("settlement_ts"))
        if not settled:
            return {"ticker": ticker, "count": 0, "error": "Settlement timestamp missing"}
        end = datetime.fromisoformat(settled)
        start = max(end - timedelta(days=max(2, min(days, 730))),
                    datetime.fromisoformat(iso(market.get("created_time"))) if
                    iso(market.get("created_time")) else end - timedelta(days=days))
        if start >= end:
            return {"ticker": ticker, "count": 0, "error": "No interval before settlement"}
        # The historical archive may contain different ranges than the live market store.
        try:
            cutoff = await self.kalshi.get("/historical/cutoff")
            boundary = iso(cutoff.get("market_settled_ts"))
            archived = bool(boundary and end < datetime.fromisoformat(boundary))
        except ValueError:
            archived = market.get("_origin") == "archive"
        path = (f"/historical/markets/{quote(ticker, safe='')}/candlesticks" if archived else
                f"/series/{quote(series, safe='')}/markets/{quote(ticker, safe='')}/candlesticks")
        from_ts, to_ts = int(start.timestamp()), int(end.timestamp())
        chunk = 365 * 1440 * 60 if interval == 1440 else 400 * 60 * 60
        bars = []
        for left in range(from_ts, to_ts, chunk):
            payload = await self.kalshi.get(path, {"start_ts": left, "end_ts": min(to_ts, left+chunk),
                                                   "period_interval": interval})
            for candle in payload.get("candlesticks", []):
                t = candle.get("end_period_ts")
                if t is None:
                    continue
                at = datetime.fromtimestamp(int(t), timezone.utc)
                if not start <= at < end:
                    continue
                bid = price_field(candle.get("yes_bid") or {}, "close")
                ask = price_field(candle.get("yes_ask") or {}, "close")
                if bid is None or ask is None or not (0 <= bid <= ask <= 1):
                    continue
                bars.append({
                    "ticker": ticker, "asof": at.isoformat(),
                    "yes_bid": bid, "yes_ask": ask,
                    "volume": float(candle.get("volume_fp") or candle.get("volume") or 0),
                    "source": "Kalshi archived candle" if archived else "Kalshi candle",
                })
            await asyncio.sleep(.12)
        bars = list({r["asof"]: r for r in bars}.values())
        self._store_bars(bars)
        return {"ticker": ticker, "count": len(bars), "archived": archived, "source": path}

    def dataset(self, tickers: list[str]) -> list[dict]:
        if not tickers:
            return []
        tickers = list(dict.fromkeys(tickers))[:200]
        with self.engine.connect() as con:
            markets = [dict(r._mapping) for r in con.execute(
                select(self.markets).where(self.markets.c.ticker.in_(tickers)))]
            bars = [dict(r._mapping) for r in con.execute(
                select(self.bars).where(self.bars.c.ticker.in_(tickers)).order_by(self.bars.c.asof))]
        by_ticker = {m["ticker"]: {**m, "bars": []} for m in markets}
        for bar in bars:
            if bar["ticker"] in by_ticker:
                by_ticker[bar["ticker"]]["bars"].append(bar)
        return [by_ticker[t] for t in tickers if t in by_ticker]
