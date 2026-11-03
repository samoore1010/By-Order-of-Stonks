"""Regression suite for intent-preserving research.

All sports/exchange data here are synthetic TEST FIXTURES, never investment data.
"""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.research_intent import classify, completion
from backend.domain_evidence import SportsEvidence, prop_spec, metric_value
from backend.task_workflows import trade_construction
from backend.service import Services
from backend.store import Store
from backend.desk import Desk, ResearchInput


def test_combo_request_is_not_misrouted_to_generic_backtest():
    plan = classify(
        "Build a 4 leg combo for Thursday night NFL using only player props, "
        "using each team's last 7 games and target 45%-60% joint probability.",
        current=datetime(2026, 11, 3, 21, tzinfo=timezone.utc))
    assert plan.intent == "trade_construction"
    assert plan.constraints.requested_legs == 4
    assert plan.constraints.target_probability_min == pytest.approx(.45)
    assert plan.constraints.target_probability_max == pytest.approx(.60)
    assert plan.constraints.lookback_games == 7
    assert plan.constraints.market_filter == "player_prop"
    assert plan.constraints.event_date == "2026-11-05"
    assert plan.constraints.league == "NFL"
    assert "joint_probability" in plan.required
    assert "player_game_logs" in plan.required


def test_unrelated_market_comparison_routes_to_history():
    plan = classify("Compare profitability of weather and economic announcements")
    assert plan.intent == "comparative_backtest"
    assert "historical_samples" in plan.required
    assert "requested_legs" not in plan.required


def test_unavailable_requirements_remain_incomplete():
    plan = classify("Build a 4 leg combo for Thursday NFL player props at 45%-60%")
    result = completion(plan, {"verified_event": {"status":"verified", "evidence":["provider-event-3"]},
                               "requested_legs": {"status":"verified", "evidence":["FOO-1","FOO-2","FOO-3","FOO-4"]}})
    assert not result["complete"]
    assert "Joint probability" in result["missing"]
    assert result["status"] == "incomplete"
    forged = completion(plan, {"joint_probability":{"status":"verified"}})
    assert "Joint probability" in forged["missing"]


def test_exact_statistic_mapping_avoids_using_rushing_yards_as_passing():
    data={"passing:yds":"210","rushing:yds":"15"}
    assert metric_value(data,"passing_yards") == 210
    assert metric_value(data,"rushing_yards") == 15
    assert metric_value(data,"receiving_yards") is None
    assert prop_spec("John Smith passing yards over 200") == {
        "stat":"passing_yards","threshold":200., "direction":"over",
        "source_text":"John Smith passing yards over 200"}


async def fixture_transport(url, params):
    if "scoreboard" in url:
        return {"events":[{"id":"12345","name":"North Wolves at South Hawks",
                 "date":"2026-11-06T01:15:00Z",
                 "competitions":[{"competitors":[
                    {"team":{"id":"1","displayName":"North Wolves","abbreviation":"NW"},"homeAway":"away"},
                    {"team":{"id":"2","displayName":"South Hawks","abbreviation":"SH"},"homeAway":"home"}]}]}]}
    return {"events":[]}


def test_schedule_verifier_returns_actual_event_ids_not_model_guess():
    adapter=SportsEvidence(transport=fixture_transport)
    result=asyncio.run(adapter.verify_nfl_event("2026-11-05"))
    assert result["status"]=="verified"
    assert result["game"]["id"]=="12345"
    assert {t["name"] for t in result["game"]["teams"]}=={"North Wolves","South Hawks"}


class SportsFixture:
    async def verify_nfl_event(self, target_date, supplied_teams=None):
        game={"id":"12345","title":"North Wolves at South Hawks",
              "kickoff_utc":"2026-11-06T01:15:00+00:00",
              "teams":[{"id":"1","name":"North Wolves","abbreviation":"NW"},
                       {"id":"2","name":"South Hawks","abbreviation":"SH"}],
              "source":"https://site.api.espn.com/fixture"}
        return {"status":"verified","game":game,"source":game["source"]}

    async def previous_games(self, team_id, before, count):
        return {"status":"verified","observed":count,"requested":count,
                "games":[{"id":str(i),"date":"2026-10-01T00:00:00Z"} for i in range(1,count+1)],
                "source":"https://site.api.espn.com/fixture_schedule"}

    async def player_logs(self, team, game_ids):
        player_names=(["John Smith","Bob Smith"] if team["id"]=="1"
                      else ["Jane Doe","Alice Doe"])
        players=[]
        for i,name in enumerate(player_names):
            stat=("passing:yds" if "Smith" in name else "receiving:yds")
            players.append({"id":str(team["id"])+str(i+1),"team_id":team["id"],"name":name,
                            "games":{x:{stat:"215" if stat=="passing:yds" else "65"}
                                     for x in game_ids}})
        return {"status":"retrieved","players":players,"games_requested":len(game_ids),"failed":[]}


