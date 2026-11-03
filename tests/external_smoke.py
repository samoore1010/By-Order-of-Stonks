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
            relevant=[x for x in data.get("series",[]) if any(t in str(x.get("title","")).lower() for t in ("football","nfl","passing yards","receiving yards"))]
            print("Potential football series:",[{k:x.get(k) for k in ("ticker","title","category")} for x in relevant[:16]])
            import re
            targeted=[x for x in data.get("series",[]) if
                      re.search(r"player|passing yards|receiving yards|rushing yards|receptions",str(x.get("title","")),re.I)
                      and str(x.get("category","")).lower()=="sports"]
            print("Player-related sports series:",[{k:x.get(k) for k in ("ticker","title")} for x in targeted[:22]])
            for series in targeted[:12]:
                resp=await c.get("https://external-api.kalshi.com/trade-api/v2/markets",
                    params={"series_ticker":series["ticker"],"status":"open","limit":3},
                    headers={"Accept":"application/json"})
                print("Sample series",series["ticker"],"HTTP",resp.status_code)
                if resp.status_code==200:
                    mk=resp.json().get("markets",[])
                    print("market examples",[{k:x.get(k) for k in ("ticker","title","yes_sub_title","event_ticker","close_time")} for x in mk[:2]])
                    if mk:
                        ev=await c.get("https://external-api.kalshi.com/trade-api/v2/events/"+mk[0]["event_ticker"],headers={"Accept":"application/json"})
                        print("event response",ev.status_code,({k:(ev.json().get("event") or {}).get(k) for k in ("title","sub_title","product_metadata")} if ev.status_code==200 else ""))
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
                rows=(raw.get("boxscore") or {}).get("players",[])
                print("Boxscore stat groups and labels:",[{
                    "name":cat.get("name"),"labels":cat.get("labels"),
                    "athletes":len(cat.get("athletes",[]))} for team in rows[:1] for cat in team.get("statistics",[])[:4]])
                parsed=await source.player_logs(team,[x["id"] for x in logs["games"]])
                print("Parsed athletes:",len(parsed["players"]),"coverage errors:",len(parsed["failed"]))
                if parsed["players"]:
                    print("Sample parsed stat names:",list(next(iter(parsed["players"]))["games"].values())[0].keys())


if __name__ == "__main__":
    asyncio.run(run())
