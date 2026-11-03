"""Optional external connectivity smoke check using only public data.

This intentionally never loads Kalshi credentials, account balances or trade
APIs. It runs only in CI with network access and reports provider availability.
"""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.domain_evidence import SportsEvidence


async def run():
    async with httpx.AsyncClient(timeout=18,follow_redirects=False) as c:
        response=await c.get(
            "https://external-api.kalshi.com/trade-api/v2/series",
            params={"limit": 1}, headers={"Accept":"application/json"})
        print("Kalshi /series HTTP:",response.status_code)
        if response.status_code == 200:
            data=response.json()
            print("Kalshi series schema:",list(data.keys())[:10])
            print("series returned:",len(data.get("series",[])))
        response=await c.get(
            "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
            params={"dates":"20261105"},headers={"Accept":"application/json"})
        print("Public sports scoreboard HTTP:",response.status_code)
        if response.status_code == 200:
            games=response.json().get("events",[])
            print("Scheduled event examples:",[
                {"id":g.get("id"),"name":g.get("name"),"date":g.get("date")}
                for g in games[:4]])
    if response.status_code == 200:
        r=await SportsEvidence().verify_nfl_event("2026-11-05")
        print("Provider-verified matching game:",{
            "status":r["status"],"title":(r.get("game")or{}).get("title"),
            "teams":[t["name"] for t in (r.get("game")or{}).get("teams",[])]})
        if r.get("game"):
            team=r["game"]["teams"][0]
            logs=await SportsEvidence().previous_games(team["id"],r["game"]["kickoff_utc"],7)
            print("Verified completed games before kickoff:",logs.get("observed"),"of",logs.get("requested"))
            if logs.get("games"):
                first=logs["games"][0]["id"]
                source=SportsEvidence()
                raw=await source._get(
                    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary",
                    {"event":first})
                print("Latest completed game boxscore keys:",list((raw.get("boxscore")or{}).keys()))
                print("Player statistics teams returned:",len((raw.get("boxscore")or{}).get("players",[])))


if __name__ == "__main__":
    asyncio.run(run())
