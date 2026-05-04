-- =============================================================================
-- Polymarket Scanner — Row Level Security Policies
-- Generated: 2026-04-27
-- =============================================================================
--
-- ROLE OVERVIEW
-- ─────────────────────────────────────────────────────────────────────────────
-- service_role  The key used by the Python backend (analyze.py, app.py).
--               Supabase grants this role BYPASSRLS at the Postgres level, so
--               it always has full access regardless of any policy defined here.
--               No policy is needed — and adding one would have no effect.
--
-- authenticated Supabase Auth users who hold a valid signed JWT
--               (role claim = "authenticated").  Full CRUD access.
--
-- anon          Requests made with the public/anon key, or no key at all.
--               Read-only (SELECT) access only.
-- =============================================================================
-- This script is idempotent: safe to re-run. Existing policies are dropped
-- and recreated so you can update them without manual cleanup.
-- =============================================================================


-- ---------------------------------------------------------------------------
-- markets
-- ---------------------------------------------------------------------------
ALTER TABLE markets ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "markets_authenticated_all"  ON markets;
DROP POLICY IF EXISTS "markets_anon_select"         ON markets;

CREATE POLICY "markets_authenticated_all" ON markets
    FOR ALL
    TO authenticated
    USING (true)
    WITH CHECK (true);

CREATE POLICY "markets_anon_select" ON markets
    FOR SELECT
    TO anon
    USING (true);


-- ---------------------------------------------------------------------------
-- market_prices
-- ---------------------------------------------------------------------------
ALTER TABLE market_prices ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "market_prices_authenticated_all"  ON market_prices;
DROP POLICY IF EXISTS "market_prices_anon_select"         ON market_prices;

CREATE POLICY "market_prices_authenticated_all" ON market_prices
    FOR ALL
    TO authenticated
    USING (true)
    WITH CHECK (true);

CREATE POLICY "market_prices_anon_select" ON market_prices
    FOR SELECT
    TO anon
    USING (true);


-- ---------------------------------------------------------------------------
-- equity_signals
-- ---------------------------------------------------------------------------
ALTER TABLE equity_signals ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "equity_signals_authenticated_all"  ON equity_signals;
DROP POLICY IF EXISTS "equity_signals_anon_select"         ON equity_signals;

CREATE POLICY "equity_signals_authenticated_all" ON equity_signals
    FOR ALL
    TO authenticated
    USING (true)
    WITH CHECK (true);

CREATE POLICY "equity_signals_anon_select" ON equity_signals
    FOR SELECT
    TO anon
    USING (true);


-- ---------------------------------------------------------------------------
-- watchlists
-- ---------------------------------------------------------------------------
ALTER TABLE watchlists ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "watchlists_authenticated_all"  ON watchlists;
DROP POLICY IF EXISTS "watchlists_anon_select"         ON watchlists;

CREATE POLICY "watchlists_authenticated_all" ON watchlists
    FOR ALL
    TO authenticated
    USING (true)
    WITH CHECK (true);

CREATE POLICY "watchlists_anon_select" ON watchlists
    FOR SELECT
    TO anon
    USING (true);
