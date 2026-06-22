# Alpha Terminal — Polymarket Signal Scanner

> Turn prediction market sentiment into actionable equity intelligence.

## 🚀 Live Demo

**[Alpha Terminal → Live on Streamlit Cloud](https://polymarketsignalscanner-284zlymjaoam9mhiuj5fcm.streamlit.app/)**

> **Note:** For the best experience, use the **🧪 Quick Scan** button in the sidebar to generate live signals on your first visit.

---

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
     3-Tier Triage Gate (MarketPreFilter)
     ├─ Stage 1: Category blocklist  {Crypto, Sports, Politics, ...}  ──► DROP
     ├─ Stage 2: Keyword regex  {XRP, NFT, Meme, IPOs?, Daily close, ...}  ► DROP
     └─ Stage 3: LLM Chain-of-Thought analysis (pass only)
          │
          ▼
     LLMFactory
     ├─ Groq llama-3.1-8b-instant  (PRIMARY — 30 RPM, 2.5 s/market)
     │    header-aware Retry-After wait on 429, up to 3 retries
     └─ Gemini 2.0 Flash           (FALLBACK — activates on 3× Groq failure)
          │
          ├──► score ≥ 1 + ticker not null:
          │    equity_signals ───────────────────────────────────► Supabase
          │    (ticker, relevance_score, impact_type,
          │     rationale, provider, created_at)
          │
          ├──► score = 0 or ticker = null: skipped (logged, not persisted)
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
  ├─ Signal Terminal  ← equity_signals (Score > 0, searchable, filtered)
  ├─ Quant Audit      ← backtest_history per-ticker + log
  └─ Triage Audit Log ← equity_signals (Score = 0, LLM rejections)
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

## Prerequisites

Before you run anything, have these four things ready:

| Requirement | Purpose | Where to get it |
|---|---|---|
| **Supabase project** | Database for signals, markets, and backtest history | [supabase.com](https://supabase.com) — free tier |
| **Groq API key** | Primary LLM — ultra-fast inference, 30 RPM free tier | [console.groq.com](https://console.groq.com) |
| **Gemini API key** | Fallback LLM — activates if Groq hits its rate ceiling | [aistudio.google.com](https://aistudio.google.com/app/apikey) |
| **Discord Webhook URL** | Real-time signal alerts to your phone | See the [Discord Alerts](#discord-alerts--real-time-signal-delivery) section below |

---

## Installation

### 1. Create the virtual environment

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

### 3. Mount the Database (Supabase)

This project uses Supabase (PostgreSQL) as its live data store. The database ships empty — signals are generated in real time by the scanner, not bundled with the repo.

**a. Create a Supabase project**

Log in at [supabase.com](https://supabase.com), create a new project, and copy your **Project URL** and **service role key** from **Settings → API** into your `.env`.

**b. Open the SQL Editor**

In the Supabase left-hand sidebar, click the **SQL Editor** icon (`>_`).

**c. Run the setup scripts in order**

Open each file from the `/database` folder in this repo, copy its contents into the SQL Editor, and run it. The order is critical:

| # | File | What it does |
|---|---|---|
| 1 | `schema_export.sql` | Creates all five tables |
| 2 | `security_policies.sql` | Applies Row Level Security (RLS) rules |
| 3 | `seed_data.sql` | Seeds the 23-ticker watchlist |
| 4 | `backtest_history_migration.sql` | Adds the backtest audit table |

> **Your database will be empty after this step — that is expected.** Alpha Terminal is a live-data engine. It has no historical data to ship because the signals it generates are tied to real Polymarket markets at the moment of analysis. To populate it for the first time, launch the app and hit **🧪 Quick Scan** in the sidebar.

---

## Getting Started — The Control Center

There are two ways to pilot the scanner. For most users, **Option A is all you need.**

### Option A: The Alpha Terminal (Recommended)

Launch the dashboard and run everything from the UI:

```bash
python main.py --serve
```

Opens at `http://localhost:8501`. The sidebar is your control center:

| Button | What it does |
|---|---|
| **🚀 Full Harvest** | Scans all active Polymarket markets — thorough, production run |
| **🧪 Quick Scan** | Scans the first 5 markets — instant feedback, zero quota burn |
| **🔄 Refresh** | Pulls the latest signals from the database without re-running |
| **🤖 Automation** | Sets a cron schedule so harvests run unattended (e.g. every 4 h) |

**First time?** Hit **🧪 Quick Scan** — it processes the first 5 markets, costs zero meaningful quota, and populates the Signal Terminal in under 30 seconds. Once you can see signals in the table, the full pipeline is confirmed working. Then hit **🚀 Full Harvest** to go live.

As a harvest runs, the page switches to a live monitor: real-time progress bar, colour-coded log feed, and a Terminate button. The moment it completes, the Signal Terminal auto-refreshes and any score ≥ 8 signals have already hit your Discord.

Press Ctrl+C in the terminal for a clean shutdown.

### Option B: Command Line Interface

For automation, cron jobs, or when you want direct control:

```bash
# Full harvest — ingest and analyze all unanalyzed markets
python main.py --harvest

# Quick test — first 5 markets only, safe for logic changes
python main.py --harvest --limit 5

# Backtest — validate signal accuracy against intraday price data
python main.py --backtest --limit 20

# Full backtest over all signals
python main.py --backtest
```

Groq runs first at 2.5 s/market. On a 429, the pipeline reads the `Retry-After` header and waits the exact window — no guessing. Gemini 2.0 Flash takes over on persistent failure. Discord alerts fire mid-harvest for every `relevance_score ≥ 8`.

For fully automated background harvesting:

```bash
bash harvest.sh   # cron-safe; manages harvest.lock to prevent duplicate runs
```

Use the **Automation panel** in the dashboard sidebar to set the schedule (hours + minutes) without touching crontab directly.

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

## What the Dashboard Shows

**Four KPI cards** sit at the top of every page, sourced live from the latest backtest run:
- Global Win Rate · High-Conviction Accuracy (score ≥ 8) · Signals Generated (24h) · Top Performing Ticker

**Signal Terminal tab** — the live signal feed. Search and filter by ticker, market question, or rationale text. Sidebar controls narrow by Sentiment and Conviction Score. Every row links directly back to its Polymarket event.

**Quant Audit tab** — quantitative validation. A horizontal bar chart shows win rate per ticker from the most recent backtest (emerald ≥ 50%, crimson < 50%, 50% dotted baseline). Below it, the Backtest Log shows the 15 most recent per-ticker rows across all runs.

**Audit Log** — toggle the 📜 icon in the sidebar to open a searchable, reversed log viewer showing the last 500 lines of `automation.log`. Filter by ticker, status code, or keyword.

---

## Scoring Rubric

Every analysis uses a Chain-of-Thought prompt that forces the model to answer: *"Is there a direct, highly-documented supply chain, balance sheet, or macroeconomic transmission mechanism?"* before committing to a ticker. A tenuous answer produces `score=0, ticker=null` and is never persisted.

| Score | Label | Criteria |
|---|---|---|
| 9–10 | Critical | Direct, first-order impact on core business or valuation |
| 7–8 | Strong | High-correlation macro event with clear near-term revenue implications |
| 5–6 | Moderate | Indirect link, speculative sentiment, or low-weight revenue driver |
| 1–4 | Tenuous | Atmospheric or stretch connection — not actionable |
| 0 | Rejected | No specific P&L line affected; connection is vague sentiment or announcement noise |

Scores ≥ 8 trigger Discord alerts and form the High Conviction cohort in backtest reporting. Score-0 rejections are visible in the **Triage Audit Log** in the dashboard.

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
│   │   ├── models.py          ← Pydantic: MarketSignal, LLMAnalysisResult, BacktestSummary
│   │   └── filters.py         ← MarketPreFilter: Stage 1 category gate + Stage 2 keyword regex
│   ├── providers/
│   │   ├── polymarket_client.py  ← Gamma API fetch + Pydantic-validated parse
│   │   ├── yfinance_client.py    ← 5-min intraday bars + closest_close()
│   │   └── llm_factory.py        ← Groq primary + Gemini fallback; CoT prompt; 429 retry
│   ├── utils/
│   │   ├── database.py           ← DatabaseService: all Supabase ops
│   │   ├── notifications.py      ← NotificationService: Discord signal + backtest alerts
│   │   ├── cron_utils.py         ← Lock-file state + crontab r/w helpers
│   │   └── logger.py             ← GracefulExit + setup_logger (auto-creates logs/)
│   └── jobs/
│       ├── harvester.py          ← Harvester: pidfile guard + triage gate + ingest + analyze
│       └── backtester.py         ← Backtester: HIT/MISS → backtest_history (per-ticker)
│
├── dashboard/
│   └── app.py                 ← Alpha Terminal: 4 KPI cards, Signal Terminal, Quant Audit, Triage Log
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
