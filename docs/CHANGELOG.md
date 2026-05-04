# Changelog

All notable changes to the Polymarket Signal Scanner are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

---

## [0.5.0] — 2026-04-30 · Backtesting & Automation Layer

### Added

#### Intraday Backtesting (`backtest.py`)
- New script that validates LLM signal accuracy against real equity price data
- Fetches 5-min yfinance bars (5-day window) for all tickers in `equity_signals`
- Maps each signal's `created_at` timestamp to the nearest 5-min bar (entry price)
- Compares against the most recent available bar (current price)
- Verdict logic: `Bullish → HIT if current > entry`, `Bearish → HIT if current < entry`
- Three output sections: signal detail table, per-ticker summary, aggregate stats
- High Conviction filter: win-rate breakdown for `relevance_score ≥ 8` signals
- Pre-market detection: fires if `last_bar.date() < date.today()` — warns and advises re-run
- Saves `latest_results.json` after every run (schema stable, readable by `discord_pusher.py`)
- `--limit N` flag for smoke-testing without processing all signals

#### Discord Result Pusher (`discord_pusher.py`)
- Reads `latest_results.json` and posts a rich Discord embed
- Colour-coded: green (≥50% win rate), red (<50%), amber (pre-market data)
- Fields: overall/bullish/bearish win rates, High Conviction rate, Top 3 by % change
- `--file PATH` flag for dry-running against test data without affecting production
- Guards against unconfigured webhook (placeholder check → silent skip, no crash)

#### Time Travel Smoke Test (`test_backtest_logic.py`)
- Fetches real 5-min bars for GOOGL, MSTR, NVDA
- Injects 6 synthetic signals at 09:35 AM ET (entry) → 11:00 AM ET (exit)
- Self-calibrating: expected verdicts derived from actual price direction — never hardcoded
- Named test cases: TC-01…TC-06 with explicit PASS/FAIL audit trail
- Prints a step-by-step win-rate calculation ("show your work") for full auditability
- Saves `test_results.json` (same schema as `latest_results.json`) for Discord dry-runs
- CI-gate: exits non-zero if any test case fails

**First intraday observation (2026-04-30, 09:35→11:00 ET window):**
| Ticker | Move | Bearish | Bullish |
|---|---|---|---|
| GOOGL | +0.93% | MISS ✓ | HIT ✓ |
| MSTR | +2.37% | MISS ✓ | HIT ✓ |
| NVDA | −2.83% | **HIT** ✓ | MISS ✓ |

All 6 test cases passed. NVDA provided the first confirmed live Bearish HIT.

#### Automated 9:45 AM ET CCR Routine
- One-shot Anthropic cloud agent fires 15 min after NYSE open
- Queries `equity_signals` via Supabase MCP, fetches yfinance bars inline
- Saves backtest summary to `backtest_results` Supabase table
- Prints completion signal for local follow-up (`backtest.py` + `discord_pusher.py`)
- Prompt updated to include Supabase INSERT step; future runs use new prompt

#### Supabase `backtest_results` Table
- Stores automated backtest snapshots with full win-rate breakdown and top-3 JSON
- RLS enabled: service role full CRUD, anon SELECT

### Changed

#### `app.py` — Unified Harvest Monitor (v13 → v14)
- Replaced split streaming/fragment architecture with a single `@st.fragment(run_every=2)`
  that handles all harvest types (UI-triggered, Small Harvest, and cron/background)
- `_spawn_harvest()`: fire-and-forget subprocess + daemon thread clears `harvest.lock` on exit
- `st.stop()` exclusive monitor view: dashboard content hidden while harvest is active
- Fragment exit path: `st.success("🎉 Harvest Complete!")` → 2 s → `st.rerun(scope="app")`
- State reconciliation on every page load: if `is_processing()` is False, both
  `harvest_running` and `small_harvest_active` are reset regardless of session state
- Scrollable log: `_render_log_html()` (CSS `overflow-y:auto`) replaces `st.code`
- Pulsing "Initialising…" placeholder during subprocess startup delay
- Force Exit button: clears lock + `st.rerun(scope="app")` without SIGTERM
- Terminate button: SIGTERM via PID file + lock clear + app rerun

#### `app.py` — Audit Log Browser
- Sidebar `📜 View Audit Logs` toggle reveals a full-page log viewer
- Reads last 500 lines of `automation.log` with UTF-8 error-ignore
- Case-insensitive ticker filter, `st.container(height=500)` scrollable viewer
- Download button: exports the filtered view as a `.log` file

#### `app.py` — Small Harvest Button
- `🧪 Small Harvest (Test)` button runs `analyze.py --limit 5`
- Session state `small_harvest_active` tracks test harvests separately from full runs

#### `analyze.py` — `impact_type` Normalisation (v8 → v9)
- LLM output normalised on extraction: any string containing "bullish" → `"Bullish"`,
  "bearish" → `"Bearish"`, anything else → `"Neutral"`
