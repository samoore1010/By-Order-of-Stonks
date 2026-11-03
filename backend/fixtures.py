"""Explicit, reproducible synthetic fixtures. Never a silent fallback for an API failure."""
from datetime import datetime, timedelta, timezone
import random
from .models import now


def dataset() -> dict:
    rng = random.Random(37)
    rows = []
    origin = datetime(2025, 1, 1, tzinfo=timezone.utc)
    for i in range(240):
        start = origin+timedelta(hours=i*12)
        p = rng.uniform(.025, .25)
        outcome = "yes" if rng.random() < p else "no"
        # Balanced toy markets, with sampling noise; no designed guarantee of an edge.
        for j in range(4):
            price = min(.95, max(.01, p+rng.uniform(-.012, .012)))
            ts = (start+timedelta(hours=j*3)).isoformat()
            rows.append({"ticker": f"SAMPLE-{i:04}", "event_id": f"SAMPLE-EVENT-{i//2:04}",
                "category": ["Weather", "Economics", "Sports"][i%3], "observed_at": ts, "available_at": ts,
                "yes_bid": round(max(.001, price-.01), 4), "yes_ask": round(min(.999, price+.01), 4),
                "volume": rng.randint(500, 3000), "outcome": outcome,
                "settled_at": (start+timedelta(hours=24)).isoformat()})
    return {"name": "Synthetic sandbox · 240 contracts", "source": "synthetic", "rows": rows,
        "description": "Seed 37. Generated prices and outcomes, not historical Kalshi data.",
        "coverage": {"start": rows[0]["available_at"], "end": rows[-1]["settled_at"], "contracts": 240},
        "warnings": ["Synthetic fixtures must never qualify a strategy for live deployment."]}


def markets() -> list[dict]:
    titles = ["Phoenix high temperature above 100°F?", "Inflation above the release threshold?",
              "Detroit wins the featured game?", "Rainfall exceeds the daily threshold?",
              "Economic growth exceeds the forecast?", "Player passing yards above the line?"]
    result = []
    for i, title in enumerate(titles):
        bid = [.08, .34, .57, .13, .62, .68][i]
        result.append({"ticker": f"DEMO-{i+1}", "event_id": f"DEMO-EVENT-{i//2+1}", "title": title,
            "category": ["Weather", "Economics", "Sports", "Weather", "Economics", "Sports"][i],
            "yes_bid": bid, "yes_ask": round(bid+.03, 4), "volume": [1400, 5200, 17000, 820, 2800, 9400][i],
            "status": "open", "source": "synthetic", "observed_at": now(),
            "close_time": None, "rules": "Synthetic sandbox instrument. No actual event or exchange order.",
            "binary_supported": True, "result": None})
    return result