class KalshiFixture:
    def __init__(self):
        self.base="https://external-api.kalshi.com/trade-api/v2"

    async def get(self,path,params=None):
        if path=="/markets":
            markets=[
               {"ticker":"TEST-GAME-1","event_ticker":"TEST-EVT","title":"John Smith passing yards over 200"},
               {"ticker":"TEST-GAME-2","event_ticker":"TEST-EVT","title":"Bob Smith passing yards over 180"},
               {"ticker":"TEST-GAME-3","event_ticker":"TEST-EVT","title":"Jane Doe receiving yards over 40"},
               {"ticker":"TEST-GAME-4","event_ticker":"TEST-EVT","title":"Alice Doe receiving yards over 50"},
            ]
            return {"markets":[{**m,"close_time":"2026-11-06T01:15:00Z",
                "yes_bid_dollars":"0.3000","yes_ask_dollars":"0.3400",
                "volume_fp":"100"} for m in markets]}
        if path=="/events/TEST-EVT":
            return {"event":{"title":"North Wolves vs South Hawks"}}
        raise AssertionError("Unexpected exchange API call "+path)


def test_four_candidate_legs_are_not_misrepresented_as_verified_combo(tmp_path):
    desk=Desk(Services(Store("sqlite:///"+str(tmp_path/"test.db"))))
    desk.s.kalshi=KalshiFixture()
    desk.catalog.put_series([{"ticker":"TEST","title":"NFL football player props",
                              "category":"Sports"}])
    plan=classify("Build a 4-leg combo for Thursday night NFL football using player props, "
                  "each team's last 7 games and 45%-60% overall probability",
                  current=datetime(2026,11,3,21,tzinfo=timezone.utc))
    job=desk.enqueue(ResearchInput(question=plan.query,include_web=False))
    result=asyncio.run(trade_construction(desk,job["id"],plan,sports=SportsFixture()))
    assert result["task_type"]=="trade_construction"
    assert result["status"]=="incomplete"
    assert result["verified_event"]["id"]=="12345"
    assert len(result["trade_review"]["candidate_legs"])==4
    assert len(result["trade_review"]["proposed_legs"])==4
    assert result["trade_review"]["independence_scenario"] is not None
    assert result["trade_review"]["frechet_scenario"] is not None
    assert result["trade_review"]["joint_probability"] is None
    assert not result["completion"]["complete"]
    assert result["studies"]==[]
    assert "Joint probability" in result["completion"]["missing"]


class MissingSports:
    async def verify_nfl_event(self,*args,**kwargs):
        return {"status":"not_found","game":None,"note":"No verified matchup",
                "source":"https://site.api.espn.com/fixture"}


def test_unverified_event_blocks_trade_without_unrelated_backtest(tmp_path):
    desk=Desk(Services(Store("sqlite:///"+str(tmp_path/"unknown.db"))))
    plan=classify("Build 4-leg NFL combo for Thursday using last 7 games at 45%-60%",
                  current=datetime(2026,11,3,21,tzinfo=timezone.utc))
    job=desk.enqueue(ResearchInput(question=plan.query,include_web=False))
    result=asyncio.run(trade_construction(desk,job["id"],plan,sports=MissingSports()))
    assert result["verified_event"] is None
    assert result["studies"]==[]
    assert result["status"]=="incomplete"
    assert "Verified event" in result["completion"]["missing"]


def test_comparison_captures_every_express_market_type():
    plan=classify("Compare NFL player props versus moneyline versus spread profitability")
    assert plan.intent=="comparative_backtest"
    assert set(plan.constraints.compare_groups)=={
        "Player performance","Match winner","Margin / spread"
    }
    assert "requested_group_coverage" in plan.required


def test_conversational_update_changes_only_explicit_leg_count():
    original=("Build 4-leg combo for Thursday night NFL player props, "
              "last 7 games, target 45%-60% joint probability.")
    changed=classify(original+"\nUpdated requirement: Make it 3 legs instead.",
                     current=datetime(2026,11,3,21,tzinfo=timezone.utc))
    assert changed.constraints.requested_legs==3
    assert changed.constraints.lookback_games==7
    assert changed.constraints.event_date=="2026-11-05"
    assert changed.constraints.target_probability_min==pytest.approx(.45)
    assert changed.constraints.target_probability_max==pytest.approx(.60)