- Prevents non-standard values (e.g. `"Strong Correlated Sector Shift"`) entering the DB

### Fixed

- **One-time DB cleanup:** 27 legacy `equity_signals` rows with non-standard `impact_type`
  values corrected via SQL UPDATE (ILIKE matching on "bullish"/"bearish")
- **Pre-market detection:** backtest now uses `last_bar.date() < date.today()` instead of
  checking if all `|pct_change| < 0.001` — robust when mixed-date signal sets include older
  signals with real price movement
- **App stuck in monitor view:** state reconciliation block at page top ensures
  `harvest_running` can never remain `True` after `harvest.lock` is removed

---

## [0.4.0] — 2026-04-30 · Token Budget Optimisation (Groq 429 Elimination)

### Changed

#### `analyze.py` — Compact Prompt (v7 → v8)
- `build_prompt()` condensed: ~380 tokens → ~180 tokens (rubric kept, verbose prose removed)
- Groq `max_tokens`: 512 → 200 (JSON response is ~80 tokens; 200 gives 2.5× headroom)
- Gemini `max_output_tokens`: 300 added (caps failover response verbosity)
- TPM math: ~380 tok/call × 24 RPM ≈ 9,100 TPM — well under free-tier ceiling
- Comment documents TPM budget so future changes can recalculate before adjusting delays

### Fixed

- **Groq TPM exhaustion:** at 24 RPM, the previous 460-token-per-call budget exceeded the
  free-tier TPM ceiling and caused cascading 429s despite staying under RPM. Cutting tokens
  ~53% resolved this without reducing throughput.

---

## [0.3.0] — 2026-04-29 · Live Harvest Monitor + Dashboard Polish

### Added

#### `app.py` — Live Harvest Monitor
- `@st.fragment(run_every=2)` replaces the blocking `while` loop — page stays interactive
- Dynamic `[X/Y]` progress bar scanned from full log bottom-up (not just tail)
- Fragment exit: `st.rerun(scope="app")` auto-refreshes signal table when harvest completes

#### `app.py` — UX Improvements
- Dynamic LLM provider label in sidebar (reads from `config.PRIMARY_LLM` — never hardcoded)
- Refresh button disabled during harvest (with tooltip)
- PID-based Terminate button reads `/tmp/polymarket_analyze.pid`

### Changed

- `config.py` v4: `PRIMARY_LLM=GROQ`, `GROQ_MODEL=llama-3.1-8b-instant` (30 RPM, replaces
  deprecated `llama-3-8b-8192` which returned HTTP 404)
- `RATE_LIMIT_DELAY_GROQ`: 3.0 s → 2.5 s (yields 24 RPM effective, eliminates 60 s backoff)
- `automation.log` auto-trimmed to last 500 lines if > 1 MB

### Fixed

- `llama-3-8b-8192` HTTP 404: model decommissioned by Groq; migrated to `llama-3.1-8b-instant`
- Lock lifecycle for UI-triggered harvests: `harvest.lock` now touched before `Popen`;
  `clear_lock()` called after `proc.wait()` — Cancel button survives page refresh

---

## [0.2.0] — 2026-04-28 · Groq Primary + Gemini Failover Architecture

### Added

- `groq==1.2.0` library installed
- `_groq_429_wait()`: reads `Retry-After` header, waits exact reset window + 10 s buffer
- `_gemini_429_wait()`: reads `retryDelay` from Google error body; fallback: [30, 60, 120] s
- Header-aware retry loops for both providers (`MAX_429_RETRIES=3` each)
- `provider` column added to `equity_signals` — records which LLM generated each signal
- `--no-search` flag retained for backward compat (no-op — search grounding removed)

### Changed

- `config.py` v2→v3: `PRIMARY_LLM`, `GROQ_MODEL`, `GEMINI_MODEL` centralised
- `analyze.py`: Groq primary → Gemini failover architecture with adaptive throttling
  (2 s Groq → 15 s Gemini on failover)
- Throughput: ~199 markets × 2.5 s ≈ 8 min on Groq quota (vs. 17 min Gemini, 12 h Groq 70b)

---

## [0.1.0] — 2026-04-27 · Initial Release

### Added

- `ingest.py`: Polymarket Gamma API ingestion with volume filter (≥ $1k)
- `analyze.py`: Gemini 2.0 Flash primary analysis with Google Search grounding
- `notifications.py`: Discord webhook alerts (score ≥ 8 threshold, rich embeds)
- `app.py`: Streamlit dashboard — signal table, score distribution chart, bull/bear metrics
- `harvest.sh`: cron-safe automation entry point with lock file
- `cron_utils.py`: crontab r/w + lock state helpers
- Supabase schema: `markets`, `market_prices`, `equity_signals`, `watchlists` (RLS enabled)
- 23-ticker watchlist seeded: AI, Crypto, Mining, Fintech sectors
- Circuit breaker: 3 consecutive API failures → `sys.exit(1)`
- Idempotent market skip: already-analysed markets excluded upstream
