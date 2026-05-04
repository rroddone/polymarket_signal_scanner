# Alpha Terminal — Polymarket Signal Scanner

> Turn prediction market sentiment into actionable equity intelligence.

Polymarket is one of the world's most liquid real-money prediction markets. Hundreds of millions of dollars are wagered on geopolitical, macro, and corporate events — events that also move public equities. Alpha Terminal harvests that signal, runs it through a dual-LLM analysis pipeline, and surfaces high-conviction trades through an institutional-grade terminal built for systematic research.

---

## What It Does

1. **Ingests** every active Polymarket market with volume above $1,000 via the Gamma API.
2. **Scores** each market's equity relevance using a skeptical hedge-fund analyst persona (Groq `llama-3.1-8b-instant`, with Gemini 2.0 Flash as failover) on a 1–10 conviction scale.
3. **Alerts** your Discord channel the moment a score ≥ 8 signal is generated.
4. **Backtests** every signal against real 5-min intraday price data to produce per-ticker and aggregate win rates.
5. **Visualises** everything through the Alpha Terminal — a Streamlit dashboard with live harvest monitoring, searchable signal feed, and quantitative audit charts.

---

## System Architecture

```
  Polymarket Gamma API
          │
          ▼
     PolymarketClient                Supabase
     (volume ≥ $1k filter) ────────► markets + market_prices
          │
          ▼
     LLMFactory
     ├─ Groq llama-3.1-8b-instant  (PRIMARY — 30 RPM, 2.5 s/market)
     │    header-aware Retry-After wait on 429, up to 3 retries
     └─ Gemini 2.0 Flash           (FALLBACK — activates on 3× Groq failure)
          │
          ├──► equity_signals ─────────────────────────────────► Supabase
          │    (ticker, relevance_score, impact_type,
          │     rationale, provider, created_at)
          │
          └──► score ≥ 8 ──────────────────────────────────────► Discord Webhook

  YFinanceClient  (5-min intraday bars, 5-day window)
          │
          ▼
     Backtester
     ├─ entry  = bar closest to signal.created_at
     └─ exit   = most recent 5-min bar
     HIT/MISS per impact_type (Bullish → current > entry)
          │
          ├──► backtest_history  (per-ticker rows,  ticker IS NOT NULL)
          └──► backtest_history  (aggregate row,     ticker IS NULL)

  Alpha Terminal  (Streamlit)
  ├─ KPI cards        ← backtest_history aggregate
  ├─ Signal Terminal  ← equity_signals (searchable, filtered)
  └─ Quant Audit      ← backtest_history per-ticker + log
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Database | Supabase (Postgres + PostgREST + RLS) |
| LLM Primary | Groq — `llama-3.1-8b-instant` (30 RPM free tier) |
| LLM Fallback | Gemini 2.0 Flash (Google GenAI SDK) |
| Alerts | Discord Webhook (embed format) |
| Dashboard | Streamlit 1.43+ |
| Charts | Plotly Express |
| Price Data | yfinance (5-min intraday, 5-day window) |
| Scheduling | cron via `cron_utils.py` + `harvest.sh` |

---

## Setup

### 1. Clone and create the virtual environment

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
SUPABASE_URL=https://YOUR_PROJECT_ID.supabase.co
SUPABASE_SERVICE_ROLE_KEY=YOUR_SERVICE_ROLE_KEY
GROQ_API_KEY=YOUR_GROQ_API_KEY
GEMINI_API_KEY=YOUR_GEMINI_API_KEY
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN
NOTIFICATION_EMAIL=your@email.com
```

### 3. Initialize the database

Apply SQL files from `database/` in the Supabase SQL Editor in this order:

```
database/schema_export.sql
database/security_policies.sql
database/seed_data.sql
database/backtest_history_migration.sql
```

---

## How to Run

All operations go through a single entrypoint.

### Harvest — ingest and analyze markets

```bash
python main.py --harvest
```

Groq is tried first at 2.5 s/market. On a 429, the script reads the `Retry-After` header and waits the exact window (up to 3× per market). Gemini activates on persistent Groq failure. Discord alerts fire for `relevance_score ≥ 8`. A circuit breaker exits on 5 consecutive parse failures to protect free-tier quota.

Use `--limit N` to test logic changes on the first N markets only:

```bash
python main.py --harvest --limit 5
```

### Backtest — validate signal accuracy

```bash
python main.py --backtest --limit 10
```

Fetches 5-min yfinance bars, maps each signal's `created_at` to its entry price, and scores HIT or MISS. Results are written to `backtest_history` in Supabase: one row per ticker plus one aggregate row (`ticker IS NULL`) per run.

Run without `--limit` for the full backtest over all signals:

```bash
python main.py --backtest
```

### Dashboard — Alpha Terminal

```bash
python main.py --serve
```

Opens at `http://localhost:8501`. Press Ctrl+C for a clean shutdown.

---

## Discord Alerts — Real-Time Signal Delivery

This is the feature that separates passive research from active edge. Without Discord configured, high-conviction signals accumulate in the database. With it, every score ≥ 8 analysis fires a rich embed notification to your phone within seconds of that market being processed — not at the end of the run, but the moment the verdict is reached.

Discord is free, runs on iOS and Android, and supports per-channel push notifications. Configure it once and you have a systematic signal feed in your pocket, running on free-tier infrastructure.

### Step 1 — Create a webhook

1. Open Discord and create a dedicated server (e.g. `Alpha Terminal`) — or use an existing private server.
2. Add a channel for signals, e.g. `#signals`.
3. Open **Channel Settings → Integrations → Webhooks → New Webhook**.
4. Give it a name (e.g. `Alpha Terminal Bot`) and click **Copy Webhook URL**.

