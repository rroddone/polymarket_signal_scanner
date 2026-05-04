-- =============================================================================
-- Polymarket Scanner — Schema Export
-- Generated: 2026-04-27
-- Database: Supabase (Postgres 17) | Project: polymarket_scanner
-- =============================================================================

-- Core Market Metadata
CREATE TABLE markets (
    id          TEXT PRIMARY KEY,
    slug        TEXT,
    question    TEXT NOT NULL,
    end_date    TIMESTAMP WITH TIME ZONE,
    category    TEXT,
    active      BOOLEAN DEFAULT true,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Time-Series Price Snapshots
CREATE TABLE market_prices (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    market_id   TEXT REFERENCES markets(id),
    price       DECIMAL(3, 2),
    volume_24h  DECIMAL,
    timestamp   TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- LLM Analysis Results (Gemini-generated equity signals)
CREATE TABLE equity_signals (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    market_id        TEXT REFERENCES markets(id),
    ticker           TEXT,
    relevance_score  INTEGER,
    impact_type      TEXT,
    rationale        TEXT,
    citations        JSONB,
    created_at       TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Sector Watchlist (tickers monitored for signal correlation)
CREATE TABLE watchlists (
    ticker      TEXT PRIMARY KEY,
    sector      TEXT,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
