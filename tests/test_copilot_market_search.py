"""Market topic searches must report their coverage, not claim exhaustive discovery."""
import asyncio
from types import SimpleNamespace
from backend.copilot import dispatch


class FakeDesk:
    def __init__(self):
        self.calls = []
        self.kalshi = SimpleNamespace(market=self.detail)

    async def markets(self, source, series, cursor=""):
        self.calls.append((source, series, cursor))
        if not cursor:
            return {"markets": [{"ticker": "ABC", "title": "Football match"}], "cursor": "next"}
        return {"markets": [{"ticker": "SENATE-1", "title": "Senate control after midterms"}], "cursor": "still-more"}

    async def detail(self, ticker):
        return {"ticker": ticker, "status": "open", "rules": "Verified exchange rules"}


def test_market_search_reports_partial_coverage():
    desk = FakeDesk()
    result = asyncio.run(dispatch(desk, "search_kalshi_markets",
                                  {"query": "Senate midterm elections", "max_pages": 2}))
    assert result["matches_returned"] == 1
    assert result["markets"][0]["ticker"] == "SENATE-1"
    assert result["pages_scanned"] == 2
    assert result["observations_scanned"] == 2
    assert result["more_pages_available"] is True
    assert "not an exhaustive" in result["coverage_warning"]
    assert len(desk.calls) == 2


def test_market_search_no_match_is_not_a_negative_availability_claim():
    desk = FakeDesk()
    result = asyncio.run(dispatch(desk, "search_kalshi_markets",
                                  {"query": "Space launch", "max_pages": 1}))
    assert result["matches_returned"] == 0
    assert result["more_pages_available"] is True
    assert result["pages_scanned"] == 1


def test_market_details_requires_exact_ticker():
    desk = FakeDesk()
    result = asyncio.run(dispatch(desk, "kalshi_market_details", {"ticker": "senate-1"}))
    assert result["ticker"] == "SENATE-1"
