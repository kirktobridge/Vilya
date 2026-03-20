"""ETL pipeline: join forecasts + Kalshi prices into feature rows."""
# Phase 2: implement full bodies
from typing import Any


def build_training_dataset(
  forecasts_table: str,
  prices_table: str,
  observations_table: str,
  output_path: str,
) -> None:
  """
  Join weather_forecasts + kalshi_prices + weather_observations into a
  wide training CSV keyed on (ticker, forecast_lead_hours).
  """
  raise NotImplementedError


def build_live_feature_row(ticker: str, db_conn: Any) -> dict[str, float] | None:
  """Pull latest forecast snapshot + price and return a live feature dict."""
  raise NotImplementedError
