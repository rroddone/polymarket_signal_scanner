"""
dashboard/app.py — Alpha Terminal: Polymarket Signal Scanner Dashboard.
Run with: venv/bin/python main.py --serve
      or: streamlit run dashboard/app.py
"""

import os
import re
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd
import plotly.express as px
import streamlit as st
from supabase import create_client

from src.core.config import (
    LOCK_FILE,
    LOG_FILE,
    POLYMARKET_BASE,
    PRIMARY_LLM,
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_URL,
)
try:
    from src.utils.cron_utils import (
        CRON_AVAILABLE,
        clear_lock,
        get_current_schedule,
        is_processing,
        update_schedule,
    )
except Exception:
    CRON_AVAILABLE = False
    def is_processing() -> bool: return False          # type: ignore[misc]
    def clear_lock() -> None: pass                     # type: ignore[misc]
    def get_current_schedule() -> dict: return {"active": False, "hours": 4, "minutes": 0}  # type: ignore[misc]
    def update_schedule(*_a: object, **_kw: object) -> None: pass  # type: ignore[misc]

PROJECT_ROOT = _PROJECT_ROOT

# ---------------------------------------------------------------------------
# Institutional color palette
# ---------------------------------------------------------------------------
_EMERALD = "#10b981"
_CRIMSON = "#dc2626"
_SLATE   = "#64748b"
_INDIGO  = "#6366f1"

_IMPACT_HEX: dict[str, str] = {
    "Bullish": _EMERALD,
    "Bearish": _CRIMSON,
    "Neutral": _SLATE,
}
_IMPACT_CSS: dict[str, str] = {
    "Bullish": f"color: {_EMERALD}; font-weight: 600",
    "Bearish": f"color: {_CRIMSON}; font-weight: 600",
    "Neutral": f"color: {_SLATE}",
}
_IMPACT_MD_COLOR: dict[str, str] = {"Bullish": "green", "Bearish": "red", "Neutral": "gray"}

_PRIMARY_NAME   = "Groq"   if PRIMARY_LLM == "GROQ" else "Gemini"
_SECONDARY_NAME = "Gemini" if PRIMARY_LLM == "GROQ" else "Groq"

_LOG_PANEL_STYLE = (
    "max-height:320px;overflow-y:auto;background:#0f172a;"
    "border:1px solid #1e293b;border-radius:6px;"
    "padding:10px 12px;font-family:'Courier New',monospace;"
    "font-size:12px;line-height:1.65"
)

_DB_RETRIES     = 3
_DB_RETRY_DELAY = 0.5


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Alpha Terminal · Polymarket Signal Scanner",
    page_icon="⚡",
    layout="wide",
)

if "harvest_pid" not in st.session_state:
    st.session_state.harvest_pid = None
if "harvest_running" not in st.session_state:
    st.session_state.harvest_running = False
if "small_harvest_active" not in st.session_state:
    st.session_state["small_harvest_active"] = False

if not is_processing():
    st.session_state.harvest_running = False
    st.session_state["small_harvest_active"] = False


# ---------------------------------------------------------------------------
# Database client
# ---------------------------------------------------------------------------
@st.cache_resource
def _get_db_client():
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------
@st.cache_data(ttl=10)
def load_signals() -> tuple[pd.DataFrame, str]:
    last_exc: Exception | None = None
    for attempt in range(_DB_RETRIES):
        try:
            db = _get_db_client()
            result = db.table("equity_signals").select(
                "id, market_id, ticker, relevance_score, impact_type, rationale, created_at,"
                " markets(question, category, slug)"
            ).order("created_at", desc=True).limit(1000).execute()

            fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            if not result.data:
                return pd.DataFrame(), fetched_at

            rows = []
            for row in result.data:
                m    = row.get("markets") or {}
                slug = m.get("slug") or ""
                rows.append({
                    "Ticker":       row["ticker"],
                    "Score":        int(row["relevance_score"]),
                    "Impact":       row.get("impact_type") or "Neutral",
                    "Question":     m.get("question") or "—",
                    "Category":     m.get("category") or "—",
                    "Rationale":    row.get("rationale") or "—",
                    "Link":         f"{POLYMARKET_BASE}/{slug}" if slug else "",
                    "Created":      row["created_at"],
                    "_created_raw": row["created_at"],
                })

            df = pd.DataFrame(rows)
            df["Created"] = pd.to_datetime(df["Created"]).dt.strftime("%Y-%m-%d %H:%M UTC")
            return df, fetched_at

        except Exception as exc:
            last_exc = exc
            if attempt < _DB_RETRIES - 1:
                time.sleep(_DB_RETRY_DELAY * (2 ** attempt))
    raise last_exc  # type: ignore[misc]


