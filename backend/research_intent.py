"""Typed research intents, constraints and honest completion gates.

An LLM may help plan, but hard requirements are extracted independently from
the user's original text. A generic backtest cannot fulfill a trade-build task.
"""
from __future__ import annotations
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Literal

from pydantic import BaseModel, Field, ConfigDict, model_validator

Intent = Literal["trade_construction", "comparative_backtest",
                 "market_investigation", "event_analysis"]
DAY_NAMES = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
             "friday": 4, "saturday": 5, "sunday": 6}


class Constraints(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requested_legs: int | None = Field(default=None, ge=2, le=12)
    target_probability_min: float | None = Field(default=None, ge=0, le=1)
    target_probability_max: float | None = Field(default=None, ge=0, le=1)
    lookback_games: int | None = Field(default=None, ge=1, le=30)
    market_filter: str | None = None
    relative_day: str | None = None
    event_date: str | None = None
    league: str | None = None
    exact_ticker: str | None = None

    @model_validator(mode="after")
    def valid(self):
        if self.target_probability_min is not None and self.target_probability_max is not None:
            if self.target_probability_min > self.target_probability_max:
                raise ValueError("Probability range bounds reversed")
        return self


class ResearchPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Intent
    query: str
    constraints: Constraints
    required: list[str]
    capability: str
    explanation: str


class Gate(BaseModel):
    id: str
    label: str
    required: bool = True
    status: Literal["verified", "partial", "blocked", "not_applicable"] = "blocked"
    evidence: list[str] = Field(default_factory=list)
    reason: str = ""


def _target_date(text: str, current: datetime) -> tuple[str | None, str | None]:
    days = list(re.finditer(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", text, re.I))
    match = days[-1] if days else None
    if match:
        day = match.group(1).lower()
        local = current.astimezone(ZoneInfo("America/New_York"))
        target = local.date() + timedelta(days=(DAY_NAMES[day] - local.weekday()) % 7)
        return day, target.isoformat()
    dates = list(re.finditer(r"\b(20\d{2})-(\d{2})-(\d{2})\b", text))
    match = dates[-1] if dates else None
    if match:
        return None, match.group()
    return None, None


def classify(question: str, current: datetime | None = None) -> ResearchPlan:
    text = question.strip()
    q = text.lower()
    if not text:
        raise ValueError("Research request cannot be empty")
    current = current or datetime.now(ZoneInfo("America/New_York"))
    trade_terms = any(x in q for x in
        ("combo", "parlay", "multi-leg", "multi leg", "leg trade", "leg bet",
         "put together a trade", "build a trade", "construct a trade"))
    compare_terms = any(x in q for x in
        ("compare", "versus", " vs ", "relative profitability", "more profitable",
         "better historical", "difference between"))
    intent: Intent = ("trade_construction" if trade_terms else
                      "comparative_backtest" if compare_terms else
                      "event_analysis" if any(x in q for x in
                        ("this game", "this matchup", "this event", "upcoming game",
                         "thursday night", "tonight's game", "the match")) else
                      "market_investigation")
    leg_matches = list(re.finditer(r"\b(\d{1,2})[\s-]*(?:legs?|selections?)\b", q))
    leg_matches += list(re.finditer(r"\b(?:legs?|selections?)\s*(?:of|:)?\s*(\d{1,2})\b", q))
    legs = max(leg_matches, key=lambda m:m.start()) if leg_matches else None
    nlegs = int(legs.group(1)) if legs else None
    if nlegs is not None and not 2 <= nlegs <= 12:
        raise ValueError("Supported trade construction requires between 2 and 12 legs")
    # Explicit ranges only. Never convert an unrequested probability to an edge.
    pbs = list(re.finditer(r"(\d{1,3}(?:\.\d+)?)\s*%\s*(?:-|–|to|through|and)\s*(\d{1,3}(?:\.\d+)?)\s*%", q))
    pb = pbs[-1] if pbs else None
    low, high = ((float(pb.group(1))/100, float(pb.group(2))/100) if pb else (None, None))
    looks = list(re.finditer(r"(?:last|past|previous|prior|most recent)\s+(\d{1,2})\s+(?:games?|matches?|events?)", q))
    look = looks[-1] if looks else None
    lookback = int(look.group(1)) if look else None
    day, at = _target_date(text, current)
    ticker = re.search(r"\b(?:ticker|contract)\s*[:=]\s*([A-Z0-9.-]{3,160})\b", text)
    league = "NFL" if re.search(r"\bNFL\b|thursday night football", text, re.I) else None
    # Only label explicit filters; otherwise leave the market universe open.
    filt = ("player_prop" if "player prop" in q else
            "moneyline" if "moneyline" in q else
            "spread" if "spread" in q else None)
    constraints = Constraints(
        requested_legs=nlegs,
        target_probability_min=low,
        target_probability_max=high,
        lookback_games=lookback,
        market_filter=filt,
        relative_day=day,
        event_date=at,
        league=league,
        exact_ticker=ticker.group(1) if ticker else None
    )
    required = ["market_identification", "source_provenance", "request_completion"]
    capability = "market_catalog"
    if intent == "trade_construction":
        required += ["verified_event", "eligible_contracts", "requested_legs",
                     "probability_estimates", "joint_probability",
                     "exchange_execution_status"]
        if lookback:
            required.append("player_game_logs")
        if low is not None:
            required.append("probability_target")
        capability = "trade_assembly"
    elif intent == "comparative_backtest":
        required += ["historical_samples", "consistent_rules", "reproducible_metrics"]
        capability = "historical_comparison"
    elif intent == "event_analysis":
        required += ["verified_event", "relevant_evidence"]
        capability = "event_verification"
    else:
        required += ["market_coverage", "testable_hypothesis"]
        capability = "market_research"
    return ResearchPlan(intent=intent, query=text, constraints=constraints,
        required=required, capability=capability,
        explanation={
            "trade_construction": "Construct the requested trade and verify event, each leg, joint probability and execution availability.",
            "comparative_backtest": "Assemble comparable historical groups, run consistent assumptions and report uncertainty.",
            "event_analysis": "Identify the actual event first; retrieve only related contracts and evidence.",
            "market_investigation": "Identify relevant real markets and formulate testable hypotheses."
        }[intent])


def completion(plan: ResearchPlan, observations: dict[str, dict[str, Any]]) -> dict:
    """Require explicit evidence; a model's prose cannot satisfy a gate."""
    gates = []
    for name in plan.required:
        result = observations.get(name) or {}
        status = result.get("status", "blocked")
        if status not in ("verified", "partial", "blocked", "not_applicable"):
            status = "blocked"
        evidence = result.get("evidence") or []
        if not isinstance(evidence, list):
            evidence = []
        # A 'verified' verdict must cite a concrete artifact or data source.
        if status == "verified" and not evidence:
            status = "blocked"
        gates.append(Gate(id=name, label=name.replace("_", " ").capitalize(),
                          status=status, evidence=[str(v)[:260] for v in evidence[:10]],
                          reason=str(result.get("reason", ""))[:650]).model_dump())
    mandatory = [g for g in gates if g["required"]]
    satisfied = bool(mandatory) and all(g["status"] == "verified" for g in mandatory)
    return {
        "complete": satisfied,
        "status": "completed" if satisfied else "incomplete",
        "requirements": gates,
        "missing": [g["label"] for g in mandatory if g["status"] != "verified"],
        "warning": (None if satisfied else
                    "The requested task is NOT fulfilled. Do not present partial data as a completed trade or supported edge."),
    }
