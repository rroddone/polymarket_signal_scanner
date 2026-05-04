# Development Log — Polymarket Signal Scanner

Chronological record of significant fixes, architectural decisions, and open problems.

---

## Session 4 — 2026-04-29
**Theme: Automation, Analytics, and Pipeline Stability**

### Fix 1: Nuke Button — Bigint vs UUID Mismatch
**Problem:** The "☢️ Nuke & Reset" button in the dashboard used `.neq("id", "00000000-...")`,
a UUID sentinel, but `equity_signals.id` is a `BIGINT`. Supabase rejected the filter with a
type error and nothing was deleted.

**Fix:** Changed sentinel to `.neq("id", -1)`. A bigint PK will never be negative, so this
matches every row safely.

**File:** `app.py`

---

### Fix 2: Bulletproof JSON Parser — `first_{` to `last_}` Slicer
**Problem:** Groq occasionally wraps its JSON output in prose or markdown fences
(`\`\`\`json ... \`\`\``). The original `json.loads(text)` call raised `JSONDecodeError`
on any decorated response, counting the market as a parse failure.

**Fix:** `parse_llm_response()` now:
1. Strips ` ```json ` / ` ``` ` fences.
2. Finds the first `{` and the last `}` in the cleaned text and attempts `json.loads` on
   that slice — tolerates any prose before or after the JSON object.
3. Falls back to scanning for the innermost self-contained `{…}` fragment with
   `re.finditer(r"\{[^{}]+\}", cleaned)`.

This handles models that "yap" around the JSON and models that nest commentary inside the
response without breaking the outermost object.

**File:** `analyze.py` — `parse_llm_response()`

---

### Fix 3: Lean Context — Sector Brain Anti-Drift
**Problem:** On re-runs after a partial harvest, `analyze.py` would sometimes re-score
markets it had previously seen at a different relevance — signal quality drifted between
sessions with no shared context.

**Fix:** `_format_recent_context()` fetches the 5 most recent `equity_signals` rows and
formats them as a compact one-liner: `"Recent signals: $MSTR: Bullish (9), $COIN: Bearish (6), …"`.
This line is injected into every prompt so the model has a calibration anchor when
choosing tickers and scores within the same session.

**File:** `analyze.py` — `_format_recent_context()`, `build_prompt()`

---

### Fix 4: Cron Automation + Sidebar Control Center
**Problem:** The pipeline required manual execution. No way to schedule or monitor it from
the dashboard.

**Fix:**
- `harvest.sh` — bash entry point: manages `harvest.lock` with `trap EXIT`, activates venv,
  runs `ingest.py` then `analyze.py` sequentially. Designed for `crontab` (`0 */4 * * *`).
- `cron_utils.py` — pure-Python crontab interface: `get_current_schedule()`,
  `update_schedule(h, m, active)`, `make_cron_expression()`, `parse_cron_to_hm()`,
  `is_processing()`, `clear_lock()`.
- `app.py` sidebar "🤖 Autonomous Agent Control" section: `st.toggle` with on_change
  callback, two-column Hours/Minutes `st.selectbox` components, live schedule status
  caption, Agent Pulse log tail, conditional "🔓 Clear Lock & Reset" button.

**Files:** `harvest.sh` (new), `cron_utils.py` (new), `app.py`

---

### Fix 5: GracefulExit — Preventing the 429 Death Spiral
**Problem:** On a Groq 429, `analyze_market()` previously fell over to Gemini. But Gemini's
free-tier daily RPD quota was already exhausted. The fallover caused a cascade of Gemini
429s → exponential backoff retries → script running for hours making no progress.

**Fix:** On `groq_lib.RateLimitError` or `groq_lib.APIConnectionError`, `analyze_market()`
now raises `GracefulExit` instead of returning a fallback result. The main loop catches it,
logs the partial counts, and calls `sys.exit(0)`. The next cron cycle resumes from the
first unanalyzed market (the DB exclusion query is idempotent). Gemini remains the fallback
only for non-rate-limit Groq errors (connection timeouts, etc.).

**File:** `analyze.py` — `analyze_market()`, `run_analysis()`, `GracefulExit` class

---