### Step 2 — Add it to `.env`

```env
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN
```

No code changes. The system reads this variable at runtime and activates the alert pipeline automatically.

### Step 3 — Enable mobile push notifications

In the Discord mobile app:

- Go to your server → **Notification Settings** → set the `#signals` channel to **All Messages**.
- In Discord app settings, confirm **Push Notifications** are on.

### What the alert contains

Each notification is a formatted embed with:

| Field | Content |
|---|---|
| Ticker | The equity symbol flagged (e.g. `NVDA`) |
| Impact | `Bullish` or `Bearish` with colour coding |
| Conviction Score | `9 / 10` — the raw score from the LLM |
| Rationale | One-sentence analyst justification |
| Market Link | Direct URL to the underlying Polymarket event |

Alerts fire mid-harvest. If a 150-market run finds a score-9 NVDA signal on market 12, the Discord notification arrives before market 13 starts processing.

> **If the webhook URL is missing or left as a placeholder, the system skips notifications silently — no crash, no error.** Alerts are purely additive and never block the harvest pipeline.

---

## Dashboard Features

**KPI Cards** (sourced from latest `backtest_history` aggregate row)
- Global Win Rate · High-Conviction Accuracy (score ≥ 8) · Signals (24h) · Top Performing Ticker

**Signal Terminal tab**
- Full searchable dataframe with keyword filter across market question, ticker, and rationale
- Sidebar: Ticker multiselect · Sentiment filter · Conviction Score slider

**Quant Audit tab**
- Accuracy by Asset: horizontal bar chart, emerald ≥ 50% / crimson < 50%, 50% dotted baseline
- Backtest Log: 15 most recent per-ticker rows across all runs

**Sidebar controls**
- Refresh · Full Harvest · Small Harvest (--limit 5) · Automation (cron schedule) · Audit Log viewer

**Live Harvest Monitor** — when a harvest runs, the page switches to an exclusive monitor view (refreshes every 2s) with a progress bar, colour-coded log tail, Force Exit, and Terminate controls. Returns to the terminal automatically on completion.

---

## Scoring Rubric

Every analysis uses a conservative hedge-fund analyst persona on a 1–10 scale.

| Score | Label | Criteria |
|---|---|---|
| 9–10 | Critical | Direct, first-order impact on core business or valuation |
| 7–8 | Strong | High-correlation macro event with clear near-term revenue implications |
| 5–6 | Moderate | Indirect link, speculative sentiment, or low-weight revenue driver |
| 1–4 | Tenuous | Atmospheric or stretch connection — not actionable |

Scores ≥ 8 trigger Discord alerts and form the High Conviction cohort in backtest reporting.

---

## Project Structure

```
polymarket_scanner/
├── main.py                    ← CLI: --harvest [--limit N], --backtest [--limit N], --serve
├── harvest.sh                 ← Cron wrapper: python main.py --harvest
│
├── src/
│   ├── core/
│   │   ├── config.py          ← PROJECT_ROOT-derived paths; all env vars; LLM constants
│   │   └── models.py          ← Pydantic: MarketSignal, LLMAnalysisResult, BacktestSummary
│   ├── providers/
│   │   ├── polymarket_client.py  ← Gamma API fetch + Pydantic-validated parse
│   │   ├── yfinance_client.py    ← 5-min intraday bars + closest_close()
│   │   └── llm_factory.py        ← Groq primary + Gemini fallback; header-aware 429 retry
│   ├── utils/
│   │   ├── database.py           ← DatabaseService: all Supabase ops
│   │   ├── notifications.py      ← NotificationService: Discord signal + backtest alerts
│   │   ├── cron_utils.py         ← Lock-file state + crontab r/w helpers
│   │   └── logger.py             ← GracefulExit + setup_logger (auto-creates logs/)
│   └── jobs/
│       ├── harvester.py          ← Harvester: pidfile guard + ingest + analyze pipeline
│       └── backtester.py         ← Backtester: HIT/MISS → backtest_history (per-ticker)
│
├── dashboard/
│   └── app.py                 ← Alpha Terminal: 4 KPI cards, Signal Terminal, Quant Audit
│
├── database/
│   ├── schema_export.sql      ← Canonical DDL for all 5 tables
│   ├── security_policies.sql  ← RLS policies (idempotent)
│   ├── seed_data.sql          ← 23-ticker watchlist seed
│   └── backtest_history_migration.sql  ← backtest_history DDL + ticker column
│
├── tests/
│   └── test_backtest_logic.py ← HIT/MISS smoke test (synthetic signals, real bars)
│
├── docs/                      ← Project documentation
├── logs/                      ← automation.log, app.log (runtime — gitignored)
├── data/                      ← test_results.json (runtime — gitignored)
│
├── .env                       ← Live credentials — never commit
├── .env.example               ← Placeholder template — safe to commit
└── venv/                      ← Python virtual environment
```

---

## Engineering Constraints

- **Volume threshold:** markets with < $1,000 total volume are excluded
- **Alert threshold:** Discord fires for `relevance_score ≥ 8`
- **Circuit breaker:** 5 consecutive API parse failures → `sys.exit(1)`
- **Rate discipline:** `RATE_LIMIT_DELAY_GROQ = 2.5 s` — do not reduce; yields 24 RPM / ~9,100 TPM
- **Secrets:** no credentials in any `.py` file — `.env` only
- **Backtest rows:** `generated_at` is the run-grouping key; `ticker IS NULL` = aggregate row
- **impact_type:** always normalised to `Bullish | Bearish | Neutral` on extraction