@st.cache_data(ttl=10)
def load_counts() -> dict[str, int]:
    last_exc: Exception | None = None
    for attempt in range(_DB_RETRIES):
        try:
            db     = _get_db_client()
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            m      = db.table("markets").select("id", count="exact").execute()
            am     = db.table("markets").select("id", count="exact").eq("active", True).execute()
            w      = db.table("watchlists").select("ticker", count="exact").execute()
            s24    = db.table("equity_signals").select("id", count="exact").gte("created_at", cutoff).execute()
            return {
                "markets":       m.count  or 0,
                "active_markets": am.count or 0,
                "watchlist":     w.count  or 0,
                "signals_24h":   s24.count or 0,
            }
        except Exception as exc:
            last_exc = exc
            if attempt < _DB_RETRIES - 1:
                time.sleep(_DB_RETRY_DELAY * (2 ** attempt))
    raise last_exc  # type: ignore[misc]


@st.cache_data(ttl=60)
def load_backtest_aggregate() -> dict:
    """Latest global aggregate row (ticker IS NULL) — source for KPI cards."""
    try:
        db     = _get_db_client()
        result = (
            db.table("backtest_history")
            .select("overall_win_rate_pct, hc_win_rate_pct, hc_count, hc_hits, total_signals, judged, top3_by_pct, generated_at")
            .is_("ticker", "null")
            .order("generated_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else {}
    except Exception:
        return {}


@st.cache_data(ttl=60)
def load_backtest_tickers() -> pd.DataFrame:
    """Per-ticker rows from the most recent backtest run (ticker IS NOT NULL)."""
    try:
        db  = _get_db_client()
        agg = (
            db.table("backtest_history")
            .select("generated_at")
            .is_("ticker", "null")
            .order("generated_at", desc=True)
            .limit(1)
            .execute()
        )
        if not agg.data:
            return pd.DataFrame()
        latest_ts = agg.data[0]["generated_at"]
        result = (
            db.table("backtest_history")
            .select("ticker, total_signals, judged, overall_win_rate_pct, bullish_win_rate_pct, bearish_win_rate_pct, hc_win_rate_pct, avg_score")
            .not_.is_("ticker", "null")
            .eq("generated_at", latest_ts)
            .execute()
        )
        return pd.DataFrame(result.data) if result.data else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60)
def load_backtest_log() -> pd.DataFrame:
    """Most recent 15 per-ticker backtest rows across all runs."""
    try:
        db     = _get_db_client()
        result = (
            db.table("backtest_history")
            .select("ticker, total_signals, judged, overall_win_rate_pct, hc_win_rate_pct, avg_score, last_bar_date, generated_at")
            .not_.is_("ticker", "null")
            .order("generated_at", desc=True)
            .limit(15)
            .execute()
        )
        return pd.DataFrame(result.data) if result.data else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_ai_status(df: pd.DataFrame) -> str:
    if st.session_state.get("harvest_running"):
        return "🔵 Analyzing…"
    last_logs = st.session_state.get("_last_harvest_logs", [])
    if any("Rate limited" in line or "429" in line for line in last_logs):
        return "🟡 Rate Limited (Pacing Mode)"
    if not df.empty and "_created_raw" in df.columns:
        try:
            latest = pd.to_datetime(df["_created_raw"], utc=True).max()
            if (datetime.now(timezone.utc) - latest).total_seconds() < 3600:
                return "🟢 System Ready"
        except Exception:
            pass
    return "⚪ Awaiting Harvest"


def _render_log_html(lines: list[str]) -> str:
    if not lines:
        return (
            f'<div style="{_LOG_PANEL_STYLE}">'
            '<span style="color:#6b7280">No log output yet.</span></div>'
        )
    rows = []
    for ln in lines:
        if re.search(r"Waiting \d+s.*rate.limit|Retry-After", ln, re.IGNORECASE):
            color = "#f59e0b"
        elif "429" in ln or "Rate limit" in ln:
            color = "#ef4444"
        elif "→ Saved:" in ln or "Analysis Complete" in ln or "Session Complete" in ln:
            color = "#22c55e"
        elif "WARNING" in ln or "ERROR" in ln:
            color = "#f97316"
        elif "Session Start" in ln:
            color = "#818cf8"
        else:
            color = "#9ca3af"
        safe = ln.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        rows.append(f'<div style="padding:2px 0;color:{color}">{safe}</div>')
    return f'<div style="{_LOG_PANEL_STYLE}">{"".join(rows)}</div>'


# ---------------------------------------------------------------------------
# Harvest process management
# ---------------------------------------------------------------------------
def _spawn_harvest(cmd: list[str]) -> int:
    LOCK_FILE.touch()
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=str(PROJECT_ROOT),
    )

    def _clear_lock_on_exit() -> None:
        proc.wait()
        LOCK_FILE.unlink(missing_ok=True)

    threading.Thread(target=_clear_lock_on_exit, daemon=True).start()
    return proc.pid


