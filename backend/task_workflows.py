"""Request-specific research workflows and verifiable outcomes.

A multi-leg trade inquiry is NOT routed to generic calibration. Unknown events,
missing sources, absent offers and uncalibrated joint odds are blocking defects.
"""
from __future__ import annotations
import asyncio
import re
import itertools
import math
from datetime import datetime
from typing import Any

from .domain_evidence import SportsEvidence, prop_spec, find_player, game_log_summary, text_key
from .market_catalog import TICKER_PATTERN
from .research_intent import ResearchPlan, completion
from .models import now


def _state(status: str, reason: str, *sources: str):
    return {"status": status, "reason": reason,
            "evidence": [x for x in sources if x]}


def _relation(text: str, teams: list[dict]) -> bool:
    """Require explicit event/team evidence, never generic NFL association."""
    text = str(text or "").lower()
    names = []
    for team in teams:
        names.append([team.get("name","").lower(), team.get("abbreviation","").lower()])
    return all(any(x and re.search(r"\b"+re.escape(x)+r"\b", text) for x in group)
               for group in names)


def structure_candidates(candidates: list[dict], count: int | None,
                         target_low: float | None, target_high: float | None) -> dict:
    """Provisional selection only. Empirical frequencies are NOT predicted probabilities."""
    if not count or count < 2:
        return {"legs":[], "independence_scenario":None, "frechet_scenario":None}
    eligible = [c for c in candidates if c.get("last_games",{}).get("status") == "verified"
                and c.get("last_games",{}).get("observed_frequency") is not None]
    if len(eligible) < count:
        return {"legs":[], "independence_scenario":None, "frechet_scenario":None}
    mid = (target_low+target_high)/2 if target_low is not None and target_high is not None else .50
    best = None
    for group in itertools.islice(itertools.combinations(eligible[:20], count), 6000):
        names = [(x["player_id"],x["stat"]["stat"]) for x in group]
        if len(set(names)) != len(names):
            continue
        rates = [x["last_games"]["observed_frequency"] for x in group]
        independence = math.prod(rates)
        score = abs(independence-mid)
        # Prefer both teams represented where the other criteria tie.
        score += .0001 if len({x["team_id"] for x in group})==1 else 0
        if best is None or score < best[0]:
            best = (score, group, rates, independence)
    if best is None:
        return {"legs":[], "independence_scenario":None, "frechet_scenario":None}
    _, group, rates, independent = best
    lower = max(0.,sum(rates)-len(rates)+1)
    upper = min(rates)
    return {"legs":[{k:v for k,v in leg.items() if k!="raw"} for leg in group],
            "independence_scenario":round(independent,5),
            "frechet_scenario":[round(lower,5),round(upper,5)],
            "warning":"Illustrative calculation using observed seven-game frequencies as if they were true marginals. They are NOT calibrated probabilities; independence is unverified and these bounds are NOT a validated range for the upcoming game."}


def _includes_player(title: str, name: str) -> bool:
    # Full player name must match; ambiguous last names cannot identify a contract.
    normalized = text_key(title)
    candidate = text_key(name)
    return bool(candidate and candidate in normalized)


async def locate_prop_markets(desk, event: dict, max_series=10) -> dict:
    """Fetch real Kalshi markets in relevant sport series. Reject unverified events."""
    catalog = desk.catalog
    matching_series = []
    for term in ("football", "nfl", "player"):
        matching_series.extend(catalog.search_series(term, 20))
    seen = set()
    unique = []
    for row in matching_series:
        if row["ticker"] not in seen:
            seen.add(row["ticker"])
            unique.append(row)
    series = unique[:max_series]
    failures, rows = [], []
    kickoff = datetime.fromisoformat(event["kickoff_utc"])
    for info in series:
        try:
            data = await desk.s.kalshi.get("/markets", {
                "series_ticker": info["ticker"], "status": "open",
                "limit": 100, "mve_filter": "exclude"})
            raw = data.get("markets") or []
            for market in raw:
                if not TICKER_PATTERN.fullmatch(str(market.get("ticker") or "")):
                    continue
                # Retain only contracts within 36h of the verified event kickoff.
                closing = market.get("close_time") or market.get("expected_expiration_time")
                if not closing:
                    continue
                try:
                    delta = abs((datetime.fromisoformat(closing.replace("Z","+00:00"))-kickoff).total_seconds())
                except ValueError:
                    continue
                if delta > 36*3600:
                    continue
                market = {**market, "_series_title":info["title"], "_category":info.get("category")}
                rows.append(market)
        except ValueError as exc:
            failures.append({"series": info["ticker"], "error": str(exc)[:180]})
        await asyncio.sleep(.05)
    return {"markets": rows, "series": series, "failures": failures,
            "total_scanned": len(rows), "series_scanned": len(series),
            "warning": "Only selected current market pages for relevant series were inspected; not exhaustive."}


