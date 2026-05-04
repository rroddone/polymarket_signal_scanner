-- Migration: create_backtest_history
-- Stores every backtest run's aggregate metrics so results are
-- queryable over time rather than overwritten in a JSON file.

CREATE TABLE IF NOT EXISTS backtest_history (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    generated_at         TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    pre_market           BOOLEAN,
    last_bar_date        DATE,
    total_signals        INTEGER,
    judged               INTEGER,
    neutral              INTEGER,
    avg_score            DECIMAL(4, 2),
    overall_win_rate_pct DECIMAL(5, 2),
    bullish_win_rate_pct DECIMAL(5, 2),
    bearish_win_rate_pct DECIMAL(5, 2),
    hc_win_rate_pct      DECIMAL(5, 2),
    hc_count             INTEGER,
    hc_hits              INTEGER,
    top3_by_pct          JSONB
);

ALTER TABLE backtest_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_all" ON backtest_history
    FOR ALL
    USING (true)
    WITH CHECK (true);
