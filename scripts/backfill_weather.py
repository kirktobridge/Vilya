"""
Backfill historical weather observations from OpenWeather timemachine.

Usage:
  poetry run python scripts/backfill_weather.py --start 2024-01-01 --end 2024-12-31

Writes actual observed highs/lows into weather_observations.
Rate-limited to ~1 call/sec to stay well within OW free tier (1000/day).
"""
import argparse
import time
from datetime import date, timedelta

from sqlalchemy import text

from src.config import settings
from src.db import get_engine
from src.monitoring.logger import get_logger
from src.weather_data.openweather_client import OWClient

log = get_logger(__name__)

_UPSERT = text("""
  INSERT INTO weather_observations
    (location, obs_date, actual_high_f, actual_low_f, source)
  VALUES
    (:location, :obs_date, :high_f, :low_f, 'openweather')
  ON CONFLICT (location, obs_date) DO UPDATE
    SET actual_high_f = EXCLUDED.actual_high_f,
        actual_low_f  = EXCLUDED.actual_low_f,
        source        = EXCLUDED.source
""")


def _noon_unix(d: date) -> int:
  """Return Unix timestamp for noon UTC of the given date."""
  from datetime import datetime, timezone
  return int(datetime(d.year, d.month, d.day, 12, 0, tzinfo=timezone.utc).timestamp())


def _parse_actual_high_low(data: dict[str, object]) -> tuple[float, float]:
  """Extract daily high and low from a timemachine response."""
  hourly: list[dict[str, object]] = data.get("data", [])  # type: ignore[assignment]
  if not hourly:
    return float("nan"), float("nan")
  temps = [float(h["temp"]) for h in hourly if "temp" in h]  # type: ignore[index]
  return max(temps), min(temps)


def backfill(start: date, end: date) -> None:
  client = OWClient()
  engine = get_engine()
  current = start
  location = settings.target_location

  with engine.begin() as conn:
    while current <= end:
      unix_ts = _noon_unix(current)
      try:
        data = client.fetch_historical(settings.target_lat, settings.target_lon, unix_ts)
        high_f, low_f = _parse_actual_high_low(data)
        conn.execute(_UPSERT, {
          "location": location, "obs_date": current,
          "high_f": high_f, "low_f": low_f,
        })
        log.info("weather_backfill_day", date=str(current), high_f=high_f, low_f=low_f)
      except Exception as exc:
        log.error("weather_backfill_error", date=str(current), error=str(exc))

      current += timedelta(days=1)
      time.sleep(1.1)  # stay under 1 req/sec


def main() -> None:
  parser = argparse.ArgumentParser(description="Backfill weather observations from OW timemachine")
  parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
  parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
  args = parser.parse_args()
  backfill(date.fromisoformat(args.start), date.fromisoformat(args.end))


if __name__ == "__main__":
  main()
