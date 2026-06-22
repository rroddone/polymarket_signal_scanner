# Alpha Terminal — Architecture Specification

Technical reference for the Polymarket Signal Scanner. Covers system design, database schema, module map, triage pipeline, LLM output contract, rate-limit architecture, and data flows.

---

## Tech Stack

| Layer | Technology | Notes |
|---|---|---|
| Language | Python 3.11+ | `src/` package layout |
| Database | Supabase (Postgres + PostgREST) | RLS on all 5 tables |
| LLM Primary | Groq — `llama-3.1-8b-instant` | 30 RPM free tier; 2.5 s/market; header-aware 429 retry |
| LLM Fallback | Gemini 2.0 Flash | Activates after 3 consecutive Groq failures |
| Alerts | Discord Webhook | Rich embeds; fires on `relevance_score ≥ 8` |
| Dashboard | Streamlit 1.43+ | `@st.fragment` live monitor; Alpha Terminal UI |
| Charts | Plotly Express | Dark/institutional palette: Emerald / Crimson / Slate |
| Price Data | yfinance | 5-min intraday bars, 5-day window |
| Scheduling | crontab via `cron_utils.py` | Managed from dashboard sidebar |

---

## Database Schema

### markets
```sql
CREATE TABLE markets (
    id         TEXT PRIMARY KEY,
    slug       TEXT,
    question   TEXT NOT NULL,
    end_date   TIMESTAMPTZ,
    category   TEXT,
    active     BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### market_prices
```sql
CREATE TABLE market_prices (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    market_id  TEXT REFERENCES markets(id),
    price      DECIMAL(3, 2),       -- probability 0.00–1.00
    volume_24h DECIMAL,
    timestamp  TIMESTAMPTZ DEFAULT NOW()
);
```

### equity_signals
```sql
CREATE TABLE equity_signals (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    market_id       TEXT REFERENCES markets(id),
    ticker          TEXT,
    relevance_score INTEGER,         -- 1–10 (0 = LLM-rejected, not persisted)
    impact_type     TEXT,            -- 'Bullish' | 'Bearish' | 'Neutral' | 'None'
    rationale       TEXT,            -- stores fundamental_reasoning from LLM
    citations       JSONB,
    provider        TEXT,            -- 'llama-3.1-8b-instant' | 'gemini-2.0-flash'
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
```

### watchlists
```sql
CREATE TABLE watchlists (
    ticker     TEXT PRIMARY KEY,
    sector     TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
-- 23 tickers seeded: AI/Semiconductors, AI/Technology, Crypto/Exchange,
-- Crypto/Mining, Crypto/Fintech, Space/Technology
```

### backtest_history
```sql
CREATE TABLE backtest_history (
    id                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticker                TEXT,           -- NULL = global aggregate; 'MSTR' = per-ticker
    generated_at          TIMESTAMPTZ NOT NULL,
    pre_market            BOOLEAN NOT NULL DEFAULT false,
    last_bar_date         DATE,
    total_signals         INT,
    judged                INT,            -- non-Neutral signals only
    neutral               INT,
    avg_score             NUMERIC(5, 2),
    overall_win_rate_pct  NUMERIC(5, 1),
    bullish_win_rate_pct  NUMERIC(5, 1),
    bearish_win_rate_pct  NUMERIC(5, 1),
    hc_win_rate_pct       NUMERIC(5, 1),  -- High Conviction (score ≥ 8)
    hc_count              INT,
    hc_hits               INT,
    top3_by_pct           JSONB           -- populated on aggregate row only
);
```

RLS enabled on all tables: service role = full CRUD; anon = SELECT only.

---

## Module Map

```
src/
├── core/
│   ├── config.py        — PROJECT_ROOT-relative paths; all env vars; LLM constants
│   ├── models.py        — Pydantic v2: MarketSignal, LLMAnalysisResult, BacktestSummary
│   └── filters.py       — MarketPreFilter: Stage 1 category gate + Stage 2 keyword blocklist
│
├── providers/
│   ├── polymarket_client.py  — Gamma API fetch (volume ≥$1k); Pydantic-validated output
│   ├── yfinance_client.py    — fetch_intraday() + closest_close() via get_indexer nearest
│   └── llm_factory.py        — Groq primary + Gemini fallback; CoT prompt; MAX_429_RETRIES=3
│                               RATE_LIMIT_DELAY_GROQ=2.5 s; RATE_LIMIT_DELAY_GEMINI=5 s
│
├── utils/
│   ├── database.py      — DatabaseService: upsert_markets, insert_prices, save_signal,
│   │                       load_signals_for_backtest, save_backtest_results (bulk insert)
│   ├── notifications.py — NotificationService: Discord signal alerts (score≥8) + backtest push
│   ├── cron_utils.py    — is_processing(), clear_lock(), get_current_schedule(), update_schedule()
│   └── logger.py        — GracefulExit exception; setup_logger(); auto-rotate > 1 MB
│
└── jobs/
    ├── harvester.py     — Harvester.run(): pidfile guard, triage gate, ingest, analyze, circuit breaker
    └── backtester.py    — Backtester.run(): yfinance bars, HIT/MISS, per-ticker summaries,
                            _build_ticker_summary(), _compute_aggregate() → list[BacktestSummary]
```

---

## 3-Tier Signal Triage Pipeline

Every market passes through three sequential gates before reaching the LLM. Each gate is cheaper than the next; early exits save quota and latency.

```
Polymarket Gamma API
        │
        ▼
 PolymarketClient (Stage 0)
 volume ≥ $1,000 filter
        │
        ▼
 MarketPreFilter.failed_category_gate()  ── Stage 1 ──►  DROP + log [category]
 CATEGORY_BLOCKLIST = {Crypto, Pop Culture, Sports, Politics, Creator Economy}
        │ pass
        ▼
 MarketPreFilter.failed_keyword_blocklist()  ── Stage 2 ──►  DROP + log [keyword]
 compiled regex: XRP|Solana|Dogecoin|NFT|Meme|IPOs?|Strava|Hourly|
                 Up or Down|Price bet|Daily close|2PM ET
        │ pass
        ▼
 LLMFactory.analyze_market()  ── Stage 3 ──►  Chain-of-Thought analysis
 CoT mandate: model must answer "Is there a direct supply chain,
 balance sheet, or macroeconomic transmission mechanism?" before
 selecting a ticker. Tenuous answer → reject (score=0, ticker=null).
        │
        ▼
 Pydantic LLMAnalysisResult validation
 score ≥ 1 + ticker not null → save_signal() → equity_signals
 score = 0 or ticker = null  → skipped (logged, not persisted)
```

### Stage 1 — Category Gate (`src/core/filters.py`)

```python
CATEGORY_BLOCKLIST = frozenset({
    "Crypto", "Pop Culture", "Sports", "Politics", "Creator Economy"
})
```

O(1) frozenset lookup. Zero regex cost.

### Stage 2 — Keyword Blocklist (`src/core/filters.py`)

Compiled once at import time with `re.IGNORECASE`. Word-boundary anchors prevent partial matches (`\bIPOs?\b` blocks "IPO" and "IPOs" but not "depot").

### Stage 3 — LLM Chain-of-Thought (`src/providers/llm_factory.py`)

The prompt mandates an internal CoT block before the model commits to a ticker. Rejection criteria (auto-score 0):
- Connection relies on vague sentiment with no P&L line
- Event is a product announcement/date with no quantifiable impact
- Multiple tickers apply equally (diversified macro, no single vehicle)
- No specific revenue, cost, or balance-sheet line is affected

Three balanced few-shot examples are embedded in every prompt:
1. **Direct macro hit** — Fed 50bps cut → SPY Bullish, score 9
2. **Supply chain hit** — TSMC Taiwan halt → NVDA Bearish, score 8
3. **Hard rejection** — OpenAI SearchGPT release date → None/null, score 0

---

## LLM Output Contract

`LLMAnalysisResult` (Pydantic v2, `src/core/models.py`):

```python
class LLMAnalysisResult(BaseModel):
    fundamental_reasoning: str                            # CoT block
    impact_type: Literal["Bullish", "Bearish", "Neutral", "None"]
    final_ticker: str | None = None                       # null = rejected
    relevance_score: int = Field(ge=0, le=10)

    @model_validator(mode="after")
    def enforce_none_consistency(self):
        # impact_type="None" → final_ticker must be null + score must be 0
        # final_ticker=null  → score must be 0
```

The `fundamental_reasoning` field is stored in the `rationale` DB column (schema unchanged; field renamed in the Python model only).

---

## Data Flows

### Harvest cycle

```
main.py --harvest
    └── Harvester.run()
            ├── PolymarketClient.fetch_markets()       →  markets + market_prices (Supabase)
            ├── MarketPreFilter (Stage 1 + 2)          →  drop noise; log dropped count
            ├── DatabaseService.fetch_unanalyzed_markets()
            └── loop: LLMFactory.analyze_market(question, watchlist)
                    ├── Groq primary → JSON parse → LLMAnalysisResult (Pydantic)
                    │   on 429: Retry-After wait → retry (max 3)
                    │   on 3× fail: Gemini fallback
                    ├── score ≥ 1 + ticker not null:
                    │   DatabaseService.save_signal()  →  equity_signals (Supabase)
                    │   score ≥ 8: NotificationService.send_signal_alert()  →  Discord
                    └── consecutive_errors ≥ 5: sys.exit(1)  [circuit breaker]
```

### Backtest cycle

```
main.py --backtest [--limit N]
    └── Backtester.run()
            ├── DatabaseService.load_signals_for_backtest()  →  equity_signals rows
            ├── YFinanceClient.fetch_intraday(ticker)         →  5-min OHLCV DataFrame
            ├── YFinanceClient.closest_close(df, ts)          →  entry price
            ├── _calc_verdict(impact, entry, current)         →  HIT | MISS | N/A
            ├── _build_ticker_summary(ticker, rows, …)        →  BacktestSummary (per ticker)
            ├── _compute_aggregate(rows, judged, …)           →  list[BacktestSummary]
            └── DatabaseService.save_backtest_results(list)  →  backtest_history (Supabase)
                 N ticker rows (ticker IS NOT NULL) + 1 aggregate (ticker IS NULL)
                 all sharing the same generated_at timestamp as run key
```

### Dashboard data sources

| UI element | Table | Filter |
|---|---|---|
| KPI cards | `backtest_history` | `ticker IS NULL`, latest `generated_at` |
| Accuracy by Asset chart | `backtest_history` | `ticker IS NOT NULL`, latest `generated_at` |
| Backtest Log table | `backtest_history` | `ticker IS NOT NULL`, last 15 rows |
| Signal Terminal | `equity_signals` | `Score > 0` top-level gate + sidebar filters |
| Signals (24h) KPI | `equity_signals` | `created_at > now() - 24h` |
| Triage Audit Log | `equity_signals` | `Score == 0` (LLM rejections) |

---

## Rate-Limit Architecture

```
Groq llama-3.1-8b-instant (PRIMARY)
  RATE_LIMIT_DELAY_GROQ   = 2.5 s   →  24 effective RPM (30 RPM cap)
  MAX_429_RETRIES         = 3
  On 429: reads x-ratelimit-reset-requests header → waits exact window
  Fallback sequence: [90s, 180s, 360s] if no header
  max_tokens = 500 (CoT block ~150 tok + JSON fields ~30 tok)
  Free tier TPM ceiling: 14,400 TPM for 8b — safe at this budget

Gemini 2.0 Flash (FALLBACK)
  RATE_LIMIT_DELAY_GEMINI = 5 s     →  12 effective RPM (15 RPM cap)
  MAX_429_RETRIES         = 3
  On 429: reads Retry-After or retryDelay field → waits exact window
  max_output_tokens = 600
  Activates only after 3 consecutive Groq failures per market
```

---

## Key Constants

```python
# src/core/config.py
GROQ_MODEL              = "llama-3.1-8b-instant"
GEMINI_MODEL            = "gemini-2.0-flash"
PRIMARY_LLM             = "GROQ"

# src/providers/llm_factory.py
RATE_LIMIT_DELAY_GROQ   = 2.5    # never reduce — free-tier TPM budget
RATE_LIMIT_DELAY_GEMINI = 5
MAX_429_RETRIES         = 3
MAX_RETRIES             = 4      # generic API error retries
MIN_RELEVANCE_SCORE     = 1      # score=0 → skip, not saved

# src/utils/database.py
CLEANUP_DAYS            = 30     # market_prices retention window

# src/providers/polymarket_client.py
VOLUME_THRESHOLD        = 1_000  # minimum market volume to ingest

# src/utils/notifications.py
ALERT_THRESHOLD         = 8      # minimum score to trigger Discord alert

# src/jobs/harvester.py
CIRCUIT_BREAKER_THRESHOLD = 5    # consecutive parse failures → sys.exit(1)
```

---

## Engineering Constraints

- **No credentials in `.py` files** — `.env` only; `_get_secret()` reads env then `st.secrets`
- **Harvest guard** — pidfile at `/tmp/polymarket_analyze.pid`; `harvest.lock` prevents cron overlap
- **Duplicate analysis prevention** — `fetch_unanalyzed_markets()` excludes markets already in `equity_signals`
- **Log rotation** — `setup_logger()` trims `automation.log` to last 500 lines when it exceeds 1 MB
- **Pre-market detection** — backtester warns if most recent yfinance bar is from a prior trading day
- **Backtest grouping key** — `generated_at` timestamp shared by all rows in a single run; `ticker IS NULL` = aggregate
- **Dashboard Score > 0 gate** — `df_signals = df_all[df_all["Score"] > 0]` applied before all sidebar filters
