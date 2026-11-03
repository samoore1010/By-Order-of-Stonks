"""Browser smoke for three-workspace, real-data-only research desk.

Run: APP_ENV=development python tests/browser_desk.py
All 'market' inputs here are in-process mocked exchange responses, never real
market observations or evidence for an investment decision.
"""
from pathlib import Path
from datetime import datetime, timezone
import os
import re
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["APP_ENV"] = "development"
for key in ("APP_PASSWORD", "OPENAI_API_KEY", "KALSHI_API_KEY_ID", "KALSHI_PRIVATE_KEY_PEM"):
    os.environ.pop(key, None)

from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
from backend.app import create_app
from backend.service import Services
from backend.store import Store
from backend.providers import normalize_market, parse_book

ROOT = Path(__file__).resolve().parents[1]


class MockExchange:
    environment = "production"
    key = None

    async def get(self, path, params=None):
        if path == "/series":
            return {"series": [{"ticker": "TEST", "title": "Test forecasts",
                                "category": "Other", "tags": []}]}
        if path == "/historical/markets":
            return {"markets": [], "cursor": ""}
        if path == "/historical/cutoff":
            return {"market_settled_ts": "2026-11-01T00:00:00Z"}
        if path == "/markets":
            if (params or {}).get("status") == "settled":
                return {"markets": [{
                    "ticker": "TEST-26-HIST", "event_ticker": "TEST-26",
                    "series_ticker": "TEST", "title": "Past mock outcome",
                    "status": "settled", "result": "no",
                    "settlement_ts": "2026-10-10T00:00:00Z",
                    "created_time": "2026-09-01T00:00:00Z",
                    "notional_value_dollars": "1.0000",
                    "yes_bid_dollars": ".0900", "yes_ask_dollars": ".1100",
                    "volume_fp": "2000",
                }], "cursor": ""}
            return {"markets": [], "cursor": ""}
        if path.startswith("/historical/markets/") and path.endswith("/candlesticks"):
            return {"candlesticks": [{
                "end_period_ts": int(datetime(2026, 10, d, tzinfo=timezone.utc).timestamp()),
                "yes_bid": {"close": ".0900"},
                "yes_ask": {"close": ".1100"},
                "volume_fp": "2000",
            } for d in (6, 7, 8)]}
        raise AssertionError("Unexpected route: "+path)

    async def market(self, ticker):
        return normalize_market({
            "ticker": ticker, "event_ticker": "TEST-OPEN",
            "title": "Mock current contract",
            "status": "open", "notional_value_dollars": "1.0000",
            "yes_bid_dollars": ".3800", "yes_ask_dollars": ".4000",
            "volume_fp": "3000"
        })

    async def book(self, ticker):
        return parse_book({"orderbook_fp": {
            "yes_dollars": [[".3800", "200"]],
            "no_dollars": [[".6000", "200"]]
        }})


