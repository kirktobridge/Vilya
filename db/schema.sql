-- kalshi_markets: discovered weather markets
CREATE TABLE IF NOT EXISTS kalshi_markets (
    ticker TEXT PRIMARY KEY,
    series_ticker TEXT NOT NULL,
    event_ticker TEXT NOT NULL,
    title TEXT,
    open_date DATE,
    close_time TIMESTAMPTZ,
    settlement_value TEXT,
    yes_settlement BOOLEAN,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- kalshi_prices: price snapshots over trading day
CREATE TABLE IF NOT EXISTS kalshi_prices (
    id BIGSERIAL PRIMARY KEY,
    ticker TEXT REFERENCES kalshi_markets(ticker),
    yes_price SMALLINT,
    volume INTEGER,
    snapshot_at TIMESTAMPTZ NOT NULL
);

-- weather_forecasts: timestamped forecast snapshots per location
CREATE TABLE IF NOT EXISTS weather_forecasts (
    id BIGSERIAL PRIMARY KEY,
    location TEXT NOT NULL,
    source TEXT NOT NULL,
    valid_date DATE NOT NULL,
    forecast_high_f NUMERIC(5,2),
    forecast_low_f NUMERIC(5,2),
    precip_prob NUMERIC(4,3),
    humidity_pct SMALLINT,
    fetched_at TIMESTAMPTZ NOT NULL
);

-- weather_observations: actual observed outcomes
CREATE TABLE IF NOT EXISTS weather_observations (
    id BIGSERIAL PRIMARY KEY,
    location TEXT NOT NULL,
    obs_date DATE NOT NULL,
    actual_high_f NUMERIC(5,2),
    actual_low_f NUMERIC(5,2),
    actual_precip_in NUMERIC(5,3),
    source TEXT,
    UNIQUE(location, obs_date)
);

-- trade_log: every signal and order decision
CREATE TABLE IF NOT EXISTS trade_log (
    id BIGSERIAL PRIMARY KEY,
    ticker TEXT,
    decision TEXT,
    model_prob NUMERIC(5,4),
    market_implied NUMERIC(5,4),
    edge NUMERIC(5,4),
    contracts INTEGER,
    order_id TEXT,
    forecasts_snapshot JSONB,
    logged_at TIMESTAMPTZ DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_kalshi_prices_ticker_time ON kalshi_prices(ticker, snapshot_at DESC);
CREATE INDEX IF NOT EXISTS idx_weather_forecasts_location_date ON weather_forecasts(location, valid_date DESC);
CREATE INDEX IF NOT EXISTS idx_trade_log_ticker ON trade_log(ticker, logged_at DESC);
