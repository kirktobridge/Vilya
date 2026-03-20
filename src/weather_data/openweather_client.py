"""OpenWeather One Call 3.0 client with retry logic."""
import time
from datetime import datetime, timezone
from typing import Any

import requests

from src.config import settings
from src.monitoring.logger import get_logger
from src.weather_data.models import DailyForecast, HourlyForecast

log = get_logger(__name__)

_MAX_RETRIES = 4
_BACKOFF_BASE = 2.0
_RETRY_CODES = {429, 500, 502, 503, 504}


class OWError(Exception):
  def __init__(self, status_code: int, url: str) -> None:
    super().__init__(f"OpenWeather HTTP {status_code} for {url}")
    self.status_code = status_code


class OWClient:
  """Fetch OpenWeather One Call 3.0 forecasts and historical data."""

  def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
    self._api_key = api_key or settings.openweather_api_key
    self._base_url = base_url or settings.openweather_base_url
    self._session = requests.Session()

  def one_call(self, lat: float, lon: float) -> dict[str, Any]:
    """Fetch current + 48h hourly + 8-day daily forecast (imperial units)."""
    return self._get(f"{self._base_url}/onecall", {"lat": lat, "lon": lon, "units": "imperial"})

  def fetch_daily_forecast(self, lat: float, lon: float) -> list[DailyForecast]:
    """Return up to 8-day daily forecasts parsed from One Call 3.0."""
    data = self.one_call(lat, lon)
    fetched_at = datetime.now(tz=timezone.utc)
    return [_parse_daily(d, fetched_at) for d in data.get("daily", [])]

  def fetch_hourly_forecast(self, lat: float, lon: float) -> list[HourlyForecast]:
    """Return 48-hour hourly forecasts parsed from One Call 3.0."""
    data = self.one_call(lat, lon)
    return [_parse_hourly(h) for h in data.get("hourly", [])]

  def fetch_historical(self, lat: float, lon: float, unix_ts: int) -> dict[str, Any]:
    """
    Fetch historical weather for a specific day.

    unix_ts should be a Unix timestamp for noon (local) of the target day.
    Returns the raw One Call Timemachine response.
    """
    return self._get(
      f"{self._base_url}/onecall/timemachine",
      {"lat": lat, "lon": lon, "dt": unix_ts, "units": "imperial"},
    )

  def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
    all_params: dict[str, Any] = {**params, "appid": self._api_key}
    for attempt in range(_MAX_RETRIES):
      resp = self._session.get(url, params=all_params, timeout=15)
      if resp.status_code in _RETRY_CODES and attempt < _MAX_RETRIES - 1:
        wait = _BACKOFF_BASE ** attempt
        log.warning("ow_retry", status=resp.status_code, attempt=attempt, wait=wait)
        time.sleep(wait)
        continue
      if not resp.ok:
        raise OWError(resp.status_code, url)
      return resp.json()  # type: ignore[no-any-return]
    raise OWError(0, f"max retries exceeded for {url}")


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_daily(period: dict[str, Any], fetched_at: datetime) -> DailyForecast:
  temp = period.get("temp", {})
  return DailyForecast(
    valid_date=datetime.fromtimestamp(period["dt"], tz=timezone.utc).date(),
    high_f=float(temp.get("max", temp.get("day", 0.0))),
    low_f=float(temp.get("min", 0.0)),
    precip_prob=float(period.get("pop", 0.0)),
    humidity_pct=int(period["humidity"]) if "humidity" in period else None,
    source="openweather",
    fetched_at=fetched_at,
  )


def _parse_hourly(period: dict[str, Any]) -> HourlyForecast:
  return HourlyForecast(
    valid_time=datetime.fromtimestamp(period["dt"], tz=timezone.utc),
    temperature_f=float(period["temp"]),
    wind_speed_mph=float(period.get("wind_speed", 0.0)),
    precip_prob=float(period.get("pop", 0.0)),
    humidity_pct=int(period["humidity"]) if "humidity" in period else None,
    source="openweather",
  )