def run():
    with tempfile.TemporaryDirectory() as folder:
        service = Services(Store("sqlite:///"+str(Path(folder)/"app.db")))
        service.kalshi = MockExchange()
        app = create_app(service)
        catalog = app.state.desk.catalog
        catalog.put_series([{"ticker": "TEST", "title": "Test forecasts", "category": "Other"}])
        catalog.put_markets([{
            "ticker": "TEST-OPEN-NOW", "event_ticker": "TEST-OPEN",
            "series_ticker": "TEST", "title": "Mock current contract",
            "status": "open", "notional_value_dollars": "1.0000",
            "yes_bid_dollars": ".3800", "yes_ask_dollars": ".4000",
            "volume_fp": "3000"
        }], "test fixture")
        service.store.write("desk_report", {
            "task_type":"trade_construction",
            "question":"Four-leg test fixture combo using seven games at 45%-60%",
            "origin":"test_fixture","status":"incomplete",
            "market_count":0,"selected_series":[],"current_markets":[],
            "acquisition":{"contracts_with_candles":0,"settled_market_count":0,
                           "candles_loaded":0,"partial_universe":True},
            "studies":[],"external":{"status":"not_used","text":"","sources":[]},
            "plan":{"constraints":{"requested_legs":4,
                                  "target_probability_min":.45,
                                  "target_probability_max":.60,
                                  "lookback_games":7}},
            "completion":{"complete":False,"status":"incomplete",
                          "warning":"Research task not fulfilled",
                          "requirements":[{"id":"joint_probability",
                                           "label":"Joint probability",
                                           "status":"blocked",
                                           "reason":"No calibrated model available",
                                           "evidence":[]}]},
            "verified_event":None,
            "trade_review":{"candidate_legs":[],"proposed_legs":[],
                            "game_log_coverage":[],
                            "joint_probability":None,
                            "native_combo_quote":None},
            "limitations":["No verified event or native combo quotation"],
            "evidence":[],"conclusion":"Cannot verify the specified combination."
        })
        with TestClient(app) as client, sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1500, "height": 970})
            errors = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))

            def route(url, opts):
                result = client.request(opts.get("method", "GET"), url,
                                        content=opts.get("body"), headers=opts.get("headers", {}))
                return {"status": result.status_code, "body": result.text,
                        "headers": dict(result.headers)}
            page.expose_function("localBackend", route)
            html = re.sub(r"<link[^>]+>", "", (ROOT/"frontend/desk.html").read_text())
            html = re.sub(r"<script.*?</script>", "", html, flags=re.S)
            page.set_content(html)
            page.add_style_tag(content=(ROOT/"frontend/desk.css").read_text())
            page.evaluate("""window.fetch=async(url,opts={})=>{
              const r=await window.localBackend(url,opts);
              return new Response(r.body,{status:r.status,headers:r.headers});
            };
            if(!crypto.randomUUID)crypto.randomUUID=()=>"test-"+Math.random().toString(16).slice(2);""")
            page.add_script_tag(content=(ROOT/"frontend/desk.js").read_text(), type="module")
            page.wait_for_selector('h1:has-text("What do you want to investigate")')
            assert page.locator('nav .nav').count() == 3
            assert page.locator('text=Mock current contract').count() > 0
            page.locator('button[data-nav="research"]').click()
            page.wait_for_selector('h1:has-text("Your investigations")')
            page.locator('[data-action="report"]:has-text("Four-leg test fixture combo")').click()
            page.wait_for_selector('h1:has-text("Request requirements and verified evidence")')
            assert page.locator('text=This request has NOT been fulfilled').count() > 0
            assert page.locator('text=Historical comparison').count() == 0
            page.locator('button[data-nav="trade"]').click()
            page.wait_for_selector('h1:has-text("Simulate a real-market position")')
            page.locator('button[data-nav="explore"]').click()
            page.locator('button[data-action="ticket"]').first.click()
            page.wait_for_selector('#paper-form')
            page.locator('#paper-form [name="confirm"]').check()
            page.locator('#paper-form [type="submit"]').click()
            page.wait_for_timeout(500)
            assert len(service.store.list("paper_order")) == 1
            page.locator('button[data-nav="explore"]').click()
            page.locator('#question').fill("Investigate the Test forecasts contracts")
            page.locator('#explore-form [type="submit"]').click()
            page.wait_for_timeout(1000)
            assert len(service.store.list("desk_job")) >= 1
            # A real asynchronous research job is working in-process.
            page.wait_for_selector('h1:has-text("Your investigations")', timeout=30000)
            assert len(service.store.list("desk_report")) >= 1
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(200)
            assert page.evaluate("document.documentElement.scrollWidth") <= 400
            assert not errors, errors
            browser.close()
            print("PASS: 3 workspaces, real-only catalogue, paper order, automatic history, research report, mobile.")
if __name__ == "__main__":
    run()
