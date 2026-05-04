from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class MarketSignal(BaseModel):
    id: str
    slug: str | None = None
    question: str
    category: str
    end_date: str | None = None
    probability: float = Field(ge=0.0, le=1.0)
    volume: float = Field(ge=0.0)
    market_count: int = Field(default=1, ge=1)

    @field_validator("probability")
    @classmethod
    def round_probability(cls, v: float) -> float:
        return round(v, 2)


class LLMAnalysisResult(BaseModel):
    ticker: str
    impact_type: str
    rationale: str
    relevance_score: int = Field(ge=1, le=10)

    @field_validator("impact_type")
    @classmethod
    def normalise_impact(cls, v: str) -> str:
        v = v.strip()
        if v in ("Bullish", "Bearish", "Neutral"):
            return v
        lower = v.lower()
        if "bullish" in lower:
            return "Bullish"
        if "bearish" in lower:
            return "Bearish"
        return "Neutral"


class BacktestSummary(BaseModel):
    # NULL → global aggregate row; set to e.g. "MSTR" for per-ticker rows
    ticker: str | None = None
    generated_at: str
    pre_market: bool
    last_bar_date: str | None
    total_signals: int
    judged: int
    neutral: int
    avg_score: float
    overall_win_rate_pct: float | None
    bullish_win_rate_pct: float | None
    bearish_win_rate_pct: float | None
    hc_win_rate_pct: float | None
    hc_count: int
    hc_hits: int
    top3_by_pct: list[dict[str, Any]]