### Fix 6: Analytics Dashboard — Two-Tab Layout
**Problem:** The dashboard had no aggregate view of signal quality, sector coverage, or
bull/bear balance.

**Fix:** Added a `📊 Market Analytics` tab alongside the existing `🔬 Intelligence Feed`:
- Average relevance score by ticker (horizontal bar chart)
- Signal volume by sector/category (stacked bar)
- Score distribution histogram (1–10 buckets)
- Top-5 highest-scored signals (table)
- Bull/Bear/Neutral percentage summary

`compute_analytics(df)` pre-computes all DataFrames and is decorated `@st.cache_data(ttl=60)`
so repeated reruns within the same minute do not re-query Supabase.

**File:** `app.py` — `compute_analytics()`, `_tab_analytics`

---

### Fix 7: Direct Terminal Logging — Diagnosing Silent Failures
**Problem:** `harvest.sh` redirected all output to `automation.log` with `>> log 2>&1`.
When `analyze.py` failed during import (e.g., missing venv activation), the error was
swallowed and the log stayed empty. Root-cause debugging was impossible.

**Fix (current / temporary):**
- Removed all `>> automation.log 2>&1` redirections from `harvest.sh` — output now goes
  directly to the terminal.
- `analyze.py` wraps all third-party imports in `try/except ImportError` that prints
  `IMPORT ERROR: <reason>` with `flush=True` before `sys.exit(1)`.
- Added `print("Pre-flight: Connecting to Supabase...", flush=True)` as the very first line
  in `__main__` — if this doesn't appear, the failure is at import time.
- Added pidfile check (`/tmp/polymarket_analyze.pid`) with `os.kill(pid, 0)` liveness test
  to detect and report duplicate instances.
- `logging.basicConfig` changed to dual-handler setup: `StreamHandler(sys.stdout)` +
  `FileHandler(automation.log, mode="a")` with `force=True`.
- `_flush_logs()` (calls `sys.stdout.flush()` + `logging.shutdown()`) called before all
  `sys.exit()` paths to prevent buffered output from being lost.

**Files:** `harvest.sh`, `analyze.py`

---

## Fix 8: Header-Aware 429 Retry — Groq Rate-Limit Root Cause Confirmed

**Status: Resolved (2026-04-29 Operator Mode)**

**Root cause confirmed via `Retry-After` header:**
Groq's free tier for `llama-3.3-70b-versatile` uses a **~713-second (~12-minute) rate-limit
window** — not a 1-minute RPM window as initially assumed. The 429 fires consistently after
~22 requests regardless of inter-request delay because the window is token-bucket based over
a 12-minute horizon (not per-minute).

**Observed data points:**
- 429 fires at market 23 of ~200 across all test runs
- `Retry-After` header value: 713 s (confirmed directly from Groq HTTP response)
- Prior 65 s wait was 10x too short; persistent 429s after 3 × 65 s confirmed

**Fix: `_groq_429_wait()` + `_parse_reset_duration()`**

Two new helpers in `analyze.py`:
- `_groq_429_wait(error, attempt)` — reads `Retry-After`, `x-ratelimit-reset-requests`,
  and `x-ratelimit-reset-tokens` from the 429 response headers; adds a 10 s safety buffer.
- `_parse_reset_duration(s)` — parses Groq's duration strings (`"1m30.123s"`, `"65.4s"`,
  `"500ms"`) into integer seconds.
- Falls back to exponential [90 s, 180 s, 360 s] if headers are absent.
- `MAX_429_RETRIES = 3` — allows 3 wait-and-retry cycles per market before GracefulExit.

**Throughput math (with retries):**
- ~22 markets per 713 s window; 4 windows per session (3 retries + initial) → **~88 markets/cycle**
- 195 markets / 88 per cycle ≈ **3 cron cycles = 12 hours** for full harvest
- `RATE_LIMIT_DELAY_GROQ = 3.0 s` unchanged — increasing it would only reduce throughput

**File:** `analyze.py` — `_groq_429_wait()`, `_parse_reset_duration()`, `analyze_market()`

---

## Fix 9: Dashboard Safety Layer — Lock-Aware Kill Switch + Color-Coded Log Monitor

**Status: Resolved (2026-04-29 Operator Mode)**

