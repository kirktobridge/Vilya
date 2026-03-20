"""NWS (api.weather.gov) client with ETag caching."""
import re
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

import requests

from src.config import settings
from src.monitoring.logger import get_logger
from src.weather_data.models import DailyForecast, HourlyForecast

log = get_logger(__name__)

_USER_AGENT = "kalshi-weather-bot/0.1 (contact: bot@example.com)"
_MAX_RETRIES = 4
_BACKOFF_BASE = 2.0  # seconds


class NWSError(Exception):
  def __init__(self, status_code: int, url: str) -> None:
    super().__init__(f"NWS HTTP {status_code} for {url}")
    self.status_code = status_code


class NWSClient:
  """Fetch NWS grid forecasts. Respects ETag to avoid redundant payloads."""

  def __init__(self, base_url: str | None = None) -> None:
    self._base_url = base_url or settings.nws_base_url
    self._etags: dict[str, str] = {}        # url -> last ETag value
    self._cache: dict[str, Any] = {}         # url -> last successful payload
    self._gridpoints: dict[str, dict[str, str]] = {}  # "lat,lon" -> url dict
    self._session = requests.Session()
    self._session.headers.update({"User-Agent": _USER_AGENT, "Accept": "application/geo+json"})

  # ------------------------------------------------------------------
  # Public API
  # ------------------------------------------------------------------

  def resolve_gridpoint(self, lat: float, lon: float) -> dict[str, str]:
    """
    Resolve lat/lon to NWS gridpoint forecast URLs.

    Returns a dict with keys: forecast, forecastHourly, forecastGridData.
    Result is cached in-process (gridpoints never change for a given lat/lon).
    """
    key = f"{lat},{lon}"
    if key in self._gridpoints:
      return self._gridpoints[key]

    url = f"{self._base_url}/points/{lat},{lon}"
    data = self._get(url, use_etag=False)
    props = data["properties"]
    urls = {
      "forecast": props["forecast"],
      "forecastHourly": props["forecastHourly"],
      "forecastGridData": props["forecastGridData"],
    }
    self._gridpoints[key] = urls
    log.info("nws_gridpoint_resolved", lat=lat, lon=lon, forecast_url=urls["forecast"])
    return urls

  def fetch_daily_forecast(self, lat: float, lon: float) -> list[DailyForecast]:
    """
    Return up to 7-day daily forecasts for a location.

    NWS periods are 12-hour blocks (day / night). This method pairs them by
    date: daytime temp -> high_f, nighttime temp -> low_f.
    Uses ETag caching so repeated calls within a 10-min window cost 0 bytes.
    """
    urls = self.resolve_gridpoint(lat, lon)
    data = self._get(urls["forecast"], use_etag=True)
    fetched_at = datetime.now(tz=timezone.utc)
    periods: list[dict[str, Any]] = data["properties"]["periods"]
    return _parse_daily_periods(periods, fetched_at)

  def fetch_hourly_forecast(self, lat: float, lon: float) -> list[HourlyForecast]:
    """
    Return up to 7-day hourly forecasts for a location.

    Uses ETag caching; returns cached data on HTTP 304.
    """
    urls = self.resolve_gridpoint(lat, lon)
    data = self._get(urls["forecastHourly"], use_etag=True)
    periods: list[dict[str, Any]] = data["properties"]["periods"]
    return [_parse_hourly_period(p) for p in periods]

  # ------------------------------------------------------------------
  # Internal HTTP helpers
  # ------------------------------------------------------------------

  def _get(self, url: str, *, use_etag: bool) -> Any:
    headers: dict[str, str] = {}
    if use_etag and url in self._etags:
      headers["If-None-Match"] = self._etags[url]

    for attempt in range(_MAX_RETRIES):
      resp = self._session.get(url, headers=headers, timeout=15)

      if resp.status_code == 304:
        log.debug("nws_cache_hit", url=url)
        return self._cache[url]

      if resp.status_code in {429, 500, 502, 503, 504} and attempt < _MAX_RETRIES - 1:
        wait = _BACKOFF_BASE ** attempt
        log.warning("nws_retry", status=resp.status_code, attempt=attempt, wait=wait, url=url)
        time.sleep(wait)
        continue

      if not resp.ok:
        raise NWSError(resp.status_code, url)

      payload = resp.json()
      if use_etag and "ETag" in resp.headers:
        self._etags[url] = resp.headers["ETag"]
        self._cache[url] = payload

      return payload

    raise NWSError(0, f"max retries exceeded for {url}")


# ------------------------------------------------------------------
# Parsing helpers (module-level, pure functions, easy to unit test)
# ------------------------------------------------------------------

def _parse_daily_periods(
  periods: list[dict[str, Any]],
  fetched_at: datetime,
) -> list[DailyForecast]:
  """
  Pair NWS 12-hour periods into daily (high + low) DailyForecast objects.

  Day periods supply high_f; night periods supply low_f.
  Periods for the same date are merged into one record.
  """
  by_date: dict[date, dict[str, Any]] = defaultdict(dict)

  for period in periods:
    dt = datetime.fromisoformat(period["startTime"])
    d = dt.date()
    temp_f = float(period["temperature"])
    precip = _extract_percent(period.get("probabilityOfPrecipitation")) / 100.0
    humidity = _extract_percent(period.get("relativeHumidity"))

    if period.get("isDaytime", True):
      by_date[d]["high_f"] = temp_f
      by_date[d]["precip_prob"] = precip
      by_date[d]["humidity_pct"] = humidity
    else:
      by_date[d]["low_f"] = temp_f
      if "precip_prob" not in by_date[d]:
        by_date[d]["precip_prob"] = precip

  result: list[DailyForecast] = []
  for d in sorted(by_date):
    row = by_date[d]
    result.append(DailyForecast(
      valid_date=d,
      high_f=row.get("high_f"),
      low_f=row.get("low_f"),
      precip_prob=row.get("precip_prob", 0.0),
      humidity_pct=row.get("humidity_pct"),
      source="nws",
      fetched_at=fetched_at,
    ))
  return result


def _parse_hourly_period(period: dict[str, Any]) -> HourlyForecast:
  return HourlyForecast(
    valid_time=datetime.fromisoformat(period["startTime"]),
    temperature_f=float(period["temperature"]),
    wind_speed_mph=_parse_wind_speed(period.get("windSpeed", "0 mph")),
    precip_prob=_extract_percent(period.get("probabilityOfPrecipitation")) / 100.0,
    humidity_pct=_extract_percent(period.get("relativeHumidity")) or None,
    source="nws",
  )


def _extract_percent(field: dict[str, Any] | None) -> int:
  """Extract integer percent from NWS quantitative value object, defaulting to 0."""
  if field is None:
    return 0
  value = field.get("value")
  return int(value) if value is not None else 0


def _parse_wind_speed(wind_str: str) -> float:
  """Parse NWS wind speed string like '10 mph' or '5 to 15 mph' -> mph float."""
  numbers = re.findall(r"\d+", wind_str)
  if not numbers:
    return 0.0
  values = [float(n) for n in numbers]
  return sum(values) / len(values)  # average for ranges like "5 to 15 mph"
