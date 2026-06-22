from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


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
    fundamental_reasoning: str
    impact_type: Literal["Bullish", "Bearish", "Neutral", "None"]
    final_ticker: str | None = None
    relevance_score: int = Field(ge=0, le=10)

    @model_validator(mode="after")
    def enforce_none_consistency(self) -> "LLMAnalysisResult":
        if self.impact_type == "None":
            if self.final_ticker is not None:
                raise ValueError("final_ticker must be null when impact_type is 'None'")
            if self.relevance_score != 0:
                raise ValueError("relevance_score must be 0 when impact_type is 'None'")
        if self.final_ticker is None and self.relevance_score != 0:
            raise ValueError("relevance_score must be 0 when final_ticker is null")
        return self


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
