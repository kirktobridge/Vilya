"""ETL pipeline: join DB tables into a training-ready CSV."""
from datetime import date, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import text

from src.db import get_engine
from src.features.engineering import build_seasonal_features, compute_climatology
from src.monitoring.logger import get_logger

log = get_logger(__name__)

# Lead-time windows in hours: label -> (min_hours_before_close, max_hours_before_close)
_LEAD_WINDOWS: dict[str, tuple[int, int]] = {
  "t24": (20, 28),
  "t12": (8, 16),
  "t6":  (3,  9),
  "t3":  (1,  5),
}


def build_training_dataset(
  output_path: str,
  location: str = "NYC_CENTRAL_PARK",
  series_ticker: str = "KXHIGHNY",
) -> pd.DataFrame:
  """
  Join weather_forecasts + kalshi_markets into a wide training CSV.

  For each settled market, looks up NWS and OW forecast snapshots at
  T-24, T-12, T-6, T-3 lead times and pivots them into one wide row.
  Writes CSV to output_path and returns the DataFrame.
  """
  engine = get_engine()

  markets = _load_settled_markets(engine, series_ticker)
  if markets.empty:
    log.warning("pipeline_no_markets", series_ticker=series_ticker)
    return markets

  forecasts = _load_forecasts(engine, location)
  if forecasts.empty:
    log.warning("pipeline_no_forecasts", location=location)
    return pd.DataFrame()

  rows = [_build_row(m, forecasts, location) for _, m in markets.iterrows()]
  df = pd.DataFrame([r for r in rows if r is not None])
  df.to_csv(output_path, index=False)
  log.info("pipeline_csv_written", path=output_path, rows=len(df))
  return df


def build_live_feature_row(
  ticker: str,
  valid_date: date,
  location: str = "NYC_CENTRAL_PARK",
) -> dict[str, float] | None:
  """
  Pull the latest forecast snapshot from the DB and return a live feature dict.
  Used by the execution loop to feed the model at inference time.
  """
  engine = get_engine()
  forecasts = _load_forecasts(engine, location)
  if forecasts.empty:
    return None

  target_date_str = valid_date.isoformat()
  day_forecasts = forecasts[forecasts["valid_date"] == target_date_str]
  if day_forecasts.empty:
    return None

  latest = day_forecasts.sort_values("fetched_at").iloc[-1]
  features = _row_to_feature_dict(latest, suffix="latest")
  seasonal = build_seasonal_features(valid_date)
  clim_mean, clim_std = compute_climatology(location, valid_date.month, valid_date.day)
  return {**features, **seasonal, "clim_mean_high": clim_mean, "clim_std_high": clim_std}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_settled_markets(engine: Any, series_ticker: str) -> pd.DataFrame:
  sql = text("""
    SELECT ticker, close_time, close_time::date AS valid_date, yes_settlement
    FROM kalshi_markets
    WHERE series_ticker = :series AND yes_settlement IS NOT NULL
    ORDER BY close_time
  """)
  return pd.read_sql(sql, engine, params={"series": series_ticker})


def _load_forecasts(engine: Any, location: str) -> pd.DataFrame:
  sql = text("""
    SELECT source, valid_date::text AS valid_date, forecast_high_f, forecast_low_f,
           precip_prob, humidity_pct, fetched_at
    FROM weather_forecasts
    WHERE location = :loc
    ORDER BY fetched_at
  """)
  return pd.read_sql(sql, engine, params={"loc": location})


def _build_row(
  market: "pd.Series[Any]",
  forecasts: pd.DataFrame,
  location: str,
) -> dict[str, float] | None:
  """Build one wide feature row for a single settled market."""
  close_time = pd.Timestamp(market["close_time"])
  valid_date = str(market["valid_date"])
  day_fc = forecasts[forecasts["valid_date"] == valid_date]
  if day_fc.empty:
    return None

  row: dict[str, Any] = {
    "ticker": market["ticker"],
    "valid_date": valid_date,
    "yes_settlement": int(market["yes_settlement"]),
  }

  for label, (lo, hi) in _LEAD_WINDOWS.items():
    window_lo = close_time - timedelta(hours=hi)
    window_hi = close_time - timedelta(hours=lo)
    window = day_fc[
      (pd.to_datetime(day_fc["fetched_at"]) >= window_lo) &
      (pd.to_datetime(day_fc["fetched_at"]) <= window_hi)
    ]
    for source in ("nws", "openweather"):
      src_rows = window[window["source"] == source]
      if src_rows.empty:
        continue
      # Pick the snapshot whose fetched_at is closest to the target lead time
      target_ts = close_time - timedelta(hours=(lo + hi) / 2)
      closest = src_rows.iloc[(pd.to_datetime(src_rows["fetched_at"]) - target_ts).abs().argsort()[:1]]
      prefix = f"{source.replace('openweather', 'ow')}_{label}"
      for col in ("forecast_high_f", "forecast_low_f", "precip_prob", "humidity_pct"):
        val = closest.iloc[0][col]
        row[f"{prefix}_{col}"] = float(val) if val is not None else float("nan")

  d = date.fromisoformat(valid_date)
  seasonal = build_seasonal_features(d)
  clim_mean, clim_std = compute_climatology(location, d.month, d.day)
  row.update(seasonal)
  row["clim_mean_high"] = clim_mean
  row["clim_std_high"] = clim_std
  return row


def _row_to_feature_dict(row: "pd.Series[Any]", suffix: str) -> dict[str, float]:
  return {
    f"nws_{suffix}_high_f": float(row.get("forecast_high_f") or float("nan")),
    f"nws_{suffix}_low_f": float(row.get("forecast_low_f") or float("nan")),
    f"nws_{suffix}_precip_prob": float(row.get("precip_prob") or 0.0),
  }
