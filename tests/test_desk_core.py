"""Grounded research desk tests. All provider records are mocked, never presented as real."""
import asyncio
from datetime import datetime, timezone, timedelta

import pytest

from backend.market_catalog import MarketCatalog
from backend.quant_research import samples, calibration, simulate, study
from backend.desk import Desk, ResearchInput, plan_fallback
from backend.store import Store
from backend.service import Services
from backend.app import create_app
from fastapi.testclient import TestClient


def market(n=0, result="yes"):
    return {
        "ticker": "TEST-26-"+str(n), "event_ticker": "TEST-26",
        "series_ticker": "TEST", "title": "Test variable outcome "+str(n),
        "status": "settled", "result": result,
        "settlement_ts": "2026-10-10T00:00:00Z",
        "created_time": "2026-09-01T00:00:00Z",
        "notional_value_dollars": "1.0000",
        "yes_bid_dollars": "0.0900", "yes_ask_dollars": "0.1100",
        "_category": "Other", "volume_fp": "1000",
    }


def sample(n, result="yes", mid=.11, vol=1000):
    return {
        "ticker": "T"+str(n), "series_ticker": "TEST",
        "event_id": "EV"+str(n), "title": "Test "+str(n),
        "result": result, "settled_at": "2026-10-10T00:00:00+00:00",
        "category": "Other", "raw": {},
        "bars": [{"ticker": "T"+str(n), "asof": "2026-10-08T00:00:00+00:00",
                  "yes_bid": mid-.01, "yes_ask": mid+.01, "volume": vol}]
    }


def test_baselines_only_use_historical_quotes_and_settlement():
    entries = samples([sample(1, "no"), sample(2, "yes")])
    assert len(entries) == 2
    assert entries[0]["mid"] == pytest.approx(.11)
    cal = calibration(entries)
    assert cal["contracts"] == 2
    assert cal["events"] == 2
    assert len(cal["bins"]) == 1
    result = simulate(entries, model="against_longshots")
    assert result["total_trades"] == 2
    assert result["event_count"] == 2
    assert "Hypothetical" in result["warning"]
    assert result["fees"] >= 0
    assert sum(t["pnl"] for t in result["trades"]) == pytest.approx(result["net_pnl"], abs=.02)


def test_no_future_bar_or_missing_outcome_in_study():
    rows = [sample(1, "no")]
    rows[0]["bars"][0]["asof"] = "2026-10-09T22:00:00+00:00"
    assert not samples(rows)
    rows[0]["bars"][0]["asof"] = "2026-10-08T00:00:00+00:00"
    rows[0]["result"] = "canceled"
    assert not samples(rows)


def test_real_data_only_and_explicit_sample_limit():
    result = study([sample(1, "no"), sample(2, "yes")],
                   model="buy_no", compare_by="series")
    assert result["status"] == "limited_sample"
    assert result["independent_event_ids"] == 2
    assert result["groups"][0]["group"] == "TEST"


class FakeKalshi:
    environment = "production"
    key = None

    async def get(self, path, params=None):
        if path == "/series":
            return {"series": [{"ticker": "TEST", "title": "Test forecasts",
                                "category": "Other", "tags": ["test"]}]}
        if path == "/markets" and (params or {}).get("status") == "open":
            return {"markets": [], "cursor": ""}
        if path == "/markets":
            return {"markets": [market(0, "no")], "cursor": ""}
        if path == "/historical/markets":
            return {"markets": [], "cursor": ""}
        if path == "/historical/cutoff":
            return {"market_settled_ts": "2026-11-01T00:00:00Z"}
        if path.startswith("/historical/markets/") and path.endswith("/candlesticks"):
            return {"candlesticks": [
                {"end_period_ts": int(datetime(2026, 10, d, tzinfo=timezone.utc).timestamp()),
                 "yes_bid": {"close": "0.0900"}, "yes_ask": {"close": "0.1100"},
                 "volume_fp": "500"}
                for d in (6, 7, 8)]}
        raise AssertionError(f"Unexpected provider route: {path}, {params}")


def make_desk(tmp_path):
    store = Store("sqlite:///"+str(tmp_path/"desk.db"))
    service = Services(store)
    service.kalshi = FakeKalshi()
    return Desk(service)


def test_index_and_search_are_grounded(tmp_path):
    desk = make_desk(tmp_path)
    result = asyncio.run(desk.catalog.refresh_series())
    assert result["series_count"] == 1
    assert desk.catalog.search_series("test")[0]["ticker"] == "TEST"
    assert desk.catalog.search_markets("test")["count"] == 0
    desk.catalog.put_markets([market()], "test-provider")
    found = desk.catalog.search_markets("variable")
    assert found["count"] == 1
    assert found["markets"][0]["ticker"] == "TEST-26-0"
    assert found["markets"][0]["origin"] == "test-provider"


def test_auto_collect_history_no_manual_tickers(tmp_path):
    desk = make_desk(tmp_path)
    asyncio.run(desk.catalog.refresh_series())
    series = desk.catalog.search_series("test")
    found = asyncio.run(desk.catalog.discover_history(series, 30, 8))
    assert found["discovered"] == 1
    got = asyncio.run(desk.catalog.collect_candles(found["markets"][0], days=60))
    assert got["count"] == 3
    market_data = desk.catalog.dataset(["TEST-26-0"])
    assert len(market_data[0]["bars"]) == 3
    assert market_data[0]["result"] == "no"


def test_research_question_produces_real_report(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    desk = make_desk(tmp_path)
    asyncio.run(desk.catalog.refresh_series())
    request = ResearchInput(question="Investigate the Test variable markets", include_web=False)
    job = desk.enqueue(request)
    report = asyncio.run(desk.run_research(job["id"]))
    assert report["status"] == "limited_evidence"
    assert report["acquisition"]["settled_market_count"] == 1
    assert report["acquisition"]["candles_loaded"] == 3
    assert report["studies"][0]["observations"] == 1
    assert report["real_money_execution"] is False
    assert all("synthetic" not in str(x).lower() for x in report["current_markets"])


def test_unsupported_questions_do_not_select_random_series():
    p = plan_fallback("Does this unfamiliar zymology contract have an edge?")
    assert p["search_terms"]
    assert p["method"] == "deterministic fallback"


def test_new_endpoints_keep_production_trading_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    s = Services(Store("sqlite:///"+str(tmp_path/"endpoint.db")))
    app = create_app(s)
    client = TestClient(app)
    assert client.get("/api/desk/overview").status_code == 200
    assert client.get("/api/desk/markets").json()["count"] == 0
    assert client.post("/api/desk/research", json={"question": "Compare a set of contract types"},
                       headers={"X-Stonks-Request":"1"}).status_code == 202
    assert client.post("/api/live/orders", json={}, headers={"X-Stonks-Request":"1"}).status_code == 403
