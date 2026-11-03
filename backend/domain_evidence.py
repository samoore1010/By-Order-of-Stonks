"""Verified domain evidence adapters.

No model prose is accepted as event identity or game statistics. Adapters use
fixed, read-only provider URLs and return original source links with coverage.
ESPN's publicly exposed site API is an optional, unofficial source and may
change or restrict access. Fail closed when its schema or access changes.
"""
from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
ESPN_TEAM_SCHEDULE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{team_id}/schedule"
ESPN_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary"
GAME_DATE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")


def _valid_date(raw: str) -> date:
    if not GAME_DATE.fullmatch(raw):
        raise ValueError("Date must be YYYY-MM-DD")
    return date.fromisoformat(raw)


def _iso(raw: str) -> datetime | None:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError):
        return None


def text_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


class SportsEvidence:
    def __init__(self, transport=None):
        self.transport = transport

    async def _get(self, url: str, params: dict) -> dict:
        # The caller cannot supply arbitrary URLs to the transport.
        if not (url.startswith("https://site.api.espn.com/apis/site/v2/sports/football/nfl/")):
            raise ValueError("Sports data host not allowlisted")
        try:
            if self.transport is not None:
                data = await self.transport(url, params)
            else:
                async with httpx.AsyncClient(timeout=18, follow_redirects=False) as client:
                    res = await client.get(url, params=params,
                        headers={"Accept": "application/json", "User-Agent": "ByOrderOfStonks/0.3 research"})
                    res.raise_for_status()
                    data = res.json()
            if not isinstance(data, dict):
                raise ValueError("Unexpected sports provider schema")
            return data
        except (httpx.HTTPError, ValueError) as exc:
            raise ValueError("Sports data currently unavailable: " + str(exc)[:140]) from exc

    async def verify_nfl_event(self, target_date: str, supplied_teams: list[str] | None = None) -> dict:
        """Verify an actual scheduled NFL event, with provider event id and teams."""
        target = _valid_date(target_date)
        payload = await self._get(ESPN_SCOREBOARD, {"dates": target.strftime("%Y%m%d")})
        games = []
        for event in payload.get("events", []):
            played = _iso(event.get("date"))
            if not played or played.date() not in (
                target,  # ESPN supplies actual kickoff date in UTC.
                # A late local game can fall on the following UTC day.
                date.fromordinal(target.toordinal()+1),
            ):
                continue
            competition = (event.get("competitions") or [{}])[0]
            contestants = []
            for c in competition.get("competitors") or []:
                team = c.get("team") or {}
                if not team.get("id"):
                    continue
                contestants.append({
                    "id": str(team["id"]),
                    "name": team.get("displayName") or team.get("name") or "",
                    "abbreviation": team.get("abbreviation") or "",
                    "home_away": c.get("homeAway"),
                })
            if len(contestants) != 2 or not event.get("id"):
                continue
            games.append({
                "id": str(event["id"]), "title": event.get("name") or event.get("shortName") or "",
                "kickoff_utc": played.isoformat(),
                "teams": contestants,
                "competition": "NFL", "status": (event.get("status") or {}).get("type", {}).get("name"),
                "source": ESPN_SCOREBOARD+"?dates="+target.strftime("%Y%m%d"),
            })
        supplied_teams = supplied_teams or []
        if supplied_teams:
            wanted = [text_key(t) for t in supplied_teams]
            games = [g for g in games if all(
                any(t in text_key(c["name"]) or t == text_key(c["abbreviation"]) for c in g["teams"])
                for t in wanted)]
        if len(games) == 1:
            return {"status": "verified", "game": games[0], "candidates": games,
                    "source": games[0]["source"], "note": "Event identity verified with ESPN schedule."}
        return {"status": "ambiguous" if games else "not_found", "game": None,
                "candidates": games[:10], "source": ESPN_SCOREBOARD+"?dates="+target.strftime("%Y%m%d"),
                "note": ("Multiple scheduled games match; identify the teams."
                         if games else "No provider-verified game matched the requested date and teams.")}

    async def previous_games(self, team_id: str, before: str, count: int) -> dict:
        """Get distinct completed event IDs prior to event kickoff."""
        if not re.fullmatch(r"\d{1,8}", str(team_id)):
            raise ValueError("Invalid team identifier")
        limit = min(max(count, 1), 30)
        kickoff = _iso(before)
        if not kickoff:
            raise ValueError("Invalid reference kickoff")
        url = ESPN_TEAM_SCHEDULE.format(team_id=team_id)
        payload = await self._get(url, {"season": str(kickoff.year)})
        valid = {}
        for event in payload.get("events", []):
            event_id = str(event.get("id") or "")
            dt = _iso(event.get("date") or "")
            if not event_id.isdigit() or not dt or dt >= kickoff:
                continue
            status = ((event.get("competitions") or [{}])[0].get("status") or
                      event.get("status") or {}).get("type") or {}
            # ESPN may use completed=true at event level.
            completed = bool(status.get("completed") or
                             (event.get("status") or {}).get("type", {}).get("completed"))
            if not completed:
                continue
            contenders = (event.get("competitions") or [{}])[0].get("competitors") or []
            if contenders and not any(str((x.get("team") or {}).get("id")) == str(team_id)
                                  for x in contenders):
                continue
            valid[event_id] = {"id": event_id, "date": dt.isoformat(),
                               "source": url+"?season="+str(kickoff.year)}
        ordered = sorted(valid.values(), key=lambda e: e["date"], reverse=True)
        return {"status": "verified" if len(ordered)>=limit else "partial",
                "games": ordered[:limit], "requested": limit,
                "observed": min(len(ordered), limit), "source": url,
                "note": "Only verified completed games before kickoff are eligible."}

    async def player_logs(self, team: dict, game_ids: list[str]) -> dict:
        """Read exact player box-score metrics by ESPN's own column labels."""
        if len(game_ids) > 30:
            raise ValueError("Too many requested game IDs")
        by_player = {}
        failed = []
        for event_id in game_ids:
            if not re.fullmatch(r"\d{1,12}", event_id):
                continue
            try:
                payload = await self._get(ESPN_SUMMARY, {"event": event_id})
            except ValueError as exc:
                failed.append({"game": event_id, "error": str(exc)})
                continue
            players = ((payload.get("boxscore") or {}).get("players") or [])
            for roster in players:
                if str((roster.get("team") or {}).get("id")) != str(team["id"]):
                    continue
                for category in roster.get("statistics") or []:
                    labels = category.get("labels") or []
                    group = category.get("name") or category.get("displayName") or ""
                    for athlete in category.get("athletes") or []:
                        player = athlete.get("athlete") or {}
                        ident = str(player.get("id") or "")
                        if not ident:
                            continue
                        stats = athlete.get("stats") or []
                        if not isinstance(stats, list) or not isinstance(labels, list):
                            continue
                        record = by_player.setdefault(ident, {
                            "id": ident, "name": player.get("displayName") or "",
                            "team_id": str(team["id"]), "games": {}
                        })
                        game = record["games"].setdefault(event_id, {})
                        # Use both statistic group and original label to disambiguate YDS.
                        for label, value in zip(labels, stats):
                            game[str(group).lower()+":"+str(label).lower()] = str(value)
            await asyncio.sleep(.08)
        output = []
        for r in by_player.values():
            output.append({"id": r["id"], "name": r["name"],
                           "team_id": r["team_id"], "games": r["games"],
                           "observed_games": len(r["games"])})
        return {"status": "partial" if failed else "retrieved", "players": output,
                "games_requested": len(game_ids), "failed": failed[:15],
                "source": ESPN_SUMMARY+"?event={verified_event_id}",
                "note": "Stats are raw official-boxscore-labeled values. No predictive model is implied."}