# ---------------------------------------------------------------------------
# Live Harvest Monitor fragment
# ---------------------------------------------------------------------------
@st.fragment(run_every=2)
def _live_harvest_monitor() -> None:
    _all_lines: list[str] = []
    _read_error: str | None = None

    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > 0:
            _raw = LOG_FILE.read_text(encoding="utf-8", errors="ignore")
            _all_lines = [ln for ln in _raw.splitlines() if ln.strip()]
    except Exception as _exc:
        _read_error = str(_exc)

    _tail = _all_lines[-15:]

    _hdr_col, _exit_col, _btn_col = st.columns([3, 1, 1])
    with _hdr_col:
        st.caption(f"⏱ Last refreshed: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
    with _exit_col:
        if st.button(
            "🔓 Force Exit",
            use_container_width=True,
            key="force_exit_btn",
            help="Clears the lock file; does not kill the process.",
        ):
            clear_lock()
            st.cache_data.clear()
            st.rerun(scope="app")
    with _btn_col:
        if st.button(
            "🛑 Terminate",
            type="primary",
            use_container_width=True,
            key="terminate_harvest_btn",
            help="Sends SIGTERM to the harvest process, then clears the lock.",
        ):
            _pid_file = Path("/tmp/polymarket_analyze.pid")
            try:
                if _pid_file.exists():
                    _pid = int(_pid_file.read_text().strip())
                    os.kill(_pid, signal.SIGTERM)
            except (ValueError, ProcessLookupError, OSError):
                pass
            clear_lock()
            st.cache_data.clear()
            st.rerun(scope="app")

    if not _all_lines:
        st.markdown(
            "<style>@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}</style>"
            '<div style="animation:pulse 1.8s ease-in-out infinite;padding:12px 16px;'
            "background:#1e3a5f;border:1px solid #2563eb;border-radius:8px;"
            'color:#93c5fd;font-size:14px">'
            "⏳ Initializing API connection and loading markets…"
            "</div>",
            unsafe_allow_html=True,
        )
        if _read_error:
            st.warning(f"Log read error: `{_read_error}`")
        st.progress(0.0, text="Waiting for first market…")
        if not is_processing():
            st.success("🎉 Harvest Complete! Redirecting…")
            time.sleep(2)
            st.cache_data.clear()
            st.rerun(scope="app")
        return

    _prog_i, _prog_total = 0, 0
    for ln in reversed(_all_lines):
        _pm = re.search(r"\[(\d+)/(\d+)\]", ln)
        if _pm:
            _prog_i, _prog_total = int(_pm.group(1)), int(_pm.group(2))
            break

    _status_resolved = False
    _last_action     = ""
    for ln in reversed(_tail):
        _mc = re.search(r"Analysis Complete: (\d+) saved, (\d+) skipped", ln)
        if _mc:
            _last_action     = f"Done — {_mc.group(1)} saved, {_mc.group(2)} skipped"
            _status_resolved = True
            break
        _ms = re.search(r"→ Saved: (\w+) \| (\w+) \| score=(\d+)", ln)
        if _ms:
            _last_action     = f"Saved → {_ms.group(1)} · {_ms.group(2)} · score {_ms.group(3)}/10"
            _status_resolved = True
            break
        _pm2 = re.search(r"\[(\d+)/(\d+)\]\s*(.{8,})", ln)
        if _pm2:
            q = _pm2.group(3).strip()
            _last_action     = ("Scanning: " + q[:72] + "…") if len(q) > 72 else ("Scanning: " + q)
            _status_resolved = True
            break

    _is_hibernating = False
    _hibernate_wait = ""
    for ln in reversed(_tail[-5:]):
        if re.search(r"Waiting \d+s.*rate.limit", ln, re.IGNORECASE):
            _is_hibernating = True
            _mw = re.search(r"Waiting (\d+)s", ln)
            if _mw:
                _hibernate_wait = _mw.group(1)
            _status_resolved = True
            break
        if re.search(r"→ Saved:|Analysis Complete|\[\d+/\d+\]", ln):
            break

    if _is_hibernating:
        st.warning(f"💤 **Hibernating** — waiting {_hibernate_wait}s for rate-limit window", icon="⏳")
    elif _status_resolved:
        st.info(f"🔵 {_last_action}")
    else:
        st.info("🔵 Harvest active…")

    st.progress(
        _prog_i / _prog_total if _prog_total > 0 else 0.0,
        text=f"Market {_prog_i} of {_prog_total}" if _prog_total > 0 else "Waiting for first market…",
    )
    st.caption("**📋 Live Log**")
    st.markdown(_render_log_html(_tail), unsafe_allow_html=True)

    if not is_processing():
        st.success("🎉 Harvest Complete! Redirecting…")
        time.sleep(3)
        st.cache_data.clear()
        st.rerun(scope="app")


_bg_running = is_processing()

# ---------------------------------------------------------------------------
# Load all data (with stale-cache fallback)
# ---------------------------------------------------------------------------
_db_error: str | None = None

try:
    df_all, _last_updated = load_signals()
    st.session_state["_df_cache"]     = df_all
    st.session_state["_last_updated"] = _last_updated
except Exception as _exc:
    df_all        = st.session_state.get("_df_cache", pd.DataFrame())
    _last_updated = st.session_state.get("_last_updated", "—")
    _db_error     = str(_exc)

try:
    counts = load_counts()
    st.session_state["_counts_cache"] = counts
except Exception as _exc:
    counts    = st.session_state.get("_counts_cache", {"markets": 0, "active_markets": 0, "watchlist": 0, "signals_24h": 0})
    if not _db_error:
        _db_error = str(_exc)

bt_agg     = load_backtest_aggregate()
bt_tickers = load_backtest_tickers()

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("⚡ Alpha Terminal")
    st.caption("Polymarket → Equity Intelligence · BIT Capital")

    st.markdown(f"**{get_ai_status(df_all)}**")
    st.caption(f"Last updated: **{_last_updated}**")

    if st.button(
        "🔄 Refresh Data",
        use_container_width=True,
        disabled=_bg_running,
        help="Disabled while a harvest is active." if _bg_running else None,
    ):
        st.cache_data.clear()
        st.rerun()

    st.divider()

    # --- Filters ---
    st.markdown("#### 🔍 Filters")
    available_tickers = sorted(df_all["Ticker"].dropna().unique().tolist()) if not df_all.empty else []
    ticker_filter = st.multiselect("Ticker", options=available_tickers, placeholder="All tickers")
    sentiment_filter = st.multiselect(
        "Sentiment",
        options=["Bullish", "Bearish", "Neutral"],
        default=["Bullish", "Bearish", "Neutral"],
    )
    min_score = st.slider("Conviction Score", min_value=1, max_value=10, value=1)

    st.divider()
    st.caption(
        f"**{counts.get('markets', 0)}** markets tracked  \n"
        f"**{counts.get('watchlist', 0)}** tickers on watchlist"
    )
    st.divider()

    # --- LLM status ---
    _harvest_logs = st.session_state.get("_last_harvest_logs", [])
    _on_failover  = any(
        "provider switched" in ln or "failover triggered" in ln for ln in _harvest_logs
    )
    if _on_failover:
        st.caption(f"Primary: {_PRIMARY_NAME} | ⚡ {_SECONDARY_NAME}: Failover Active")
    else:
        st.caption(f"Primary: **{_PRIMARY_NAME}** | Failover: {_SECONDARY_NAME}")

    # --- Automation control ---
    st.markdown("#### 🤖 Automation")
    if not CRON_AVAILABLE:
        st.info("Note: Automation features are disabled in this cloud environment.")
    else:
        _cron = get_current_schedule()
        _hour_options = list(range(24))
        _min_options  = [0, 15, 30, 45]
        _cron_h = _cron["hours"]   if _cron["hours"]   in _hour_options else 4
        _cron_m = _cron["minutes"] if _cron["minutes"] in _min_options  else 0

        def _freq_label(h: int, m: int) -> str:
            if h == 0:
                return f"Every {m} min"
            if m == 0:
                return f"Every {h}h"
            return f"Every {h}h {m}m"

        def _on_agent_toggle() -> None:
            if not st.session_state.get("cron_enabled", False):
                try:
                    update_schedule(
                        st.session_state.get("cron_hours", 4),
                        st.session_state.get("cron_minutes", 0),
                        False,
                    )
                except Exception:
                    pass

        _enabled = st.toggle(
            "Enable Background Agent",
            value=_cron["active"],
            key="cron_enabled",
            on_change=_on_agent_toggle,
        )

        _col_h, _col_m = st.columns(2)
        with _col_h:
            _sel_hours = st.selectbox(
                "Hours", options=_hour_options,
                index=_hour_options.index(_cron_h), disabled=not _enabled, key="cron_hours",
            )
        with _col_m:
            _sel_minutes = st.selectbox(
                "Minutes", options=_min_options,
                index=_min_options.index(_cron_m), disabled=not _enabled, key="cron_minutes",
            )

        if st.button("Update Schedule", use_container_width=True, key="cron_update", disabled=not _enabled):
            try:
                update_schedule(_sel_hours, _sel_minutes, _enabled)
                st.success(f"Scheduled: {_freq_label(_sel_hours, _sel_minutes)}.", icon="✅")
            except Exception as _cron_err:
                st.error(f"Failed: {_cron_err}")

        if _bg_running:
            st.info("🤖 Agent harvesting now…")
        elif _cron["active"]:
            st.caption(f"🟢 {_freq_label(_cron_h, _cron_m)}")
        else:
            st.caption("⚪ Agent inactive")

    st.divider()

    # --- Harvest buttons ---
    if _bg_running:
        st.info("🔄 Harvest active — use Terminate in the monitor.", icon="⚙️")
        harvest_clicked       = False
        small_harvest_clicked = False
    else:
        st.warning(
            f"Full harvest: {_PRIMARY_NAME} → {_SECONDARY_NAME} failover pipeline.",
            icon="⚠️",
        )
        harvest_clicked       = st.button("🚀 Start Full Harvest", use_container_width=True, type="primary")
        small_harvest_clicked = st.button(
            "🧪 Small Harvest (--limit 5)",
            use_container_width=True,
            type="secondary",
            help="Quick end-to-end pipeline test on first 5 markets.",
        )

    st.divider()

    # --- Troubleshooting expander ---
    with st.expander("🔧 Troubleshooting"):
        if st.button("Force Clear Process Lock", use_container_width=True, type="secondary", key="force_clear_lock_btn"):
            try:
                clear_lock()
                st.success("Lock cleared.", icon="🔓")
                st.rerun()
            except Exception as _lock_err:
                st.error(f"Error: {_lock_err}")

        st.markdown("**☢️ Danger Zone**")
        st.caption("Deletes all signals and clears the log. Use for clean-slate tests only.")
        if not st.session_state.get("_nuke_confirm_pending"):
            if st.button("☢️ Nuke & Reset Database", use_container_width=True, type="secondary", key="nuke_db_btn"):
                st.session_state["_nuke_confirm_pending"] = True
                st.rerun()
        else:
            st.warning("Permanently deletes **all signals**.", icon="⚠️")
            _nuke_c1, _nuke_c2 = st.columns(2)
            with _nuke_c1:
                if st.button("✅ Confirm", use_container_width=True, type="primary", key="nuke_confirm_btn"):
                    try:
                        _ndb = _get_db_client()
                        _ndb.table("equity_signals").delete().neq("id", -1).execute()
                        LOG_FILE.write_text("")
                        st.session_state.pop("_nuke_confirm_pending", None)
                        st.cache_data.clear()
                        st.toast("Reset complete.", icon="☢️")
                        st.rerun()
                    except Exception as _nuke_err:
                        st.error(f"Nuke failed: {_nuke_err}")
            with _nuke_c2:
                if st.button("Cancel", use_container_width=True, key="nuke_cancel_btn"):
                    st.session_state.pop("_nuke_confirm_pending", None)
                    st.rerun()

    st.toggle("📜 Audit Logs", key="show_audit_logs")


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("⚡ Alpha Terminal")
st.caption("AI-powered equity signal intelligence from prediction markets · BIT Capital Research")
st.divider()

if _db_error:
    st.warning(
        f"⚠️ Database unreachable after {_DB_RETRIES} attempts — showing last known data.  \n`{_db_error}`",
        icon="⚠️",
    )

# ---------------------------------------------------------------------------
# Live Harvest Monitor (takes over page while running)
# ---------------------------------------------------------------------------
if _bg_running:
    st.markdown("#### 🔄 Live Harvest Monitor")
    _live_harvest_monitor()
    st.stop()

# ---------------------------------------------------------------------------
# Harvest launcher
# ---------------------------------------------------------------------------
if harvest_clicked or small_harvest_clicked:
    _cmd = [
        sys.executable,
        "-u",
        str(PROJECT_ROOT / "main.py"),
        "--harvest",
    ]
    if small_harvest_clicked:
        _cmd += ["--limit", "5"]
    pid = _spawn_harvest(_cmd)
    st.session_state.harvest_pid            = pid
    st.session_state.harvest_running         = True
    st.session_state["small_harvest_active"] = small_harvest_clicked
    st.rerun()


# ---------------------------------------------------------------------------
# KPI row — 4 cards from backtest aggregate
# ---------------------------------------------------------------------------
_global_wr  = bt_agg.get("overall_win_rate_pct")
_hc_acc     = bt_agg.get("hc_win_rate_pct")
_scanned_24 = counts.get("signals_24h", 0)

_top_ticker = "—"
if not bt_tickers.empty:
    _judged = bt_tickers[bt_tickers["judged"] > 0].copy()
    if not _judged.empty:
        _best       = _judged.loc[pd.to_numeric(_judged["overall_win_rate_pct"], errors="coerce").idxmax()]
        _top_ticker = f"{_best['ticker']} ({float(_best['overall_win_rate_pct']):.0f}%)"

kpi1, kpi2, kpi3, kpi4 = st.columns(4)
kpi1.metric(
    "Global Win Rate",
    f"{float(_global_wr):.1f}%" if _global_wr is not None else "—",
    help="Overall hit rate across all judged signals in the latest backtest run",
)
kpi2.metric(
    "High-Conviction Accuracy",
    f"{float(_hc_acc):.1f}%" if _hc_acc is not None else "—",
    help="Win rate for signals with Conviction Score ≥ 8",
)
kpi3.metric(
    "Signals Generated (24h)",
    _scanned_24,
    help="Equity signals saved in the last 24 hours",
)
kpi4.metric(
    "Top Performing Ticker",
    _top_ticker,
    help="Highest win rate in the latest backtest run (judged signals only)",
)

st.divider()

# ---------------------------------------------------------------------------
# Guard: no signals yet
# ---------------------------------------------------------------------------
if df_all.empty:
    st.info(
        "No signals yet. Run `venv/bin/python main.py --harvest` to populate the terminal.",
        icon="⏳",
    )
    st.stop()


# ---------------------------------------------------------------------------
# Apply filters
# ---------------------------------------------------------------------------
# Top-level gate: score-0 LLM rejections never appear in the main signal view.
# They are surfaced separately in the Triage Audit Log expander below.
df_signals = df_all[df_all["Score"] > 0].copy()
df_noise   = df_all[df_all["Score"] == 0].copy()

df = df_signals.copy()
if sentiment_filter:
    df = df[df["Impact"].isin(sentiment_filter)]
if ticker_filter:
    df = df[df["Ticker"].isin(ticker_filter)]
df = df[df["Score"] >= min_score]


# ---------------------------------------------------------------------------
# Primary tabs
# ---------------------------------------------------------------------------
_tab_signals, _tab_quant = st.tabs(["🖥 Signal Terminal", "📐 Quant Audit"])


# ── Tab 1: Signal Terminal ────────────────────────────────────────────────────
with _tab_signals:
    _col_head, _col_search = st.columns([2, 3])
    with _col_head:
        st.subheader(f"Signal Terminal  ·  {len(df_signals)} signals total")
    with _col_search:
        _search = st.text_input(
            "search",
            placeholder="🔍  Filter by ticker, question, or rationale…",
            label_visibility="collapsed",
            key="signal_search",
        )

    if _search.strip():
        _q    = _search.strip().lower()
        _mask = (
            df["Ticker"].str.lower().str.contains(_q, na=False)
            | df["Question"].str.lower().str.contains(_q, na=False)
            | df["Rationale"].str.lower().str.contains(_q, na=False)
        )
        df = df[_mask]

    if df.empty:
        st.warning("No signals match the current filters.")
    else:
        _display = df[["Question", "Ticker", "Impact", "Score", "Rationale", "Link", "Created"]]
        _styled  = _display.style.map(lambda v: _IMPACT_CSS.get(v, ""), subset=["Impact"])
        st.dataframe(
            _styled,
            width="stretch",
            hide_index=True,
            column_config={
                "Question":  st.column_config.TextColumn("Market Question", width="large"),
                "Ticker":    st.column_config.TextColumn("Ticker",    width="small"),
                "Impact":    st.column_config.TextColumn("Sentiment", width="small"),
                "Score":     st.column_config.ProgressColumn(
                    "Conviction", min_value=0, max_value=10, format="%d / 10", width="small",
                ),
                "Rationale": st.column_config.TextColumn(
                    "Rationale", width="large", max_chars=160,
                    help="Hover for full reasoning · AI-generated with news citations",
                ),
                "Link":    st.column_config.LinkColumn("Polymarket", width="small"),
                "Created": st.column_config.TextColumn("Analyzed At", width="medium"),
            },
        )


# ── Tab 2: Quant Audit ────────────────────────────────────────────────────────
with _tab_quant:
    st.subheader("Quant Audit")
    _left, _right = st.columns([3, 2])

    # -- Accuracy by Asset (horizontal bar chart) --
    with _left:
        st.markdown("##### Accuracy by Asset")
        st.caption("Win rate % per ticker from the most recent backtest run · 50% = random baseline")

        if bt_tickers.empty:
            st.info(
                "No backtest data yet. Run `python main.py --backtest` to generate results.",
                icon="📊",
            )
        else:
            _chart_df = bt_tickers[bt_tickers["judged"] > 0].copy()
            if _chart_df.empty:
                st.info("All signals in the latest backtest are Neutral — no win rates to display.")
            else:
                _chart_df["Win Rate"] = pd.to_numeric(_chart_df["overall_win_rate_pct"], errors="coerce")
                _chart_df = _chart_df.sort_values("Win Rate", ascending=True)
                _chart_df["Bar Color"] = _chart_df["Win Rate"].apply(
                    lambda x: _EMERALD if x >= 50 else _CRIMSON
                )

                _fig_acc = px.bar(
                    _chart_df,
                    x="Win Rate",
                    y="ticker",
                    orientation="h",
                    color="Bar Color",
                    color_discrete_map="identity",
                    text=_chart_df["Win Rate"].apply(lambda x: f"{x:.0f}%"),
                    labels={"Win Rate": "Win Rate (%)", "ticker": ""},
                    height=max(220, len(_chart_df) * 52),
                )
                _fig_acc.update_traces(
                    textposition="outside",
                    textfont=dict(size=13, color="#e2e8f0"),
                    marker_line_width=0,
                )
                _fig_acc.add_vline(
                    x=50,
                    line_dash="dot",
                    line_color="#475569",
                    annotation_text="50% baseline",
                    annotation_position="top right",
                    annotation_font_color="#64748b",
                    annotation_font_size=11,
                )
                _fig_acc.update_layout(
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    showlegend=False,
                    xaxis=dict(
                        range=[0, 115],
                        gridcolor="#1e293b",
                        ticksuffix="%",
                        tickfont=dict(color="#94a3b8"),
                        title_font=dict(color="#94a3b8"),
                    ),
                    yaxis=dict(tickfont=dict(size=13, color="#e2e8f0")),
                    margin=dict(l=0, r=48, t=8, b=0),
                    font=dict(size=13),
                )
                st.plotly_chart(_fig_acc, width="stretch")

                # Sub-metrics below chart
                _sm1, _sm2, _sm3 = st.columns(3)
                _sm1.metric("Tickers Tracked", len(_chart_df))
                _sm2.metric("Total Judged", int(bt_tickers["judged"].sum()))
                _avg_wr = _chart_df["Win Rate"].mean()
                _sm3.metric("Avg Win Rate", f"{_avg_wr:.1f}%" if not pd.isna(_avg_wr) else "—")

    # -- Backtest Log table --
    with _right:
        st.markdown("##### Backtest Log")
        st.caption("Most recent 15 per-ticker rows across all runs")

        _bt_log = load_backtest_log()
        if _bt_log.empty:
            st.info("No backtest history yet.", icon="📋")
        else:
            _log_display = _bt_log.rename(columns={
                "ticker":               "Ticker",
                "total_signals":        "Signals",
                "judged":               "Judged",
                "overall_win_rate_pct": "Win Rate",
                "hc_win_rate_pct":      "HC Rate",
                "avg_score":            "Avg Sc.",
                "last_bar_date":        "Bar Date",
                "generated_at":         "Run At",
            })
            for _col in ("Win Rate", "HC Rate"):
                _log_display[_col] = _log_display[_col].apply(
                    lambda x: f"{float(x):.1f}%" if pd.notna(x) and x is not None else "—"
                )
            _log_display["Run At"] = (
                pd.to_datetime(_log_display["Run At"], utc=True)
                .dt.strftime("%m-%d %H:%M")
            )
            st.dataframe(
                _log_display,
                width="stretch",
                hide_index=True,
                column_config={
                    "Ticker":   st.column_config.TextColumn("Ticker",   width="small"),
                    "Signals":  st.column_config.NumberColumn("Sig.",    width="small"),
                    "Judged":   st.column_config.NumberColumn("Judged",  width="small"),
                    "Win Rate": st.column_config.TextColumn("Win %",    width="small"),
                    "HC Rate":  st.column_config.TextColumn("HC %",     width="small"),
                    "Avg Sc.":  st.column_config.NumberColumn("Score",   format="%.1f", width="small"),
                    "Bar Date": st.column_config.TextColumn("Bar Date", width="small"),
                    "Run At":   st.column_config.TextColumn("Run At",   width="small"),
                },
            )


# ---------------------------------------------------------------------------
# Audit Log Browser
# ---------------------------------------------------------------------------
if st.session_state.get("show_audit_logs", False):
    st.divider()
    st.subheader("📜 Audit Log Browser")

    if not LOG_FILE.exists() or LOG_FILE.stat().st_size == 0:
        st.info("No log data yet — run a harvest first.", icon="📭")
    else:
        with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as _fh:
            _log_raw = _fh.read()

        _all_log_lines = [ln for ln in _log_raw.splitlines() if ln.strip()]

        st.caption(
            f"**{len(_all_log_lines):,}** total lines · "
            f"viewer shows last **500** (newest first) · "
            f"file size **{LOG_FILE.stat().st_size / 1_024:.1f} KB**"
        )

        _ticker_query = st.text_input(
            "🔍 Filter by ticker or keyword",
            placeholder="e.g. MSTR, 429, Saved, Analysis Complete",
            key="audit_filter",
        )

        # Reverse so newest entries appear at the top of the viewer
        _view_lines = list(reversed(_all_log_lines[-500:]))
        if _ticker_query.strip():
            _q_upper    = _ticker_query.strip().upper()
            _view_lines = [ln for ln in _view_lines if _q_upper in ln.upper()]

        _match_label = (
            f"{len(_view_lines)} match{'es' if len(_view_lines) != 1 else ''} for '{_ticker_query.strip()}'"
            if _ticker_query.strip()
            else f"{len(_view_lines)} lines"
        )
        st.caption(f"Showing **{_match_label}**")

        with st.container(height=500):
            st.code(
                "\n".join(_view_lines) if _view_lines else "— no matches —",
                language=None,
            )


# ---------------------------------------------------------------------------
# Triage Audit Log — AI rejections (score = 0)
# ---------------------------------------------------------------------------
st.divider()
with st.expander("🧹 Triage Audit Log (Noise Rejected)"):
    if df_noise.empty:
        st.caption(
            "No AI rejections recorded yet. LLM-rejected markets (score=0, ticker=null) "
            "will appear here once persisted. Deterministic gate drops (category/keyword) "
            "are visible in the Audit Log above."
        )
    else:
        st.caption(
            f"**{len(df_noise)}** markets rejected by AI with score=0. "
            "The reasoning column shows the model's internal chain-of-thought for each rejection."
        )
        _noise_display = (
            df_noise[["Question", "Rationale"]]
            .rename(columns={"Rationale": "AI Rejection Reasoning"})
        )
        st.dataframe(
            _noise_display,
            width="stretch",
            hide_index=True,
            column_config={
                "Question":             st.column_config.TextColumn("Market Title",          width="large"),
                "AI Rejection Reasoning": st.column_config.TextColumn("Fundamental Reasoning", width="large", max_chars=400),
            },
        )