**Problem:**
The dashboard had no way to stop or observe a harvest that was started externally (via cron
or a terminal `bash harvest.sh`). If a cron run was in a 713 s rate-limit hibernate, the
dashboard showed no status and offered no way to cancel it.

**Fix: Three-state harvest UI in sidebar**

`app.py` now determines which button set to show based on two orthogonal signals:
- `harvest_running` — a subprocess spawned directly by this dashboard session
- `_bg_running = is_processing()` — `harvest.lock` exists, indicating an external process

| State | Buttons shown |
|---|---|
| `harvest_running` | 🛑 Stop Analysis (SIGTERM → SIGKILL on in-process PID) |
| `_bg_running` only | ⚠️ "Harvest in progress (Rate Limit Aware)" label + 🛑 Cancel/Kill Harvest button |
| Neither | 🚀 Start Full Harvest (enabled) |

**`_kill_harvest()` implementation:**
Uses `pgrep -f "harvest.sh"` and `pgrep -f "analyze.py"` to find PIDs regardless of how the
harvest was started. Sends `SIGTERM` to all matches, waits 1.5 s, sends `SIGKILL` to any
survivors. Always calls `clear_lock()` at the end — guarantees the UI returns to idle state
even if both processes were already dead.

The function skips `os.getpid()` (the Streamlit server itself) to prevent self-termination.

**Color-coded log viewer — `_render_log_html()`:**
Reads the last 20 lines of `automation.log` and applies per-line HTML color coding:

| Pattern | Color |
|---|---|
| `Waiting \d+s` / `Hibernate` / `rate.limit` | Amber |
| `429` | Red |
| `Saved` / `Complete` / `signals saved` | Green |
| `Warning` / `Error` / `Failed` | Orange |
| `Session Start` / `===` | Indigo |
| All other lines | Gray |

Rendered inside a fixed-height scrollable `<div>` with a monospace font.

**Harvest Activity Monitor (main body):**
When `_bg_running` and no in-process harvest is active, a monitor block appears above the
metrics row. It scans the last 20 log lines in reverse for a hibernate pattern
(`r"Waiting \d+s.*rate.limit"`) and shows either:
- 💤 **Hibernating** — extracts the wait time and displays it
- 🔄 **Harvest Active** — normal processing

Includes a "🔄 Refresh" button and the full color-coded log panel.

**Agent Pulse enhancement:**
Agent Pulse now shows 8 log lines (was 3) when `_bg_running`, with hibernate detection
showing "💤 Hibernating" as the status caption instead of the generic timestamp.

**Files:** `app.py` — `_render_log_html()`, `_kill_harvest()`, sidebar harvest section,
Harvest Activity Monitor block

---

## Session 5 — 2026-04-30
**Theme: LLM Model Swap, Live Monitor, and Process Control Hardening**

### Fix 10: Provider Pivot — Groq llama-3.1-8b-instant as Primary
**Problem:** Gemini 2.0 Flash was hitting 429s immediately on the 199-market backlog (per-minute
window exhausted after each test run). The previous Groq primary model (`llama-3.3-70b-versatile`,
6 RPM) had a 713-second rate-limit window that made the full harvest take 12+ hours.

**Decision:** Switch primary to `llama-3.1-8b-instant` on Groq.

**Rationale:**
- 30 RPM free-tier limit — 5× the throughput of the 70b model
- Per-minute window (not the 12-minute bucket of the 70b model)
- With `RATE_LIMIT_DELAY_GROQ = 2.5s` → 24 effective RPM → full backlog in **~8 minutes** on fresh quota
- Gemini 2.0 Flash demoted to failover if Groq exhausts 3 retries

**Caveat found mid-session:** `llama-3-8b-8192` was selected first but returned HTTP 404 — model
has been decommissioned by Groq. Immediately pivoted to `llama-3.1-8b-instant` which is the
current equivalent.

**Files:** `config.py` — `GROQ_MODEL`, `PRIMARY_LLM`, `RATE_LIMIT_DELAY_GROQ`

---

### Fix 11: Dynamic LLM Label in Dashboard
**Problem:** Sidebar showed "Primary: **Groq**" as a hardcoded string even when `PRIMARY_LLM=GEMINI`
in config. Every config change required a manual string edit in `app.py`.

