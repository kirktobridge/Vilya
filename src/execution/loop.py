"""Main daemon: poll every 10 min, orchestrate signal -> risk -> order."""
import json
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, text

from src.config import settings
from src.db import get_engine
from src.execution.order_manager import OrderManager
from src.execution.risk import RiskError, RiskManager
from src.execution.signal import Signal, compute_signal
from src.features.forecast_store import fetch_and_store_forecasts
from src.features.pipeline import build_live_feature_row
from src.kalshi_client.client import KalshiClient
from src.kalshi_client.endpoints import get_markets, get_portfolio
from src.models.predict import ModelBundle, load_model, predict_prob
from src.monitoring.logger import configure_logging, get_logger
from src.weather_data.nws_client import NWSClient
from src.weather_data.openweather_client import OWClient

log = get_logger(__name__)

_INSERT_TRADE = text("""
  INSERT INTO trade_log
    (ticker, decision, model_prob, market_implied, edge, contracts, order_id,
     forecasts_snapshot, logged_at)
  VALUES
    (:ticker, :decision, :model_prob, :market_implied, :edge, :contracts, :order_id,
     CAST(:forecasts_snapshot AS jsonb), :logged_at)
""")


def run_once(
  *,
  client: KalshiClient,
  risk: RiskManager,
  orders: OrderManager,
  model: ModelBundle,
  engine: Engine,
  series_ticker: str,
  location: str,
  ev_threshold: float,
  max_contracts: int,
) -> None:
  """Single poll cycle: fetch data, compute signals, execute orders."""
  risk.reset_daily()

  portfolio = get_portfolio(client)
  risk.update_equity(portfolio.available_balance_usd)

  try:
    risk.check_kill_switch()
  except RiskError:
    orders.cancel_all()
    return

  # Build position map: ticker -> net YES contracts held
  pos_by_ticker = {p.ticker: p.yes_contracts for p in portfolio.positions}

  markets = get_markets(client, series_ticker)
  now = datetime.now(timezone.utc)

  for market in markets:
    if market.close_time and market.close_time <= now:
      continue  # already closed

    valid_date: date = market.close_time.date() if market.close_time else date.today()
    features = build_live_feature_row(market.ticker, valid_date, location)

    if features is None:
      log.warning("no_features", ticker=market.ticker)
      continue

    model_prob = predict_prob(model, features)
    yes_price = market.yes_price

    # Cancel stale orders before considering new ones
    orders.cancel_stale_orders(market.ticker, yes_price, model_prob)

    signal = compute_signal(market.ticker, model_prob, yes_price, ev_threshold)

    if signal.action == "skip":
      log.info("signal_skip", ticker=market.ticker, edge_buy=signal.edge_buy)
      _log_trade(engine, signal, contracts=0, order_id=None, features=features)
      continue

    # Check existing position
    side = "yes" if signal.action == "buy_yes" else "no"
    held = pos_by_ticker.get(market.ticker, 0)
    if held >= max_contracts:
      log.info("position_maxed", ticker=market.ticker, held=held)
      _log_trade(engine, signal, contracts=0, order_id=None, features=features)
      continue

    contracts = min(1, max_contracts - held)
    price_cents = yes_price if side == "yes" else 100 - yes_price

    try:
      risk.check_order(contracts, price_cents)
    except RiskError as exc:
      log.warning("risk_blocked", ticker=market.ticker, reason=str(exc))
      _log_trade(engine, signal, contracts=0, order_id=None, features=features)
      continue

    order_id = orders.place_limit_order(market.ticker, side, contracts, price_cents, model_prob)
    risk.record_order(contracts, price_cents)
    _log_trade(engine, signal, contracts=contracts, order_id=order_id, features=features)


def _log_trade(
  engine: Engine,
  signal: Signal,
  contracts: int,
  order_id: str | None,
  features: dict[str, float],
) -> None:
  edge = signal.edge_buy if signal.action == "buy_yes" else signal.edge_sell
  try:
    with engine.begin() as conn:
      conn.execute(_INSERT_TRADE, {
        "ticker": signal.ticker,
        "decision": signal.action,
        "model_prob": signal.model_prob,
        "market_implied": signal.market_implied,
        "edge": edge,
        "contracts": contracts,
        "order_id": order_id,
        "forecasts_snapshot": json.dumps({k: v for k, v in features.items() if v == v}),
        "logged_at": datetime.now(timezone.utc),
      })
  except Exception:
    log.exception("trade_log_failed", ticker=signal.ticker)


def main() -> None:
  configure_logging(settings.log_level)
  log.info("bot_starting", env=settings.env, paper=settings.paper_trading)

  client = KalshiClient()
  risk = RiskManager()
  orders = OrderManager(client, paper=settings.paper_trading)
  engine = get_engine()
  nws = NWSClient()
  ow = OWClient()
  model = load_model(
    Path(settings.model_dir) / "model.pkl",
    Path(settings.model_dir) / "calibrator.pkl",
  )

  while True:
    try:
      fetch_and_store_forecasts(
        nws, ow, engine, settings.target_location,
        settings.target_lat, settings.target_lon,
      )
      run_once(
        client=client,
        risk=risk,
        orders=orders,
        model=model,
        engine=engine,
        series_ticker=settings.kalshi_series_ticker,
        location=settings.target_location,
        ev_threshold=settings.ev_threshold,
        max_contracts=settings.max_contracts_per_market,
      )
    except Exception:
      log.exception("poll_cycle_error")
    time.sleep(settings.poll_interval_seconds)


if __name__ == "__main__":
  main()
