- [x] **Phase 1: Foundation**
    - [x] Create Documentation Ecosystem (.md files)
    - [x] Initialize Supabase Schema (via MCP)
    - [x] Set up Python Environment & .env template

- [x] **Phase 2: Data Ingestion**
    - [x] Build `ingest.py` (Polymarket Gamma API)
    - [x] Implement 30-day data cleanup script
    - [x] 132 markets ingested across Business, Crypto, Tech

- [x] **Phase 3: Intelligence & Filtering**
    - [x] Build `analyze.py` (Gemini 2.0 Flash + Google Search grounding)
    - [x] Implement Ticker Matching logic (Watchlist — 23 tickers)
    - [x] Circuit breaker (3 consecutive failures → sys.exit)
    - [x] Exponential backoff on 429 + correct `e.code` attribute
    - [x] AFC response parsing (`extract_text_from_response`)
    - [x] SAFETY/OTHER finish_reason handling (no false circuit trips)

- [x] **Phase 4: Notifications**
    - [x] Discord Webhook alerts (rich embeds, score ≥ 8 threshold)
    - [x] Rationale truncation guard (1000 chars, Discord 1024-char limit)
    - [x] End-to-end verified: HTTP 204 from Discord API
    - [x] Graceful skip if `DISCORD_WEBHOOK_URL` not configured

- [x] **Phase 5: Dashboard**
    - [x] Streamlit dashboard (`app.py`) with sidebar filters
    - [x] `st.metric` row (Total / High Relevance / Bullish / Bearish)
    - [x] Signal table with score progress bar + Polymarket link column
    - [x] Plotly stacked bar chart (signals by ticker, color by sentiment)
    - [x] Live harvest button with real-time log streaming (Popen)
    - [x] Kill-switch: SIGTERM → 2s grace → SIGKILL
    - [x] DB retry logic (3× backoff) + stale session_state fallback
    - [x] Last-updated heartbeat in sidebar (cached fetch timestamp)

- [x] **Phase 6: Database Polish & Security**
    - [x] Added `created_at TIMESTAMPTZ DEFAULT NOW()` to `markets` and `watchlists`
    - [x] RLS enabled on all 4 tables (8 policies: authenticated full CRUD, anon SELECT)
    - [x] `schema_export.sql` generated (canonical DDL for all 4 tables)
    - [x] `seed_data.sql` generated (23-ticker watchlist, idempotent)
    - [x] `security_policies.sql` generated (idempotent, applied to Supabase)

- [x] **Phase 7: Rate Limit Hardening (2026-04-28)**
    - [x] `RATE_LIMIT_DELAY` bumped 5s → 15s (inter-market throttle for Search Grounding)
    - [x] `BACKOFF_BASE` bumped 15s → 20s (retry start point)
    - [x] Backoff capped at 60s — confirmed schedule: 20s → 44s → 60s → 60s

- [x] **Phase 8: No-Search Mode & Adaptive Rate Limiting (2026-04-28)**
    - [x] `--no-search` CLI flag added to `analyze.py`
    - [x] `tools=[]` passed to Gemini when flag active — bypasses Search Grounding RPM cap
    - [x] Prompt updated: "Use your internal knowledge and historical data…" when offline
    - [x] `RATE_LIMIT_DELAY` split into two constants: `RATE_LIMIT_DELAY_SEARCH=15` / `RATE_LIMIT_DELAY_NO_SEARCH=5`
    - [x] `run_analysis()` picks delay dynamically — `--no-search` full run saves ~22 min on 132 markets
    - [x] Root cause confirmed: Gemini 429s fire at base API level (not search-specific); daily RPD quota exhausted

