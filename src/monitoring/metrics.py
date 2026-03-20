from prometheus_client import Counter, Gauge, Histogram, start_http_server

# Trade lifecycle counters
trades_placed = Counter(
  "bot_trades_placed_total",
  "Total number of orders submitted to Kalshi",
  ["side", "ticker"],
)
trades_skipped = Counter(
  "bot_trades_skipped_total",
  "Signals evaluated but skipped (below threshold or risk blocked)",
  ["reason"],
)
trades_cancelled = Counter(
  "bot_trades_cancelled_total",
  "Open orders cancelled by the bot",
  ["reason"],
)

# Edge and P&L
edge_at_trade = Histogram(
  "bot_edge_at_trade",
  "Distribution of edge values when a trade was placed",
  buckets=[0.03, 0.05, 0.07, 0.10, 0.15, 0.20, 0.30],
)
daily_pnl = Gauge(
  "bot_daily_pnl_usd",
  "Intraday realized P&L in USD",
)
intraday_drawdown = Gauge(
  "bot_intraday_drawdown_usd",
  "Current intraday drawdown from peak equity",
)
daily_notional = Gauge(
  "bot_daily_notional_usd",
  "Cumulative notional traded today in USD",
)

# Data freshness
data_fetch_latency = Histogram(
  "bot_data_fetch_latency_seconds",
  "Latency for external data fetches",
  ["source"],
  buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)
data_fetch_errors = Counter(
  "bot_data_fetch_errors_total",
  "Failed external data fetches",
  ["source"],
)

# Model
model_prob = Gauge(
  "bot_model_probability",
  "Latest model P(YES) for each active market",
  ["ticker"],
)


def start_metrics_server(port: int = 8000) -> None:
  """Start Prometheus HTTP metrics endpoint."""
  start_http_server(port)
