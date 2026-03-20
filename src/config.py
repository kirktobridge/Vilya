from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
  model_config = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    case_sensitive=False,
  )

  # API credentials
  kalshi_api_key: str = Field(..., description="Kalshi bearer token")
  openweather_api_key: str = Field(..., description="OpenWeather One Call 3.0 key")

  # Database
  database_url: str = Field(..., description="SQLAlchemy connection string")

  # Runtime
  env: str = Field(default="dev", description="dev | staging | prod")
  log_level: str = Field(default="INFO", description="DEBUG | INFO | WARNING | ERROR")

  # Target location
  target_location: str = Field(default="NYC_CENTRAL_PARK")
  target_lat: float = Field(default=40.7828)
  target_lon: float = Field(default=-73.9654)

  # Trading controls
  paper_trading: bool = Field(default=True, description="Log trades without submitting")
  ev_threshold: float = Field(default=0.03, description="Minimum edge to trade")
  max_contracts_per_market: int = Field(default=5)
  max_daily_notional: float = Field(default=500.0, description="USD cap per calendar day")
  drawdown_kill_switch: float = Field(default=100.0, description="USD intraday drawdown halt")
  poll_interval_seconds: int = Field(default=600, description="Daemon poll interval")

  # Kalshi API
  kalshi_base_url: str = Field(default="https://trading-api.kalshi.com/trade-api/v2")

  # Weather API
  nws_base_url: str = Field(default="https://api.weather.gov")
  openweather_base_url: str = Field(default="https://api.openweathermap.org/data/3.0")


# Singleton — import this everywhere
settings = Settings()  # type: ignore[call-arg]
