from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, AwareDatetime, model_validator


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Observation(Strict):
    ticker: str = Field(min_length=1, max_length=160)
    event_id: str = Field(min_length=1, max_length=160)
    category: str = Field(default="Other", max_length=80)
    observed_at: AwareDatetime
    available_at: AwareDatetime
    yes_bid: float = Field(ge=0, le=1)
    yes_ask: float = Field(ge=0, le=1)
    volume: float = Field(ge=0)
    outcome: Literal["yes", "no"]
    settled_at: AwareDatetime
    quote_size: float | None = Field(default=None, ge=0)
    model_probability: float | None = Field(default=None, ge=0, le=1)
    model_asof: AwareDatetime | None = None

    @model_validator(mode="after")
    def valid(self):
        if self.yes_bid > self.yes_ask:
            raise ValueError("Crossed YES quote: bid exceeds ask")
        if not self.observed_at <= self.available_at < self.settled_at:
            raise ValueError("Require observed_at <= available_at < settled_at")
        if (self.model_probability is None) != (self.model_asof is None):
            raise ValueError("Probability estimates require their point-in-time model_asof")
        if self.model_asof and self.model_asof > self.available_at:
            raise ValueError("Model was not available at the decision timestamp")
        return self


class Strategy(Strict):
    name: str = Field(default="Longshot counterparty", min_length=1, max_length=100)
    family: Literal["longshot", "model_edge"] = "longshot"
    side: Literal["yes", "no"] = "no"
    category: str = Field(default="All", max_length=80)
    min_probability: float = Field(default=.02, ge=0, le=1)
    max_probability: float = Field(default=.15, ge=0, le=1)
    min_edge: float = Field(default=.04, ge=0, le=1)
    min_volume: float = Field(default=10, ge=0)
    risk_fraction: float = Field(default=.01, gt=0, le=.1)
    event_cap: float = Field(default=.05, gt=0, le=.25)
    total_cap: float = Field(default=.3, gt=0, le=1)
    sizing: Literal["fixed_fraction", "quarter_kelly"] = "fixed_fraction"

    @model_validator(mode="after")
    def valid(self):
        if self.min_probability > self.max_probability:
            raise ValueError("Minimum probability exceeds maximum")
        if not self.risk_fraction <= self.event_cap <= self.total_cap:
            raise ValueError("Require position risk <= event cap <= portfolio cap")
        if self.sizing == "quarter_kelly" and self.family != "model_edge":
            raise ValueError("Kelly requires independent, timestamped model probabilities")
        return self


class BacktestRequest(Strict):
    dataset_id: str = "synthetic-v1"
    strategy_id: str | None = None
    strategy: Strategy = Field(default_factory=Strategy)
    capital: float = Field(default=10000, ge=100, le=10000000)
    fee_coefficient: float = Field(default=.07, ge=0, le=1)
    slippage: float = Field(default=.005, ge=0, le=.1)
    participation: float = Field(default=.05, gt=0, le=1)
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None

    @model_validator(mode="after")
    def valid(self):
        if self.start and self.end and self.start >= self.end:
            raise ValueError("Start must precede end")
        return self


class ResearchRequest(Strict):
    question: str = Field(min_length=5, max_length=2000)
    dataset_id: str = "synthetic-v1"
    strategy: Strategy = Field(default_factory=Strategy)


class ImportRequest(Strict):
    series: str = Field(pattern=r"^[A-Z0-9-]{1,80}$")
    tickers: list[str] = Field(min_length=1, max_length=20)
    start: AwareDatetime
    end: AwareDatetime
    interval: Literal[60, 1440] = 60

    @model_validator(mode="after")
    def valid(self):
        import re
        if self.start >= self.end or (self.end - self.start).days > 365:
            raise ValueError("Import range must be positive and at most 365 days")
        if any(not re.fullmatch(r"[A-Z0-9.-]{1,160}", t) for t in self.tickers):
            raise ValueError("Invalid ticker")
        return self


class PaperOrder(Strict):
    client_order_id: str = Field(pattern=r"^[a-zA-Z0-9-]{8,80}$")
    ticker: str = Field(pattern=r"^[A-Z0-9.-]{1,160}$")
    side: Literal["yes", "no"]
    quantity: int = Field(ge=1, le=10000)
    limit_price: float = Field(gt=0, lt=1)
    source: Literal["synthetic", "kalshi"] = "synthetic"
    confirm: bool = False


class Schedule(Strict):
    enabled: bool = False
    interval_minutes: int = Field(default=60, ge=15, le=1440)
    dataset_id: str = "synthetic-v1"
    max_jobs_daily: int = Field(default=12, ge=1, le=96)
