"""NWS (api.weather.gov) client with ETag caching."""
# Phase 1: implement full bodies
from src.config import settings
from src.weather_data.models import DailyForecast, HourlyForecast


class NWSClient:
  """Fetch NWS grid forecasts. Respects ETag to avoid redundant payloads."""

  def __init__(self, base_url: str | None = None) -> None:
    self._base_url = base_url or settings.nws_base_url
    self._etags: dict[str, str] = {}  # url -> last ETag

  def resolve_gridpoint(self, lat: float, lon: float) -> dict[str, str]:
    """Resolve lat/lon to NWS gridpoint URLs."""
    raise NotImplementedError

  def fetch_daily_forecast(self, lat: float, lon: float) -> list[DailyForecast]:
    """Return 7-day daily (period) forecasts for location."""
    raise NotImplementedError

  def fetch_hourly_forecast(self, lat: float, lon: float) -> list[HourlyForecast]:
    """Return 7-day hourly forecasts for location."""
    raise NotImplementedError
