## Tech Stack

| Layer | Technology | Notes |
|---|---|---|
| Language | Python 3.11+ | `src/` package layout |
| Database | Supabase (Postgres + PostgREST) | RLS on all 5 tables |
| LLM Primary | Groq — `llama-3.1-8b-instant` | 30 RPM free tier; 2.5 s/market; header-aware 429 retry |
| LLM Fallback | Gemini 2.0 Flash | Activates after 3 consecutive Groq failures |
| Alerts | Discord Webhook | Rich embeds; fires on `relevance_score ≥ 8` |
| Dashboard | Streamlit 1.32+ | `@st.fragment` live monitor; Alpha Terminal UI |
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
    relevance_score INTEGER,         -- 1–10
    impact_type     TEXT,            -- 'Bullish' | 'Bearish' | 'Neutral'
    rationale       TEXT,
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
│   └── models.py        — Pydantic v2: MarketSignal, LLMAnalysisResult, BacktestSummary
│
├── providers/
│   ├── polymarket_client.py  — Gamma API fetch (volume ≥$1k); Pydantic-validated output
│   ├── yfinance_client.py    — fetch_intraday() + closest_close() via get_indexer nearest
│   └── llm_factory.py        — Groq primary + Gemini fallback; MAX_429_RETRIES=3 each
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
    ├── harvester.py     — Harvester.run(): pidfile guard, ingest, analyze, circuit breaker (5×)
    └── backtester.py    — Backtester.run(): yfinance bars, HIT/MISS, per-ticker summaries,
                            _build_ticker_summary(), _compute_aggregate() → list[BacktestSummary]
```

---

## Data Flow

### Harvest cycle

```
main.py --harvest
    └── Harvester.run()
            ├── PolymarketClient.fetch_markets()  →  markets + market_prices (Supabase)
            ├── DatabaseService.fetch_unanalyzed_markets()
            └── loop: LLMFactory.analyze_market(question, watchlist)
                    ├── Groq primary  →  JSON parse  →  LLMAnalysisResult (Pydantic)
                    │   on 429: Retry-After wait → retry (max 3)
                    │   on 3× fail: Gemini fallback
                    ├── DatabaseService.save_signal()  →  equity_signals (Supabase)
                    ├── score ≥ 8: NotificationService.send_signal_alert()  →  Discord
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

| UI element | Table / Source | Filter |
|---|---|---|
| KPI cards | `backtest_history` | `ticker IS NULL`, latest `generated_at` |
| Accuracy by Asset chart | `backtest_history` | `ticker IS NOT NULL`, latest `generated_at` |
| Backtest Log table | `backtest_history` | `ticker IS NOT NULL`, last 15 rows |
| Signal Terminal table | `equity_signals` | sidebar filters + keyword search |
| Signals (24h) KPI | `equity_signals` | `created_at > now() - 24h` |

---

## Rate-Limit Architecture

```
Groq llama-3.1-8b-instant (PRIMARY)
  RATE_LIMIT_DELAY_GROQ   = 2.5 s   → 24 effective RPM (30 RPM cap)
  MAX_429_RETRIES         = 3
  On 429: reads x-ratelimit-reset-requests header → waits exact window
  Prompt: ~180 tokens; max_tokens=200 → ~380 tok/call × 24 RPM ≈ 9,100 TPM
  Free tier TPM ceiling: 6,000 TPM for 70b; 14,400 TPM for 8b ← safe

Gemini 2.0 Flash (FALLBACK)
  RATE_LIMIT_DELAY_GEMINI = 5 s     → 12 effective RPM (15 RPM cap)
  MAX_429_RETRIES         = 3
  On 429: reads Retry-After or retryDelay → waits exact window
  max_output_tokens=300 (prevents verbose quota burn on failover)
  Activates only after 3 consecutive Groq failures per market
```

---

## Key Constants (src/core/config.py)

```python
GROQ_MODEL              = "llama-3.1-8b-instant"
GEMINI_MODEL            = "gemini-2.0-flash"
PRIMARY_LLM             = "GROQ"
RATE_LIMIT_DELAY_GROQ   = 2.5    # never reduce — free-tier TPM budget
RATE_LIMIT_DELAY_GEMINI = 5
MAX_429_RETRIES         = 3
VOLUME_THRESHOLD        = 1_000  # in DatabaseService
CLEANUP_DAYS            = 30     # market_prices retention
```
