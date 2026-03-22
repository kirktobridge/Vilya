# Kalshi Weather Bot — Claude Code Guide

## Architecture
Monorepo. All source code lives in `src/`. Tests in `tests/`. DB migrations in `db/migrations/` (Alembic). Infra configs in `infra/`.

## Code Standards
- Python 3.12, Poetry
- 2-space indentation
- black formatting (line-length 100), ruff linting, mypy strict
- Pydantic v2 for all external API models
- structlog only — never use `print()` or `logging.basicConfig()`
- Functions ≤ 50 lines; one responsibility per function
- All API keys via `.env` — never hardcode secrets

## Environment Setup (Windows)
- Python 3.12 installed via python.org installer ✓
- Poetry installed via `pip install poetry` (if `poetry` not on PATH, use `python -m poetry`)
- Docker Desktop required for Postgres

## Running Locally
```bash
cp .env.example .env          # fill in real keys
docker compose -f infra/docker-compose.dev.yml up -d   # start postgres
poetry install
poetry run alembic upgrade head
poetry run bot                # starts 10-min polling loop
```

## Testing
```bash
poetry run pytest             # runs all tests with coverage
poetry run ruff check src/
poetry run mypy src/
```

## Risk Rules (never bypass)
- Max 5 contracts per market tick
- Max $500 notional per calendar day
- Cancel open orders if model_prob drifts >0.10 since placement
- Cancel open orders if yes_price moves >5¢ from our limit
- Kill switch: halt all trading if intraday drawdown > $100
- Limit orders only in production — no market orders
- Log every decision (skip / buy / cancel) to `trade_log` table

## Key Environment Variables
| Variable | Purpose |
|---|---|
| `KALSHI_API_KEY` | Bearer token for Kalshi REST API |
| `OPENWEATHER_API_KEY` | OpenWeather One Call 3.0 |
| `DATABASE_URL` | SQLAlchemy connection string |
| `PAPER_TRADING` | `true` = log trades but don't submit |
| `EV_THRESHOLD` | Minimum edge to trigger a trade (default 0.03) |

## Model Training

### Cold-start (no live data yet)
```bash
poetry run python scripts/build_coldstart_dataset.py   # writes data/training_v2.csv
poetry run python scripts/train_model.py --csv data/training_v2.csv --output models/
```
Cold-start uses observed highs as a proxy for all lead-time forecast columns (t24/t12/t6/t3). This is intentional — the bot hasn't accumulated real forecast snapshots yet.

### Proper retraining (after live data accumulates)
Use `pipeline.build_training_dataset()` instead of the cold-start script. Requires ~180 days of continuous bot operation (≥1,080 market rows) for meaningful lead-time signal. Full seasonal coverage needs ~365 days.

### Current model artifacts
- `models/model.pkl`, `models/calibrator.pkl`, `models/metrics.json`
- Trained on `data/training_v2.csv` — 2,196 rows, 2024 KXHIGHNY markets
- Accuracy: 83.41%, Brier: 0.1325, ECE ≈ 0
- Top features: `nws_t6_threshold_dev_signed`, `nws_t24_threshold_dev_signed`, `is_above_threshold`

### Key feature engineering notes
- `threshold_dev_signed = (forecast_high − threshold) × (1 if above else −1)` — positive always means "more likely YES"
- T-type markets: both "above X°F" (`>` in title) and "below X°F" (`<` in title) — direction matters
- B-type bucket markets: threshold is lower bound of bucket (e.g., `B83.5` → 83.5°F)
- `_parse_threshold_f` regex: `-[TB]?(\d+(?:\.\d+)?)$` — handles T-prefix, B-prefix, and plain numeric

## API Notes
- **NWS** (`api.weather.gov`): free, no API key — only requires a descriptive `User-Agent` header
- **OpenWeather**: requires `OPENWEATHER_API_KEY`
- **Kalshi**: requires `KALSHI_API_KEY` (Bearer token)

## Phase Status
- [x] Phase 0 — Scaffold
- [x] Phase 1 — Kalshi client, NWS client, DB migrations
- [x] Phase 2 — Historical data backfill + feature engineering
- [x] Phase 3 — ML training + calibration (XGBoost/LightGBM + isotonic calibration)
- [x] Phase 4 — Execution loop + risk layer (10-min poll, signal → risk → order)
- [ ] Phase 5 — Monitoring (Prometheus + Grafana)

## Known Gaps (from PDF design review)
- Forecast delta features: `high_f_delta_t24_to_t12`, etc. not yet computed
- Per-event exposure cap: no grouping of correlated markets by event date
- Backtester: no offline simulation framework
- Real forecast snapshots: `weather_forecasts` table is empty until bot runs continuously