async def match_verified_props(desk, raw: list[dict], game: dict,
                               player_data: list[dict]) -> dict:
    """Verify current contract details and actual linked event; never invent legs."""
    matched = []
    skipped = {"unrecognized_prop": 0, "unverified_game_relation": 0,
               "unidentified_player": 0, "unavailable_market": 0}
    seen = set()
    for m in raw[:180]:
        ticker = m["ticker"]
        if ticker in seen:
            continue
        seen.add(ticker)
        event_id = m.get("event_ticker") or ""
        if not TICKER_PATTERN.fullmatch(event_id):
            skipped["unverified_game_relation"]+=1
            continue
        title = " ".join(str(m.get(k) or "") for k in
            ("title", "yes_sub_title", "_series_title"))
        spec = prop_spec(title)
        if not spec:
            skipped["unrecognized_prop"]+=1
            continue
        try:
            event = await desk.s.kalshi.get("/events/"+event_id)
            info = event.get("event") or {}
            event_text = " ".join(str(info.get(k) or "") for k in
                ("title", "sub_title", "subtitle"))
            # No independent proof the event matches both teams => reject it.
            if not _relation(event_text, game["teams"]):
                skipped["unverified_game_relation"]+=1
                continue
        except ValueError:
            skipped["unavailable_market"]+=1
            continue
        athletes = [p for team in player_data for p in team.get("players",[])]
        candidates = [p for p in athletes if _includes_player(title,p.get("name",""))]
        player = candidates[0] if len(candidates)==1 else None
        if player is None:
            skipped["unidentified_player"]+=1
            continue
        # No auto-betting. This is only a candidate with provable contract identity.
        matched.append({
            "ticker": ticker, "title": title, "event_ticker": event_id,
            "exchange_event_title": event_text, "player": player.get("name"),
            "player_id": player["id"], "team_id": player["team_id"],
            "stat": spec, "yes_bid": m.get("yes_bid_dollars"),
            "yes_ask": m.get("yes_ask_dollars"),
            "volume": m.get("volume_fp"),
            "evidence": [f"https://kalshi.com/markets/{ticker}",
                         game["source"]],
            "raw": m,
        })
        if len(matched) >= 20:
            break
    return {"candidates": matched, "skipped": skipped,
            "warning": "Verified exchange event and player identity required; partial search cannot establish unavailability."}