- [x] **Phase 9: Dashboard UI Observability & Polish (2026-04-28)**
    - [x] AI Status Indicator in sidebar: 🟢 System Active / 🟡 Rate Limited (Pacing Mode) / ⚪ Awaiting Harvest
    - [x] 429 detection: harvest log lines persisted to `session_state`; badge updates live after any run
    - [x] Metric row replaced: Total Signals / High Relevance / Active Markets (3-card layout)
    - [x] Signal table reordered — Market Question leads, Ticker/Sentiment/Relevance/Rationale follow
    - [x] Impact column color-coded: 🟢 Bullish (#16a34a) / 🔴 Bearish (#dc2626) via `pd.Styler.map()`
    - [x] Rationale column: `max_chars=160` truncation with native hover tooltip for full text
    - [x] `load_counts()` uses `count="exact"` PostgREST API — server-side count, no row data transferred
    - [x] `_get_db_client()` decorated `@st.cache_resource` — Supabase client created once per process
    - [x] `_IMPACT_HEX` / `_IMPACT_CSS` / `_IMPACT_MD_COLOR` consolidated at module level — single source of truth for all sentiment colours used in table, Plotly chart, and Top Signals

- [x] **Phase 10: Code Quality Pass — /simplify + /review (2026-04-28)**
    - [x] `POLYMARKET_BASE` moved to `config.py` — single source of truth across `analyze.py` + `app.py`
    - [x] Stale module docstring + inline changelog removed from `analyze.py`
    - [x] Task-doc references (`per INSTRUCTIONS.md`, `per PROJECT_RULES.md`) removed from comments
    - [x] Dead "Respect rate limits" comment removed; sleep uses `rate_limit_delay` variable directly
    - [x] All files syntax-verified: `config.py OK`, `analyze.py OK`, `app.py OK`

- [x] **Phase 11: Groq Primary LLM + Gemini Failover (2026-04-28)**
    - [x] Installed `groq==1.2.0` library
    - [x] `config.py` updated: `GROQ_MODEL`, `GEMINI_MODEL`, `PRIMARY_LLM="GROQ"` centralised
    - [x] `analyze.py` refactored: Groq primary, auto-failover to Gemini on 429 / connection error
    - [x] Adaptive throttling: 2s (Groq) → 15s (Gemini) on failover
    - [x] Prompt cleaned: search-grounding AFC instructions removed (Groq uses market context only)
    - [x] `provider` column added to `equity_signals` table via Supabase migration
    - [x] `save_signal()` persists `provider` field (e.g. `llama-3.3-70b-versatile`)
    - [x] `--no-search` flag retained for backward compat (no-op — search grounding removed for all providers)
    - [x] Test harvest `--limit 5` ✅ — 5/5 saved via Groq, 0 errors, 3 Discord alerts fired
    - [x] DB verified: all 5 rows have `provider=llama-3.3-70b-versatile`

- [x] **Phase 12: Gemini 2.0 Flash Primary + Groq Failover (2026-04-29)**
    - [x] `config.py`: `PRIMARY_LLM = "GEMINI"`, `GEMINI_MODEL = "gemini-2.0-flash"` (15 RPM free tier)
    - [x] `analyze.py` v8: `_gemini_429_wait()` — Retry-After header → Google retryDelay → fallback [30, 60, 120]s
    - [x] `_analyze_gemini()` propagates 429 upward (no longer swallows it)
    - [x] `analyze_market()` Gemini-primary path: 3-retry header-aware loop → Groq failover with its own header-aware retry
    - [x] `RATE_LIMIT_DELAY_GEMINI` 15s → 5s (12 RPM effective, safely under 15 RPM free tier)
    - [x] Groq-primary path preserved for `PRIMARY_LLM=GROQ` backward compat
    - [x] End-to-end validated: Gemini 429×4 → Groq HTTP 200 → correct `triggered_failover` handling
    - [x] Throughput: ~199 markets × 5s = ~17 min on fresh Gemini quota (vs 12h on Groq alone)

- [x] **Phase 13: Groq llama-3-8b-8192 Primary + UI/Lock Fixes (2026-04-29)**
    - [x] `config.py`: `PRIMARY_LLM = "GROQ"`, `GROQ_MODEL = "llama-3-8b-8192"` (30 RPM free tier vs 6 RPM for 70b)
    - [x] `app.py`: `PRIMARY_LLM` imported from config; `_PRIMARY_NAME`/`_SECONDARY_NAME` constants computed at module level
    - [x] Sidebar "Primary LLM" caption now reads dynamically from `_PRIMARY_NAME` — never hardcoded
    - [x] Cancel button fix: `harvest.lock` touched before `subprocess.Popen`; `clear_lock()` called after `proc.wait()` — Cancel survives page refresh
    - [x] All provider-label strings (warning, spinner) updated to use `_PRIMARY_NAME`/`_SECONDARY_NAME`
    - [x] Stale `harvest.lock` removed (`rm -f harvest.lock`)

- [x] **Phase 14: Live Harvest Monitor + Groq Throttle Fix (2026-04-30)**
    - [x] `@st.fragment(run_every=2)` replaces blocking while-loop — page stays interactive, no gray-out
    - [x] Fragment exit: `st.rerun(scope="app")` when lock disappears → signals table auto-refreshes
    - [x] `RATE_LIMIT_DELAY_GROQ`: 3.0s → 2.5s (24 RPM effective, eliminates 60-s 429 backoff penalties)
    - [x] Log auto-trim: `run_analysis()` truncates `automation.log` to last 500 lines if > 1 MB
    - [x] Progress bar: `[X/Y]` scanned from full log bottom-up (not just tail) for accuracy

- [x] **Phase 15: Token Budget Optimization — Groq 429 Elimination (2026-04-30)**
    - [x] `build_prompt()` condensed: ~380 tokens → ~180 tokens (removed verbose rubric prose, kept calibration)
    - [x] Groq `max_tokens`: 512 → 200 (JSON response is ~80 tokens; 200 gives 2.5× headroom)
    - [x] Gemini `max_output_tokens`: 300 added (prevents verbose failover responses from burning quota)
    - [x] TPM budget comment added to `RATE_LIMIT_DELAY_GROQ`: ~380 tokens/call × 24 RPM ≈ 9,100 TPM
    - [x] Dry run `--limit 3` validated: 3/3 saved, 0 parse errors, 2 Discord alerts fired

- [x] **Phase 16: Unified Monitor, Audit Log Browser & Backtest (2026-04-30)**
    - [x] Unified `@st.fragment` monitor handles all harvest types (UI-triggered + cron)
    - [x] `_spawn_harvest()`: fire-and-forget subprocess + daemon thread clears lock on exit
    - [x] State reconciliation at page top: `if not is_processing(): reset harvest_running + small_harvest_active`
    - [x] Small Harvest button: `analyze.py --limit 5` for testing without burning quota
    - [x] Force Exit button in fragment header: clears lock + `st.rerun(scope="app")`
    - [x] Fragment exit path: `st.success` → 2s sleep → `st.cache_data.clear()` → `st.rerun(scope="app")`
    - [x] Scrollable log: `_render_log_html()` (overflow-y:auto CSS) replaces `st.code`
    - [x] Audit Log Browser: sidebar toggle → last 500 lines, case-insensitive filter, download button
    - [x] `impact_type` normalization in `analyze.py` (maps non-standard LLM output to Bullish/Bearish/Neutral)
    - [x] One-time DB cleanup: SQL UPDATE fixed 27 rows with non-standard `impact_type` values
    - [x] `backtest.py` created: yfinance 5-min bars, HIT/MISS per signal, per-ticker & aggregate win rates
    - [x] Pre-market detection: compares last bar date to `date.today()` — shows warning + re-run advice
    - [x] Full run validated: 214 signals × 10 tickers, 10 yfinance calls, pre-market warning fires correctly

- [x] **Phase 19: Ticker-Aware Backtesting (2026-05-01)**
    - [x] `backtest_history` — `ticker TEXT NULLABLE` column added via Supabase migration
    - [x] `BacktestSummary` model — `ticker: str | None = None` field added (NULL = global aggregate)
    - [x] `DatabaseService.save_backtest_results()` — accepts `list[BacktestSummary]`, bulk-inserts in one call
    - [x] `Backtester._build_ticker_summary()` — computes per-ticker judged/hit/bull/bear/HC stats
    - [x] `Backtester._compute_aggregate()` — returns `list[BacktestSummary]` (N ticker rows + 1 aggregate)
    - [x] Neutral signals excluded from all win-rate math (ticker and aggregate rows)
    - [x] Validated: `--backtest --limit 10` → 4 ticker rows (AAPL, GOOGL, MSTR, SPCE) + 1 aggregate in Supabase

- [x] **Phase 22: Streamlit Cloud Deployment Prep (2026-05-06)**
    - [x] `requirements.txt` — created with 12 pinned direct deps (streamlit, supabase, pandas, plotly, yfinance, groq, google-genai, httpx, requests, python-dotenv, pydantic, pyarrow)
    - [x] `dashboard/app.py:649` — harvest subprocess command: `venv/bin/python` → `sys.executable` (Linux-compatible; works on any Python environment)
    - [x] `src/core/config.py` — added `_get_secret()` helper: `os.getenv` first (covers .env + Streamlit Cloud env injection), then `st.secrets` fallback
    - [x] `streamlit_app_secrets_template.toml` — created at project root; copy-paste into Streamlit Cloud console → Settings → Secrets

- [ ] **Ongoing: Production Run & Monitoring**
    - [ ] Execute full harvest: `venv/bin/python main.py --harvest`
    - [ ] Run backtest after 9:30 AM ET: `venv/bin/python main.py --backtest`
    - [ ] Verify crontab schedule via Automation panel in Alpha Terminal dashboard

- [x] **Phase 17: Lift & Shift Modular Refactor (2026-04-30)**
    - [x] `src/core/config.py` — PROJECT_ROOT-relative paths; all env vars centralised
    - [x] `src/core/models.py` — Pydantic models: MarketSignal, LLMAnalysisResult, BacktestSummary
    - [x] `src/providers/polymarket_client.py` — PolymarketClient class; Pydantic-validated output
    - [x] `src/providers/yfinance_client.py` — YFinanceClient class
    - [x] `src/providers/llm_factory.py` — LLMFactory; Groq primary + Gemini failover; all rate-limit logic preserved
    - [x] `src/utils/database.py` — DatabaseService; all Supabase ops + save_backtest_result()
    - [x] `src/utils/notifications.py` — NotificationService; signal alerts + backtest Discord push merged
    - [x] `src/utils/cron_utils.py` — paths from PROJECT_ROOT; no hardcoded absolute paths
    - [x] `src/utils/logger.py` — GracefulExit + setup_logger with auto-rotation
    - [x] `src/jobs/harvester.py` — Harvester; pidfile guard + ingest + analyze in one run()
    - [x] `src/jobs/backtester.py` — Backtester; saves to backtest_history table (not latest_results.json)
    - [x] `dashboard/app.py` — moved from root; imports from src.*; _spawn_harvest uses main.py
    - [x] `main.py` — CLI: --harvest [--limit N], --backtest [--limit N], --serve
    - [x] `harvest.sh` v3 — single `python main.py --harvest` call
    - [x] `backtest_history` table created in Supabase (RLS enabled); latest_results.json retired
    - [x] All root-level scripts removed; .md files moved to docs/; CLAUDE.md updated
    - [x] Import dry-run passed; `main.py --help` verified

- [x] **Phase 18: Standardize Project Structure (2026-05-01)**
    - [x] `logs/` — `automation.log`, `app.log` moved here
    - [x] `data/` — `latest_results.json`, `test_results.json` moved here
    - [x] `database/` — `schema_export.sql`, `security_policies.sql`, `seed_data.sql` moved here
    - [x] `tests/` — `test_backtest_logic.py` moved here; `OUT_FILE` → `data/test_results.json`; stale comments removed
    - [x] `src/core/config.py` — `LOGS_DIR`, `DATA_DIR` constants added; `LOG_FILE` → `logs/automation.log`
    - [x] `src/utils/logger.py` — `LOG_FILE.parent.mkdir(parents=True, exist_ok=True)` guard added
    - [x] `harvest.sh` — `LOG_FILE` repointed; `mkdir -p logs/` guard added
    - [x] Root contains only `main.py`, `harvest.sh`, `CLAUDE.md`, `README.md`
    - [x] No stale path references remain in any `.py` or `.sh` file

- [x] **Phase 19: Ticker-Aware Backtesting (2026-05-01)**
    - [x] `backtest_history` — `ticker TEXT NULLABLE` column added via Supabase migration
    - [x] `BacktestSummary` model — `ticker: str | None = None`; NULL = global aggregate row
    - [x] `DatabaseService.save_backtest_results()` — bulk-inserts `list[BacktestSummary]` in one call
    - [x] `Backtester._build_ticker_summary()` — per-ticker judged/hits/bull/bear/HC stats
    - [x] `Backtester._compute_aggregate()` — returns `list[BacktestSummary]` (N ticker + 1 aggregate)
    - [x] Neutral signals excluded from all win-rate math at both ticker and aggregate level
    - [x] Integration test validated: `--backtest --limit 10` → 4 ticker rows + 1 aggregate in Supabase

- [x] **Phase 21: GitHub Pre-Push Polish (2026-05-04)**
    - [x] `dashboard/app.py` — `st.dataframe` × 2 and `st.plotly_chart` × 1: `use_container_width=True` → `width="stretch"` (silences Streamlit 1.43+ deprecation warnings)
    - [x] `dashboard/app.py` — Sidebar "Agent pulse log snippet" (`st.code`) removed; debugging now via Audit Log tab and `logs/app.log`
    - [x] `README.md` — Rewritten with founder-style professional tone; How to Run section uses `python main.py` (no venv prefix); project tree updated to match `src/` modular layout
    - [x] `docs/SUMMARY.md` — Rewritten with strategic framing; architecture explained in three narrative layers; How to Run section corrected

- [x] **Phase 20: Alpha Terminal Dashboard + Final Polish (2026-05-01)**
    - [x] `dashboard/app.py` v2 — "Alpha Terminal" branding, institutional color palette (Emerald/Crimson/Slate)
    - [x] Top KPI row: Global Win Rate, HC Accuracy, Signals (24h), Top Performing Ticker
    - [x] Tab 1 "Signal Terminal" — inline keyword search, Conviction Score filter, color-coded Sentiment
    - [x] Tab 2 "Quant Audit" — Accuracy by Asset horizontal bar chart + Backtest Log table
    - [x] New loaders: `load_backtest_aggregate()`, `load_backtest_tickers()`, `load_backtest_log()`
    - [x] `load_counts()` extended with `signals_24h` (equity_signals in last 24h)
    - [x] Audit Log Browser: reversed to newest-first display; Download button removed
    - [x] `main.py --serve` — `KeyboardInterrupt` caught; confirmed exit code 0, no traceback
    - [x] `src/jobs/backtester.py` — unused `logging` import and `NotificationService` removed
    - [x] All imports verified used; syntax-checked clean