**Fix:**
- `PRIMARY_LLM` imported into `app.py`
- `_PRIMARY_NAME` / `_SECONDARY_NAME` computed at module level from `PRIMARY_LLM`
- All sidebar labels, harvest warning text, and spinner text reference these constants

**File:** `app.py`

---

### Fix 12: Lock-Backed Cancel Button
**Problem:** The "Start Full Harvest" UI button launched `analyze.py` directly without creating
`harvest.lock`. On a browser refresh the session state was lost and neither "Cancel" nor "Stop"
appeared — the user had no way to stop the running process.

**Fix:** `harvest.lock` is `touch()`ed immediately before `subprocess.Popen`, and `clear_lock()`
is called after `proc.wait()` regardless of exit code. The Cancel button's visibility is now
purely lock-file based — survives any refresh or new tab.

**File:** `app.py` — harvest runner block

---

### Fix 13: Streamlit Fragment Live Monitor — `@st.fragment(run_every=2)`
**Problem:** The previous live monitor used a `while is_processing(): ... time.sleep(2)` loop.
This blocked the Streamlit server thread, graying out the entire page between updates and making
the UI unresponsive to any user interaction.

**Root cause of blank progress bar:** `read_text()` without `errors='ignore'` raised a silent
`UnicodeDecodeError` when `automation.log` contained a partial UTF-8 write from Groq mid-response.
The fragment caught the exception internally and rendered nothing.

**Fix:** Three-layer replacement:
1. `@st.fragment(run_every=2)` — fragment runs on its own 2-second timer, independent of the
   main script; the main page remains fully interactive.
2. `read_text(encoding="utf-8", errors="ignore")` inside a `try/except` — any read error is
   surfaced as a visible `st.warning` instead of a blank fragment.
3. Broad `[X/Y]` progress regex — any log line containing `[N/M]` advances the progress bar,
   not just lines matching the exact `Analyzing` format.

Additional hardening:
- `⏱ Last refreshed` timestamp as the first widget — proves the fragment is firing
- Empty-log early-return with `🔄 Initializing Scanner…` placeholder
- Emergency dump: if no pattern matches, last 5 raw lines shown via `st.caption`
- `st.empty()` placeholders for progress bar and log tail — in-place DOM updates

**File:** `app.py` — `_live_harvest_monitor()`

---

### Fix 14: Unified Harvest State — Persistent Monitor + PID-Based Termination
**Problem (Split Personality):** The harvest monitor appeared as one section of the page, but
the metrics row, signal table, and analytics tabs remained visible below it. Users could scroll
past the monitor to see stale data. The "Refresh Market Data" button would rerun the page and
bypass the monitor entirely.

**Fix — four changes:**

1. **`st.stop()` after monitor** — when `harvest.lock` exists, the monitor renders and
   `st.stop()` prevents anything below it from rendering. The user cannot "escape" to the
   dashboard until the harvest finishes or is terminated.

2. **Terminate button inside fragment** — reads PID from `/tmp/polymarket_analyze.pid`
   (the file `analyze.py` writes itself at startup) and calls `os.kill(pid, signal.SIGTERM)`.
   More precise than `pgrep` pattern matching. Follows with `clear_lock()` and
   `st.rerun(scope="app")` for a full page reload to idle state.

3. **Disabled Refresh button** — `_bg_running` hoisted before `with st.sidebar:` so the
   "🔄 Refresh Market Data" button can reference it. Button is disabled (`disabled=_bg_running`)
   with a tooltip explaining why.

4. **`_bg_running` hoisted** — `_bg_running = is_processing()` moved before the sidebar block
   so it is available to both sidebar widgets and main-body logic without any scoping ambiguity.

**File:** `app.py`

---

### Fix 15: Log Auto-Trim + Pathlib in analyze.py
**Problem:** `automation.log` grew without bound. After a few production cycles it could exceed
1 MB, making `read_text()` in the fragment slow enough to visibly lag the 2-second refresh.

**Fix:** At the start of `run_analysis()`, before any logging begins, the log file is trimmed to
the last 500 lines if it exceeds 1 MB. This is done at process start (single writer, no race
condition) using `pathlib.Path`.

`from pathlib import Path` added to imports.

**File:** `analyze.py` — `run_analysis()`
