# Vilya — Architecture Summary

Vilya is an automated trading bot for [Kalshi](https://kalshi.com) that trades weather-based prediction markets. It fetches weather forecasts from NWS and OpenWeather, trains an ML model to predict daily high temperature outcomes, then executes limit orders when the model's edge over market-implied probability exceeds a configurable threshold.

---

## System Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        External APIs                                │
│  Kalshi REST API          NWS (api.weather.gov)    OpenWeather OC3  │
│  api.elections.kalshi.com  (ETag-cached)           (One Call 3.0)   │
└──────────┬───────────────────────┬─────────────────────┬────────────┘
           │                       │                     │
           ▼                       ▼                     ▼
┌──────────────────┐    ┌──────────────────────────────────────────┐
│ kalshi_client/   │    │ weather_data/                            │
│  client.py       │    │  nws_client.py   openweather_client.py  │
│  endpoints.py    │    │  models.py                              │
│  models.py       │    └────────────────┬─────────────────────────┘
└──────────┬───────┘                     │
           │                             ▼
           │                    ┌──────────────────┐
           │                    │ features/         │
           │                    │  forecast_store.py│
           │                    │  engineering.py   │
           │                    │  pipeline.py      │
           │                    └────────┬──────────┘
           │                             │
           │                    ┌────────▼──────────┐
           │                    │ models/            │
           │                    │  train.py          │
           │                    │  predict.py        │
           │                    │  calibrate.py      │
           │                    └────────┬──────────┘
           │                             │
           ▼                             ▼
┌──────────────────────────────────────────────────────────────────┐
│                     execution/                                   │
│   loop.py  ──►  signal.py  ──►  risk.py  ──►  order_manager.py  │
│   (10-min poll)  (edge calc)   (hard limits)  (place/cancel)    │
└──────────────────────────────────────────┬───────────────────────┘
                                           │
                          ┌────────────────▼────────────────┐
                          │           PostgreSQL             │
                          │  kalshi_markets  kalshi_prices  │
                          │  weather_forecasts  trade_log   │
                          │  weather_observations           │
                          └─────────────────────────────────┘
                                           │
                          ┌────────────────▼────────────────┐
                          │    monitoring/                   │
                          │  logger.py (structlog JSON)     │
                          │  metrics.py (Prometheus :8000)  │
                          └─────────────────────────────────┘
```

---

## Layers

### 1. External API Clients (`src/kalshi_client/`, `src/weather_data/`)

| Component | File | What it does | Tech |
|-----------|------|--------------|------|
| KalshiClient | `kalshi_client/client.py` | HTTP wrapper with 5-retry exponential backoff. Authenticates via Bearer token (dev) or RSA-PSS request signing (prod) | `requests`, `cryptography` |
| Kalshi endpoints | `kalshi_client/endpoints.py` | Typed wrappers: `get_markets`, `get_portfolio`, `place_order`, `cancel_order`, `get_open_orders` | Calls `KalshiClient` |
| Kalshi models | `kalshi_client/models.py` | Pydantic v2 models: `Market`, `Order`, `Position`, `Portfolio`, `OrderBook`. Accepts both legacy integer-cent fields and new dollar-string fields | `pydantic` v2 |
| NWSClient | `weather_data/nws_client.py` | Fetches 7-day daily + hourly forecasts from NWS. Resolves lat/lon to gridpoint once, caches ETag to avoid redundant fetches | `requests` |
| OWClient | `weather_data/openweather_client.py` | Fetches forecasts from OpenWeather One Call 3.0 (daily + hourly). Also supports historical timemachine for backfill | `requests` |
| Weather models | `weather_data/models.py` | Pydantic models: `DailyForecast`, `HourlyForecast`, `ForecastSnapshot` | `pydantic` v2 |

**Kalshi auth flow**: If `KALSHI_PRIVATE_KEY_PATH` is set, signs each request with RSA-PSS (`{timestamp_ms}{METHOD}{path}` as message). Otherwise falls back to `Authorization: Bearer {KALSHI_API_KEY}`.

---

### 2. Feature Engineering (`src/features/`)

| Component | File | What it does |
|-----------|------|--------------|
| Forecast store | `forecast_store.py` | Fetches from both NWS + OW, persists `DailyForecast` rows to `weather_forecasts` table |
| Engineering | `engineering.py` | Extracts flat feature dict from `ForecastSnapshot`: NWS/OW high/low temps, precip, humidity, provider spread, seasonal features (day-of-year, month), NOAA 30-year climatology normals |
| Pipeline | `pipeline.py` | ETL: joins `weather_forecasts` + `kalshi_markets` + `weather_observations` with lead-time windows (t24h, t12h, t6h, t3h) into a wide training CSV. Also builds `build_live_feature_row()` for inference |

---

### 3. ML Training & Inference (`src/models/`)

| Component | File | What it does |
|-----------|------|--------------|
| Train | `train.py` | Trains binary classifier (XGBoost or LightGBM) on `yes_settlement` label. 80/20 time-ordered split. Fits isotonic regression calibrator on val set. Saves `model.pkl`, `calibrator.pkl`, `metrics.json` |
| Predict | `predict.py` | Loads `ModelBundle` (classifier + calibrator + feature_names). `predict_prob()` runs forward pass → isotonic calibration → clip to `[0, 1]` |
| Calibrate | `calibrate.py` | Isotonic regression calibration utilities (`fit_isotonic`, save/load) |

**Current model**: XGBoost, 83.4% accuracy, Brier 0.131, ECE ≈ 0 (trained on 2,196 rows — 2024 KXHIGHNY markets)

---

### 4. Execution Loop (`src/execution/`)

| Component | File | What it does |
|-----------|------|--------------|
| Loop | `loop.py` | Main daemon. `run_once()`: fetch portfolio → check kill switch → for each open market: build features → predict → compute signal → risk check → place/cancel orders → log to `trade_log`. `main()` calls `run_once()` every `POLL_INTERVAL_SECONDS` (default 600s) |
| Signal | `signal.py` | `compute_signal()`: calculates `edge_buy = model_prob - market_implied` and `edge_sell = market_implied - model_prob`. Returns `Signal(action="buy_yes"|"buy_no"|"skip")` |
| Risk | `risk.py` | `RiskManager` enforces hard limits: max contracts, max daily notional ($500), kill switch (drawdown > $100). Tracks `RiskState` (daily_notional, peak_equity, killed) |
| Order manager | `order_manager.py` | `OrderManager` places/cancels limit orders and tracks open orders. In paper mode, logs without submitting. `cancel_stale_orders()` cancels if price drifted >5¢ or model_prob drifted >0.10 |

**Decision flow per market tick**:
```
features → predict_prob → compute_signal → risk.check_order → place_limit_order
                                         ↓
                               cancel_stale_orders (runs regardless)
```

---

### 5. Database (`db/`)

PostgreSQL (via SQLAlchemy + Alembic migrations). Five tables:

| Table | Purpose |
|-------|---------|
| `kalshi_markets` | Market metadata: ticker, series, close_time, yes_settlement |
| `kalshi_prices` | Intraday price snapshots (yes_price cents, volume, snapshot_at) |
| `weather_forecasts` | Timestamped forecast snapshots from NWS/OW (high_f, low_f, precip, humidity) |
| `weather_observations` | Actual observed outcomes (actual_high_f, actual_low_f, precip) — used as training labels |
| `trade_log` | Audit trail: every signal evaluation and order decision with full context |

---

### 6. Configuration (`src/config.py`, `.env`)

Pydantic `BaseSettings` loads from `.env`. Key variables:

| Variable | Purpose |
|----------|---------|
| `KALSHI_API_KEY` | Bearer token for Kalshi API |
| `KALSHI_PRIVATE_KEY_PATH` | Path to RSA private key PEM (enables request signing) |
| `OPENWEATHER_API_KEY` | OpenWeather One Call 3.0 key |
| `DATABASE_URL` | SQLAlchemy connection string |
| `PAPER_TRADING` | `true` = log trades but don't submit |
| `EV_THRESHOLD` | Minimum edge to trigger a trade (default 0.03) |
| `MAX_CONTRACTS_PER_MARKET` | Hard cap per market (default 5) |
| `MAX_DAILY_NOTIONAL` | Max daily spend in dollars (default 500) |
| `DRAWDOWN_KILL_SWITCH` | Intraday drawdown threshold to halt trading (default $100) |

---

### 7. Monitoring (`src/monitoring/`)

| Component | File | What it does |
|-----------|------|--------------|
| Logger | `logger.py` | `structlog` JSON logging. Every decision emits a structured log event (ticker, decision, model_prob, edge, etc.) |
| Metrics | `metrics.py` | Prometheus metrics server on port 8000. Tracks: `trades_placed/skipped/cancelled`, `edge_at_trade`, `daily_pnl`, `intraday_drawdown`, `daily_notional`, `data_fetch_latency` |

> Phase 5 (Grafana dashboards) is not yet implemented.

---

### 8. Infrastructure (`infra/`, `.github/`)

| File | Purpose |
|------|---------|
| `infra/docker-compose.dev.yml` | Local dev: Postgres 16 + app container (port 8000 for Prometheus) |
| `infra/Dockerfile` | Multi-stage build: Poetry install → prod image |
| `.github/workflows/ci.yml` | CI: ruff lint + mypy type-check + pytest with Postgres service |

---

### 9. Scripts (`scripts/`)

| Script | Command | Purpose |
|--------|---------|---------|
| `backfill_kalshi.py` | `poetry run python scripts/backfill_kalshi.py --series KXHIGHNY` | Fetch all settled Kalshi markets via `/events` endpoint with cursor pagination |
| `backfill_weather.py` | `poetry run python scripts/backfill_weather.py --start 2024-01-01 --end 2024-12-31` | Backfill historical observations via OW timemachine API |
| `build_coldstart_dataset.py` | `poetry run python scripts/build_coldstart_dataset.py` | Build training CSV using actual observations as forecast proxy (cold-start) |
| `train_model.py` | `poetry run python scripts/train_model.py --csv data/training.csv` | Train + calibrate ML model, save artifacts to `models/` |

---

## Tech Stack Summary

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12 |
| Package manager | Poetry |
| HTTP client | `requests` + `responses` (test mocking) |
| API auth | Bearer token / RSA-PSS (`cryptography`) |
| Data models | Pydantic v2 |
| Database | PostgreSQL 16 + SQLAlchemy (Core) + Alembic |
| ML | XGBoost, LightGBM, scikit-learn (IsotonicRegression) |
| Logging | structlog (JSON) |
| Metrics | Prometheus (`prometheus-client`) |
| Formatting | black (line-length 100) |
| Linting | ruff |
| Type checking | mypy (strict) |
| Testing | pytest + responses + pytest-cov |
| CI | GitHub Actions |
| Container | Docker + Docker Compose |

---

## Development Phases

- [x] Phase 0 — Scaffold
- [x] Phase 1 — Kalshi client, NWS client, DB migrations
- [x] Phase 2 — Historical data backfill + feature engineering
- [x] Phase 3 — ML training + calibration (XGBoost/LightGBM + isotonic)
- [x] Phase 4 — Execution loop + risk layer
- [ ] Phase 5 — Monitoring (Prometheus + Grafana dashboards)
