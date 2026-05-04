# Alpha Terminal — Project Summary

## Why This Exists

Prediction markets are priced by people with skin in the game. When Polymarket moves on a geopolitical event, a regulatory ruling, or an earnings surprise, that collective bet often leads equity price discovery by hours or days. Alpha Terminal was built to systematically harvest that edge — ingesting every active market, scoring its equity impact with an LLM trained to think like a skeptical fund analyst, and validating those scores against real intraday price data.

The goal is a repeatable, auditable signal pipeline that turns crowd intelligence into structured trade ideas.

---

## Architecture in Three Layers

### 1. Harvest Pipeline

On each cycle, `PolymarketClient` fetches every active market with volume above $1,000 from the Gamma API. Each market's question is sent to `LLMFactory`, which uses Groq `llama-3.1-8b-instant` as the primary engine (30 RPM free tier, 2.5 s/market). The LLM returns a structured JSON: `ticker`, `relevance_score` (1–10), `impact_type` (Bullish / Bearish / Neutral), and a one-sentence rationale.

On a 429, the pipeline reads the `x-ratelimit-reset-requests` header and sleeps exactly that window — no guessing, no exponential backoff thrash. After 3 retries, Gemini 2.0 Flash takes over for that market. A circuit breaker exits cleanly on 5 consecutive parse failures to protect free-tier quota.

Signals with `relevance_score ≥ 8` fire an immediate Discord embed alert. Every signal records which provider generated it for full auditability.

### 2. Ticker-Aware Backtesting

The `Backtester` fetches 5-min yfinance bars for each ticker in the signal set, maps each signal's `created_at` to the nearest bar (entry price), and compares against the most recent bar (exit price). Verdict is simple and symmetric:

- **Bullish → HIT** if `current > entry`
- **Bearish → HIT** if `current < entry`
- **Neutral → excluded** from all win-rate calculations

Each run writes one row per ticker plus one global aggregate row (`ticker IS NULL`) to `backtest_history` in Supabase. The shared `generated_at` timestamp is the run-grouping key — no post-processing needed in the dashboard.

### 3. Alpha Terminal Dashboard

`main.py --serve` opens a Streamlit dashboard with two tabs and four top-level KPI cards (Global Win Rate, HC Accuracy, Signals 24h, Top Ticker) sourced directly from the latest aggregate backtest row.

**Signal Terminal** is a searchable, filterable dataframe of all equity signals. Sidebar controls offer Ticker multiselect, Sentiment filter, and a Conviction Score slider. Inline keyword search scans market question, ticker, and rationale simultaneously.

**Quant Audit** presents a horizontal bar chart of win rate per ticker (emerald ≥ 50%, crimson < 50%, 50% dotted baseline) and a 15-row backtest log. When a harvest is in flight, the page switches to an exclusive live monitor — progress bar, colour-coded log tail, and Terminate control — then transitions back automatically on completion.

---

## Discord Alerts — The Real-Time Edge

The dashboard is for analysis. Discord is for action.

Every signal scored ≥ 8 fires a rich embed notification to Discord the moment that market's analysis completes — not batched at the end of the run, but inline, mid-harvest. On a 150-market cycle, a score-9 NVDA signal on market 12 reaches your phone before market 13 starts. That latency is the point.

Discord runs on iOS and Android with per-channel push notifications. Pair it with a dedicated private server and you have an institutional alert feed running entirely on free-tier infrastructure.

**Setup takes under two minutes:**

1. In Discord, open a server (or create one) and add a `#signals` channel.
2. **Channel Settings → Integrations → Webhooks → New Webhook** → copy the URL.
3. Paste it into `.env`:
   ```env
   DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN
   ```
4. On mobile: set the `#signals` channel to **All Messages** and enable push notifications.

**Each alert includes:** ticker, Bullish/Bearish verdict, conviction score, one-sentence rationale, and a direct link to the Polymarket event. If the webhook URL is absent or left as a placeholder, the system skips silently — alerts are additive and never interrupt the harvest pipeline.

---

## Validated Metrics

| Metric | Result |
|---|---|
| Backtest architecture | Per-ticker rows + aggregate row confirmed in Supabase |
| MSTR win rate (10-signal smoke test) | 60% overall (3/5 judged) |
| Bullish hit rate | 100% (3/3) |
| Bearish hit rate | 0% (0/2) |
| High Conviction (≥ 8) accuracy | 75% (3/4) |
| Dashboard cold-start → Ctrl+C | Exit code 0, no traceback |

---

## How to Run

### Prerequisites

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env   # fill in Supabase, Groq, Gemini, Discord keys
# Apply database/ SQL files in Supabase SQL Editor
```

### Harvest

```bash
python main.py --harvest           # all unanalyzed markets
python main.py --harvest --limit 5 # dry-run: first 5 only
```

### Backtest

```bash
python main.py --backtest --limit 10  # quick smoke-test
python main.py --backtest             # full run over all signals
```

Best run after 9:30 AM ET. The pre-market detector warns if the most recent yfinance bar is from a prior trading day.

### Dashboard

```bash
python main.py --serve
# Opens http://localhost:8501  ·  Ctrl+C for clean shutdown
```

### Automated harvesting

```bash
bash harvest.sh    # production entry point; cron-safe; manages harvest.lock
```

The Automation panel in the dashboard sidebar sets the cron schedule (hours + minutes) without touching crontab directly.

---

## Build History

| Phase | Milestone |
|---|---|
| 1–6 | Foundation: ingestion, LLM analysis, Discord alerts, dashboard, DB security |
| 7–10 | Rate-limit hardening, no-search mode, dashboard polish |
| 11–13 | Groq as primary LLM; Gemini failover; dynamic provider labels |
| 14–15 | Live harvest monitor fragment; token budget optimisation; 429 elimination |
| 16 | Unified monitor; audit log browser; initial backtest engine |
| 17 | Full `src/` package refactor — clean modular layout under `src/core`, `providers`, `utils`, `jobs` |
| 18 | Standardised project structure: `logs/`, `data/`, `database/`, `tests/` |
| 19 | Ticker-aware backtesting — per-ticker rows in `backtest_history` |
| 20 | Alpha Terminal overhaul — 4 KPI cards, Quant Audit tab, final polish |
