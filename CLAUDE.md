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

## Phase Status
- [x] Phase 0 — Scaffold
- [ ] Phase 1 — Kalshi client, NWS client, DB migrations
- [ ] Phase 2 — Historical data backfill
- [ ] Phase 3 — ML training + calibration
- [ ] Phase 4 — Execution loop + risk layer
- [ ] Phase 5 — Monitoring (Prometheus + Grafana)