def prop_spec(title: str) -> dict | None:
    """Parse only unambiguous YES-side player statistic propositions.

    'Over', 'under', and inclusive strike rules have different payoffs.
    Never silently treat a BELOW contract as an ABOVE contract.
    """
    text = str(title or "").strip()
    patterns = [
        ("passing_yards", r"\b(?:passing|pass)\s+yards?\b"),
        ("rushing_yards", r"\b(?:rushing|rush)\s+yards?\b"),
        ("receiving_yards", r"\b(?:receiving|reception)\s+yards?\b"),
        ("receptions", r"\b(?:receptions?|catches)\b"),
        ("passing_touchdowns", r"\b(?:passing|pass)\s+touchdowns?\b"),
    ]
    found = [k for k,p in patterns if re.search(p,text,re.I)]
    if len(found) != 1:
        return None
    kind = found[0]
    comparative = re.search(
        r"\b(over|more\s+than|above|at\s+least|under|below|less\s+than|fewer\s+than|at\s+most)\s+(\d+(?:\.\d+)?)\b",
        text, re.I)
    threshold = None
    comparator = None
    if comparative:
        all_clauses = re.findall(r"\b(?:over|more\s+than|above|at\s+least|under|below|less\s+than|fewer\s+than|at\s+most)\s+\d+(?:\.\d+)?\b",text,re.I)
        if len(set(x.lower() for x in all_clauses)) > 1:
            return None
        threshold = float(comparative.group(2))
        op = comparative.group(1).lower().replace(" ","")
        comparator = (">=" if op == "atleast" else "<=" if op == "atmost" else
                      "<" if op in ("under","below","lessthan","fewerthan") else ">")
    else:
        plus = re.search(r"\b(\d+(?:\.\d+)?)\+\s*(?:passing|rushing|receiving)\s+yards?\b",text,re.I)
        if plus:
            threshold = float(plus.group(1))
            comparator = ">="
    if threshold is None or comparator is None:
        return None
    return {"stat":kind,"threshold":threshold,"operator":comparator,
            "direction":"under" if comparator.startswith("<") else "over",
            "source_text":text}


