-- =============================================================================
-- Polymarket Scanner — Seed Data
-- Generated: 2026-04-27
-- Table: watchlists (23 tickers across AI, Crypto, and Space sectors)
-- =============================================================================

INSERT INTO watchlists (ticker, sector) VALUES
    -- AI / Cloud & Enterprise
    ('ORCL', 'AI/Cloud'),
    ('IBM',  'AI/Enterprise'),

    -- AI / Semiconductors
    ('AMD',  'AI/Semiconductors'),
    ('INTC', 'AI/Semiconductors'),
    ('NVDA', 'AI/Semiconductors'),

    -- AI / Software & Technology
    ('PLTR', 'AI/Software'),
    ('TSLA', 'AI/EV/Technology'),
    ('AAPL', 'AI/Technology'),
    ('AMZN', 'AI/Technology'),
    ('GOOGL','AI/Technology'),
    ('META', 'AI/Technology'),
    ('MSFT', 'AI/Technology'),

    -- Crypto
    ('MSTR', 'Crypto/Bitcoin'),
    ('COIN', 'Crypto/Exchange'),
    ('PYPL', 'Crypto/Fintech'),
    ('SQ',   'Crypto/Fintech'),
    ('BMNR', 'Crypto/Mining'),
    ('BTBT', 'Crypto/Mining'),
    ('CLSK', 'Crypto/Mining'),
    ('HUT',  'Crypto/Mining'),
    ('MARA', 'Crypto/Mining'),
    ('RIOT', 'Crypto/Mining'),

    -- Space
    ('SPCE', 'Space/Technology')

ON CONFLICT (ticker) DO NOTHING;
