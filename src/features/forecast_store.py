"""Persist weather forecast snapshots to the weather_forecasts table."""
from typing import Any

from sqlalchemy import Engine, text

from src.monitoring.logger import get_logger
from src.weather_data.models import DailyForecast

log = get_logger(__name__)

_INSERT_FORECAST = text("""
  INSERT INTO weather_forecasts
    (location, source, valid_date, forecast_high_f, forecast_low_f,
     precip_prob, humidity_pct, fetched_at)
  VALUES
    (:location, :source, :valid_date, :forecast_high_f, :forecast_low_f,
     :precip_prob, :humidity_pct, :fetched_at)
""")


def save_forecasts(
  engine: Engine,
  location: str,
  forecasts: list[DailyForecast],
) -> int:
  """Insert daily forecast rows into weather_forecasts. Returns count saved."""
  if not forecasts:
    return 0
  rows = [
    {
      "location": location,
      "source": f.source,
      "valid_date": f.valid_date,
      "forecast_high_f": f.high_f,
      "forecast_low_f": f.low_f,
      "precip_prob": f.precip_prob,
      "humidity_pct": f.humidity_pct,
      "fetched_at": f.fetched_at,
    }
    for f in forecasts
  ]
  with engine.begin() as conn:
    conn.execute(_INSERT_FORECAST, rows)
  log.info("forecasts_saved", location=location, count=len(rows))
  return len(rows)


def fetch_and_store_forecasts(
  nws: Any,
  ow: Any,
  engine: Engine,
  location: str,
  lat: float,
  lon: float,
) -> None:
  """Fetch today's forecasts from NWS + OW and persist to DB."""
  try:
    nws_forecasts = nws.fetch_daily_forecast(lat, lon)
    save_forecasts(engine, location, nws_forecasts)
  except Exception:
    log.exception("nws_forecast_fetch_failed", location=location)

  try:
    ow_forecasts = ow.fetch_daily_forecast(lat, lon)
    save_forecasts(engine, location, ow_forecasts)
  except Exception:
    log.exception("ow_forecast_fetch_failed", location=location)