def exceeds(value: float, operator: str, threshold: float) -> bool:
    if operator==">":return value>threshold
    if operator==">=":return value>=threshold
    if operator=="<":return value<threshold
    if operator=="<=":return value<=threshold
    raise ValueError("Unsupported proposition operator")


def metric_value(game: dict, stat: str) -> float | None:
    mapping = {
        "passing_yards": ("passing:yds", "passing:yards"),
        "rushing_yards": ("rushing:yds", "rushing:yards"),
        "receiving_yards": ("receiving:yds", "receiving:yards"),
        "receptions": ("receiving:rec", "receiving:receptions"),
        "passing_touchdowns": ("passing:td", "passing:tds"),
    }
    for key in mapping.get(stat, ()):
        value = game.get(key)
        if value is None:
            continue
        try:
            return float(str(value).replace(",", ""))
        except ValueError:
            continue
    return None


def find_player(name: str, athletes: list[dict]) -> dict | None:
    wanted = text_key(name)
    matches = [p for p in athletes if text_key(p.get("name")) == wanted]
    return matches[0] if len(matches) == 1 else None


def game_log_summary(player: dict, prop: dict, required: int) -> dict:
    values = [v for game in player.get("games", {}).values()
              if (v := metric_value(game, prop["stat"])) is not None]
    result = {
        "player": player.get("name"), "metric": prop["stat"],
        "threshold": prop["threshold"], "requested_games": required,
        "observed_games": len(values),
        "values": values[-required:],
        "source": "ESPN verified game boxscores",
        "status": "partial" if len(values) != required else "verified",
    }
    if len(values) == required:
        successes = sum(exceeds(x,prop.get("operator",">"),prop["threshold"]) for x in values[-required:])
        result.update({"success_count": successes, "observed_frequency": round(successes/required, 4),
                       "note": "Descriptive past-game frequency, NOT a calibrated probability for the upcoming game."})
    return result
