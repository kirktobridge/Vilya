"""ETL pipeline: join DB tables into a training-ready CSV."""
import math
import re
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
  Build a live feature dict whose keys match the training CSV schema.

  Fetches the latest NWS and OW snapshots for valid_date, populates every
  lead-time variant (t24/t12/t6/t3) with the same current values, and
  computes threshold/direction features from the ticker and market title.
  """
  engine = get_engine()
  _nan = float("nan")

  with engine.connect() as conn:
    title_row = conn.execute(
      text("SELECT title FROM kalshi_markets WHERE ticker = :t"),
      {"t": ticker},
    ).fetchone()
    title = str(title_row[0]) if title_row and title_row[0] else ""

    fc_rows = conn.execute(
      text("""
        SELECT DISTINCT ON (source)
          source, forecast_high_f, forecast_low_f, precip_prob, humidity_pct
        FROM weather_forecasts
        WHERE location = :loc AND valid_date = :dt
        ORDER BY source, fetched_at DESC
      """),
      {"loc": location, "dt": valid_date},
    ).fetchall()

  if not fc_rows:
    return None

  by_src: dict[str, dict[str, float]] = {}
  for r in fc_rows:
    src, high, low, precip, humidity = r
    by_src[src] = {
      "forecast_high_f": float(high) if high is not None else _nan,
      "forecast_low_f": float(low) if low is not None else _nan,
      "precip_prob": float(precip) if precip is not None else _nan,
      "humidity_pct": float(humidity) if humidity is not None else _nan,
    }

  row: dict[str, float] = {}
  for lead in ("t24", "t12", "t6", "t3"):
    for feat_src, db_src in (("nws", "nws"), ("ow", "openweather")):
      vals = by_src.get(db_src, {})
      prefix = f"{feat_src}_{lead}"
      for col in ("forecast_high_f", "forecast_low_f", "precip_prob", "humidity_pct"):
        row[f"{prefix}_{col}"] = vals.get(col, _nan)

  d = valid_date if isinstance(valid_date, date) else date.fromisoformat(str(valid_date))
  seasonal = build_seasonal_features(d)
  clim_mean, clim_std = compute_climatology(location, d.month, d.day)
  row.update(seasonal)
  row["clim_mean_high"] = clim_mean
  row["clim_std_high"] = clim_std

  # Threshold features (mirrors train._add_derived_features for a single row)
  t_match = re.search(r"-[TB]?(\d+(?:\.\d+)?)$", str(ticker))
  threshold_f = float(t_match.group(1)) if t_match else _nan
  row["threshold_f"] = threshold_f

  is_above = 1.0 if ">" in title else (0.0 if "<" in title else _nan)
  row["is_above_threshold"] = is_above
  row["is_bucket_market"] = 1.0 if re.search(r"-B\d", str(ticker)) else 0.0

  for lead in ("t24", "t12", "t6", "t3"):
    for src in ("nws", "ow"):
      high = row.get(f"{src}_{lead}_forecast_high_f", _nan)
      if math.isnan(high):
        continue
      dev = high - threshold_f if not math.isnan(threshold_f) else _nan
      row[f"{src}_{lead}_clim_dev"] = high - clim_mean
      row[f"{src}_{lead}_threshold_dev"] = dev
      if not math.isnan(dev) and not math.isnan(is_above):
        row[f"{src}_{lead}_threshold_dev_signed"] = dev * (2 * is_above - 1)
      else:
        row[f"{src}_{lead}_threshold_dev_signed"] = _nan

  return row


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


