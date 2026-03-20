"""OpenWeather One Call 3.0 client."""
# Phase 1: implement full bodies
from src.config import settings
from src.weather_data.models import DailyForecast, HourlyForecast


class OWClient:
  """Fetch OpenWeather forecasts. Enforces free-tier rate limits."""

  def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
    self._api_key = api_key or settings.openweather_api_key
    self._base_url = base_url or settings.openweather_base_url

  def one_call(self, lat: float, lon: float) -> dict[str, object]:
    """Fetch current + 48h hourly + 8-day daily forecast."""
    raise NotImplementedError

  def fetch_daily_forecast(self, lat: float, lon: float) -> list[DailyForecast]:
    """Return 8-day daily forecasts parsed from One Call 3.0."""
    raise NotImplementedError

  def fetch_hourly_forecast(self, lat: float, lon: float) -> list[HourlyForecast]:
    """Return 48-hour hourly forecasts parsed from One Call 3.0."""
    raise NotImplementedError

  def fetch_historical(self, lat: float, lon: float, unix_ts: int) -> dict[str, object]:
    """Fetch historical weather for a specific timestamp."""
    raise NotImplementedError
