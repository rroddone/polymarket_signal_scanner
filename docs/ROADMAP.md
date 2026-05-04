# Roadmap — Polymarket Signal Scanner

---

## ✅ Completed

### Core Pipeline
- [x] Polymarket Gamma API ingestion (`ingest.py`) — 3 categories, volume ≥ $1k filter
- [x] Supabase schema — 4 tables, RLS, DDL exports
- [x] Groq primary LLM (`llama-3.3-70b-versatile`) + Gemini 2.0 Flash fallback
- [x] Skeptical Analyst rubric — 4-band scoring, chain-of-thought (rationale before score)
- [x] Bulletproof JSON parser — `first_{` to `last_}` slicer + innermost-fragment fallback
- [x] Lean Context injection — last 5 signals appended to every prompt (anti-drift)
- [x] GracefulExit — clean stop on Groq 429, no death spiral, partial counts logged
- [x] Header-aware 429 retry — `_groq_429_wait()` reads `Retry-After` / `x-ratelimit-reset-*` headers; exponential fallback [90s, 180s, 360s]; MAX_429_RETRIES=3
- [x] Circuit breaker — 5 consecutive failures → `sys.exit(1)`
- [x] Discord alerts — rich embeds, score ≥ 8 threshold, graceful skip if unconfigured

### Dashboard & UX
- [x] Streamlit dashboard (`app.py`) — sidebar filters, metric cards, signal table
- [x] Live Intelligence Feed — real-time harvest log streaming (subprocess + select)
- [x] Progress bar with live signal-capture count
- [x] **🔬 Intelligence Feed** + **📊 Market Analytics** two-tab layout
- [x] Analytics tab — avg score by ticker, volume by sector, score distribution histogram, top-5, bull/bear split
- [x] `compute_analytics()` with `@st.cache_data(ttl=60)` — no redundant Supabase queries
- [x] Lock-aware Start button — disabled + warning when `harvest.lock` exists
- [x] Kill Switch (🛑 Cancel/Kill Harvest) — `pgrep -f` → SIGTERM → SIGKILL + `clear_lock()`
- [x] Harvest Activity Monitor — color-coded `automation.log` tail, hibernate badge, Refresh button
- [x] `_render_log_html()` — per-line HTML color coding (amber/red/green/orange/indigo/gray)
- [x] Agent Pulse hibernate detection — 8-line tail, "💤 Hibernating" caption on rate-limit wait
- [x] **Live Progress Tracking** — `@st.fragment(run_every=2)` monitor; `[X/Y]` progress bar; UTF-8-safe log read; broad regex; emergency line dump
- [x] **Process Management** — PID-based Terminate button reads `/tmp/polymarket_analyze.pid`; `st.stop()` exclusive monitor view; disabled Refresh during harvest; `harvest.lock` backed Cancel survives refresh

### Automation
- [x] `harvest.sh` — lock file + `trap EXIT`, venv activation, sequential ingest + analyze
- [x] `cron_utils.py` — crontab read/write, lock state, `make_cron_expression()`, `parse_cron_to_hm()`
- [x] Sidebar "🤖 Autonomous Agent Control" — toggle, Hours/Minutes selectors, schedule status, lock management
- [x] Nuke & Reset button (fixed for bigint PK)

### Observability
- [x] Dual-handler logging — `StreamHandler(stdout)` + `FileHandler(automation.log)`
- [x] `_flush_logs()` before all `sys.exit()` paths
- [x] Pidfile guard (`/tmp/polymarket_analyze.pid`) — detects duplicate instances
- [x] Guarded imports with explicit `IMPORT ERROR:` message on `ModuleNotFoundError`
- [x] `DEBUG: Starting analysis for market N/total: slug` print at loop start

---

## 🔴 Current — High Priority

### ~~1. API Rate-Limit Stability~~ ✅ Resolved (2026-04-29)
Groq `Retry-After` header confirmed: **713-second rate-limit window** (~12 min) for 70b model.
Pivot to `llama-3.1-8b-instant` (30 RPM) resolved throughput. `RATE_LIMIT_DELAY_GROQ = 2.5s`.
Full details in `DEVELOPMENT_LOG.md` Fix 8 + Fix 10.

### ~~2. Restore Automation Log~~ ✅ Restored (2026-04-29)
`harvest.sh` now writes to `automation.log` via `>> "$LOG_FILE" 2>&1`.
`analyze.py` logging changed from dual-handler (stdout + file) to FileHandler-only to
avoid duplicate INFO lines. Validated: no duplicate lines in `automation.log`.

### 3. Reduce Groq 429 Frequency — Token Budget Optimization
**Problem:** Even at 2.5s inter-market delay (24 effective RPM), 429s occur when verbose LLM
responses push the TPM (tokens per minute) limit on the free tier. The RPM limit (30) is not the
binding constraint — TPM is.

**Options (pick one or combine):**
- **A. Trim `max_tokens`** — reduce from 512 → 256 in `_analyze_groq()`. The JSON response
  is ~100 tokens; 512 is wasted headroom.
- **B. Compress prompt** — the current prompt is ~350 tokens. Remove the example JSON output
  block (saves ~60 tokens) and shorten the rubric.
- **C. Multi-provider rotation** — instead of primary/failover, rotate Groq and Gemini
  round-robin every N markets to split the token load across both free tiers.

---

## 🟡 Planned — Next Sprint

### 4. Historical Backtesting (`backtest.py`)
For each resolved Polymarket market in `equity_signals`, compare:
- Signal's `impact_type` + `relevance_score` at `created_at`
- Actual stock price movement of `ticker` between `created_at` and market's `end_date`

Produces a prediction accuracy score per model and per category. This is the metric that
converts the tool from a signal generator into a validated alpha source.

**Implementation:** `backtest.py` queries resolved markets, fetches OHLCV via `yfinance`,
writes stats to a new `backtest_results` Supabase table.

### 5. GitHub Actions Cron
Replace the local `harvest.sh` cron with a hosted GitHub Actions workflow that runs every
4 hours. No machine needs to be running.

```yaml
on:
  schedule:
    - cron: '0 */4 * * *'
```

Secrets: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`,
`DISCORD_WEBHOOK_URL`.

### 6. Multi-Ticker Correlation
Some events affect multiple equities simultaneously (e.g., a Fed rate cut touches COIN,
MSTR, NVDA, PYPL). Add a `correlated_tickers JSONB` column to `equity_signals` and update
the prompt to return a list of impacted tickers with individual scores. The Analytics tab
chart becomes a correlation heatmap.

---

## 🟢 Backlog — Low Priority

### 7. Ingest Expansion
Current coverage: Business, Crypto, Tech. Consider adding:
- `Politics` — regulatory risk signals (SEC, CFTC rulings)
- `Science` — FDA approvals for biotech equities
- `Economics` — CPI, unemployment, Fed statements

### 7. Email Alerts
`notifications.py` has placeholder email logic guarded by a `"your-email@example.com"`
check. Wire up `SMTP_HOST`, `SMTP_USER`, `SMTP_PASS` in `.env`. Alert threshold (score ≥ 8)
is already correct.

### 8. 30-Day Price History Purge
`market_prices` currently holds one snapshot per market (133 rows). Add a `cleanup.py`
that deletes rows older than 30 days and runs as part of the cron/GHA workflow.