async def trade_construction(desk, job_id: str, plan: ResearchPlan,
                             sports: SportsEvidence | None = None) -> dict:
    """Explicitly refuse to certify a combo without independently evidenced joint odds."""
    sports = sports or SportsEvidence()
    c = plan.constraints
    obs: dict[str,dict] = {}
    sources, warnings, logs, trade_legs = [], [], [], []
    event, universe = None, None
    obs["source_provenance"] = _state("partial", "Source documentation alone is not evidence that the actual requested data were obtained.",
                                      "https://docs.kalshi.com/api-reference/market/get-markets")
    obs["request_completion"] = _state("blocked", "Trading request must satisfy all explicit requirements.")
    desk.event(job_id, "Task planning",
               f"Identified trade construction with {c.requested_legs or 'unspecified'} legs, "
               f"date {c.event_date or 'unspecified'}, probability band "
               f"{c.target_probability_min}–{c.target_probability_max}.")
    if c.league == "NFL" and c.event_date:
        desk.event(job_id, "Event verification", "Checking actual scheduled matchup from a separate sports data source.")
        try:
            verified = await sports.verify_nfl_event(c.event_date)
        except ValueError as exc:
            verified = {"status": "provider_unavailable", "game": None,
                        "note": str(exc), "source": ""}
        sources.append({"title": "Event schedule", "url":verified.get("source") or "https://www.espn.com/nfl/schedule"})
        if verified["status"] == "verified":
            event = verified["game"]
            obs["verified_event"] = _state("verified", "Teams and kickoff verified in provider event record.",
                                            event["source"], "provider_event:"+event["id"])
            obs["source_provenance"] = _state("verified", "An event source and original identifier were retrieved.",event["source"])
        else:
            obs["verified_event"] = _state("blocked",verified.get("note", "Cannot uniquely identify event"))
    else:
        obs["verified_event"] = _state("blocked",
            "A verified event identifier is needed. This adapter currently verifies dated NFL games; other markets require matching exchange event IDs or a supported domain provider.")
    if event:
        desk.event(job_id, "Market evidence",
                   "Searching relevant open exchange series and checking event relationships.")
        try:
            universe = await locate_prop_markets(desk, event)
        except ValueError as exc:
            warnings.append(str(exc)[:200])
            universe = {"markets": [],"series": [],"failures": [],"total_scanned":0}
        for team in event["teams"]:
            try:
                history = await sports.previous_games(
                    team["id"], event["kickoff_utc"], c.lookback_games or 7)
                team["previous_games"] = history
                if history["observed"]:
                    all_ids = [x["id"] for x in history["games"]]
                    team["player_data"] = await sports.player_logs(team,all_ids)
            except ValueError as exc:
                team["previous_games"] = {"status":"unavailable","observed":0,"games":[],"error":str(exc)}
        logs = [{"team":t["name"],"team_id":t["id"],
                 "games_requested": c.lookback_games or 7,
                 "games_verified":t["previous_games"].get("observed",0),
                 "game_ids":[g["id"] for g in t["previous_games"].get("games",[])],
                 "source": t["previous_games"].get("source"),
                 "player_count":len(t.get("player_data",{}).get("players",[]))}
                for t in event["teams"]]
        full_logs = all(t["previous_games"].get("observed",0)>=(c.lookback_games or 7)
                        for t in event["teams"])
        obs["player_game_logs"] = _state("partial" if full_logs else "blocked",
            "Each team's completed game IDs are identified; player-level statistics require matching eligible props." if full_logs else
            "Could not verify all requested previous team games from provider records.",
            *[t["previous_games"].get("source","") for t in event["teams"]])
        if universe["markets"]:
            match = await match_verified_props(desk,universe["markets"],event,
                                 [t.get("player_data",{}) for t in event["teams"]])
            for market in match["candidates"]:
                athlete = next((p for t in event["teams"]
                    for p in t.get("player_data",{}).get("players",[])
                    if p["id"]==market["player_id"]),None)
                if athlete:
                    market["last_games"] = game_log_summary(
                        athlete, market["stat"], c.lookback_games or 7)
                market.pop("raw",None)
            trade_legs = match["candidates"]
            warnings.append("Not all contract types and event formats are parsable. See skipped diagnostics.")
            obs["eligible_contracts"] = _state(
                "verified" if trade_legs else "blocked",
                "Only player-prop markets linked to the verified fixture and player name are eligible."
                if trade_legs else "No sufficiently verified current player-prop contract found in bounded scope.",
                *[x["ticker"] for x in trade_legs[:10]])
            obs["market_identification"] = _state(
                "verified" if trade_legs else "partial",
                "Checked live exchange market pages, then event and player identity.",
                *[x["ticker"] for x in trade_legs[:10]])
        else:
            obs["eligible_contracts"] = _state("blocked", "No contract data obtained from scanned exchange series.")
            obs["market_identification"] = _state("partial", "Exchange series searched; no verified relevant contracts.")
    else:
        obs["eligible_contracts"] = _state("blocked", "Verify the event before selecting contracts.")
        obs["market_identification"] = _state("blocked", "Cannot identify tradable contracts without the event.")
    required_count = c.requested_legs
    qualified = [m for m in trade_legs if m.get("last_games",{}).get("status") == "verified"]
    draft=structure_candidates(qualified,required_count,c.target_probability_min,c.target_probability_max)
    if required_count:
        obs["requested_legs"] = _state("verified" if len(draft["legs"]) == required_count else "blocked",
            f"Selected {len(draft['legs'])} provisional research legs from {len(qualified)} evidence-backed candidates; requested {required_count}. "
            "No recommendation or native executable combo is implied.",
            *[m["ticker"] for m in draft["legs"]])
    else:
        obs["requested_legs"] = _state("blocked", "Required exact number of legs was not specified.")
    if draft["legs"] and all(x.get("last_games",{}).get("status")=="verified" for x in draft["legs"]):
        obs["player_game_logs"]=_state("verified",
            "Each selected player's specified last-game sample was retrieved with original provider metrics.",
            *[x["ticker"] for x in draft["legs"]])
    obs["probability_estimates"] = _state("partial" if draft["legs"] else "blocked",
        "Observed past-game frequencies are descriptive and NOT calibrated forward marginal probabilities.")
    obs["joint_probability"] = _state("partial" if draft["legs"] else "blocked",
        "Illustrative independence and Fréchet scenarios can be shown, but no verified multivariate joint model or observed native combo quote is available.")
    obs["exchange_execution_status"] = _state("blocked",
        "Kalshi's multivariate RFQ execution has not been implemented or verified. A set of single-leg orders is not an atomic combo.")
    if c.target_probability_min is not None:
        obs["probability_target"] = _state("blocked",
            "A joint probability model is necessary to test whether the requested range is met.")
    if c.lookback_games and not event:
        obs["player_game_logs"] = _state("blocked","The event must be verified before team game logs can be selected.")
    for item in plan.required:
        if item not in obs:
            obs[item] = _state("blocked","No verified evidence recorded.")
    gates = completion(plan,obs)
    return desk.s.store.write("desk_report", {
        "task_type": plan.intent, "question": plan.query,
        "origin":"user", "status":"incomplete",
        "plan":plan.model_dump(), "completion":gates,
        "verified_event":event,
        "trade_review":{
            "requested_legs": c.requested_legs,
            "candidate_legs": qualified[:20],
            "proposed_legs": draft["legs"], # Research scenario only, never a validated execution ticket.
            "requested_probability_range":[c.target_probability_min,c.target_probability_max],
            "joint_probability":None, "model":"not_calibrated",
            "independence_scenario":draft.get("independence_scenario"),
            "frechet_scenario":draft.get("frechet_scenario"),
            "scenario_warning":draft.get("warning"),
            "native_combo_quote":None, "execution_status":"not_available",
            "game_log_coverage":logs,
            "market_scan": {k:v for k,v in (universe or {}).items() if k not in ("markets",)},
        },
        "market_count":len(universe.get("markets",[])) if universe else 0,
        "current_markets":[],
        "selected_series":(universe or {}).get("series",[]),
        "acquisition":{"settled_market_count":0,"market_pages":0,
                       "candles_loaded":0,"contracts_with_candles":0,
                       "partial_universe":True,
                       "market_errors":(universe or {}).get("failures",[])},
        "studies":[],"external":{"status":"not_used_as_trade_evidence","sources":[],"text":""},
        "limitations":[
            "The specified combo trade has NOT been constructed or probability-verified.",
            "The exchange RFQ flow is not implemented. No live combo can be quoted or executed here.",
            "Recent game logs alone do not identify joint future probability or correlated uncertainty.",
            "Sports provider endpoints are unofficial and may have incomplete or changing coverage.",
            *(warnings[:6]),
        ],
        "evidence":sources+[
            {"title":"Kalshi multivariate event docs",
             "url":"https://docs.kalshi.com/api-reference/events/get-multivariate-events"}],
        "conclusion":("Could not fulfill the requested trade. The exact requested constraints are preserved; "
                      "missing evidence is shown below rather than substituting an unrelated backtest."),
        "real_money_execution":False,
    })


