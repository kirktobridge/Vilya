"""Build a cold-start training CSV from weather_observations + kalshi_markets.

Used when no historical weather_forecasts rows exist (i.e., the bot hasn't run
long enough to accumulate forecast snapshots). Fills every forecast feature
column (nws_t24_forecast_high_f, etc.) with actual_high_f from observations,
which is the best available proxy: the actual high is exactly what determines
whether a YES-threshold market settles true.

Usage:
  poetry run python scripts/build_coldstart_dataset.py \\
    --output data/coldstart_training.csv
"""
import argparse
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from src.db import get_engine
from src.features.engineering import build_seasonal_features, compute_climatology
from src.monitoring.logger import configure_logging, get_logger

log = get_logger(__name__)

_LEAD_TIMES = ("t24", "t12", "t6", "t3")
_SOURCES = ("nws", "ow")


def build_coldstart_dataset(
  output_path: str,
  location: str = "NYC_CENTRAL_PARK",
  series_ticker: str = "KXHIGHNY",
) -> pd.DataFrame:
  """
  Join weather_observations + settled kalshi_markets into a training CSV.

  Every forecast column is populated with the actual observed high/low as a
  proxy. The model learns the relationship between (actual_high - threshold)
  and yes_settlement, which transfers reasonably well to live inference where
  actual_high is replaced by forecast_high.
  """
  engine = get_engine()

  markets = pd.read_sql(
    text("""
      SELECT ticker, title, close_time::date AS valid_date, yes_settlement
      FROM kalshi_markets
      WHERE series_ticker = :series AND yes_settlement IS NOT NULL
      ORDER BY close_time
    """),
    engine,
    params={"series": series_ticker},
  )

  obs = pd.read_sql(
    text("""
      SELECT obs_date::text AS valid_date, actual_high_f, actual_low_f
      FROM weather_observations
      WHERE location = :loc
    """),
    engine,
    params={"loc": location},
  )

  if markets.empty:
    log.warning("coldstart_no_markets", series_ticker=series_ticker)
    return markets

  if obs.empty:
    log.warning("coldstart_no_observations", location=location)
    return markets

  markets["valid_date"] = markets["valid_date"].astype(str)
  merged = markets.merge(obs, on="valid_date", how="inner")

  if merged.empty:
    log.warning("coldstart_no_overlap", location=location, series_ticker=series_ticker)
    return pd.DataFrame()

  rows = []
  for _, m in merged.iterrows():
    d = date.fromisoformat(m["valid_date"])
    high_f = float(m["actual_high_f"]) if m["actual_high_f"] is not None else float("nan")
    low_f = float(m["actual_low_f"]) if m["actual_low_f"] is not None else float("nan")

    row: dict = {
      "ticker": m["ticker"],
      "title": m["title"],
      "valid_date": m["valid_date"],
      "yes_settlement": int(m["yes_settlement"]),
    }

    for src in _SOURCES:
      for lead in _LEAD_TIMES:
        prefix = f"{src}_{lead}"
        row[f"{prefix}_forecast_high_f"] = high_f
        row[f"{prefix}_forecast_low_f"] = low_f
        row[f"{prefix}_precip_prob"] = float("nan")
        row[f"{prefix}_humidity_pct"] = float("nan")

    seasonal = build_seasonal_features(d)
    clim_mean, clim_std = compute_climatology(location, d.month, d.day)
    row.update(seasonal)
    row["clim_mean_high"] = clim_mean
    row["clim_std_high"] = clim_std
    rows.append(row)

  df = pd.DataFrame(rows)
  Path(output_path).parent.mkdir(parents=True, exist_ok=True)
  df.to_csv(output_path, index=False)
  log.info("coldstart_csv_written", path=output_path, rows=len(df))
  return df


def main() -> None:
  configure_logging("INFO")
  parser = argparse.ArgumentParser(description="Build cold-start training CSV")
  parser.add_argument("--output", default="data/coldstart_training.csv")
  parser.add_argument("--location", default="NYC_CENTRAL_PARK")
  parser.add_argument("--series", default="KXHIGHNY")
  args = parser.parse_args()

  df = build_coldstart_dataset(args.output, location=args.location, series_ticker=args.series)
  if df.empty:
    print("No rows produced — check that backfill scripts have been run first.")
  else:
    print(f"Wrote {len(df)} rows to {args.output}")
    print(f"  yes_settlement distribution:\n{df['yes_settlement'].value_counts().to_string()}")


if __name__ == "__main__":
  main()