async def event_investigation(desk, job_id: str, plan: ResearchPlan,
                              sports: SportsEvidence | None=None) -> dict:
    """Verify a named event before initiating any generic exploratory study."""
    obs={}
    event=None
    if plan.constraints.league=="NFL" and plan.constraints.event_date:
        try:
            result=await (sports or SportsEvidence()).verify_nfl_event(plan.constraints.event_date)
            event=result.get("game")
            if event:
                obs["verified_event"]=_state("verified","Confirmed actual schedule event.",
                                             event["source"],"provider_event:"+event["id"])
        except ValueError:
            pass
    for name in plan.required:
        obs.setdefault(name,_state("blocked","A verified event and linked market evidence are required."))
    status=completion(plan,obs)
    return desk.s.store.write("desk_report",{
        "task_type":plan.intent,"question":plan.query,"origin":"user",
        "status":"incomplete","plan":plan.model_dump(),
        "completion":status,"verified_event":event,
        "market_count":0,"current_markets":[],"selected_series":[],
        "acquisition":{"settled_market_count":0,"candles_loaded":0,
                       "contracts_with_candles":0,"partial_universe":True},
        "studies":[],"external":{"status":"not_requested","sources":[],"text":""},
        "limitations":["This request requires event-specific evidence and methods not yet available in the selected domain adapter."],
        "evidence":[{"title":"Verified schedule" if event else "Event verification pending",
                     "url":event["source"] if event else "https://docs.kalshi.com/api-reference/events/get-events"}],
        "conclusion":"Event research is incomplete; no unrelated generic backtest was substituted.",
        "real_money_execution":False,
    })
