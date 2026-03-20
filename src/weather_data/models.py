"""Pydantic v2 models for weather forecast data."""
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class HourlyForecast(BaseModel):
  valid_time: datetime
  temperature_f: float
  wind_speed_mph: float = 0.0
  precip_prob: float = Field(default=0.0, ge=0.0, le=1.0)
  humidity_pct: Optional[int] = None
  source: str


class DailyForecast(BaseModel):
  valid_date: date
  high_f: Optional[float] = None
  low_f: Optional[float] = None
  precip_prob: float = Field(default=0.0, ge=0.0, le=1.0)
  humidity_pct: Optional[int] = None
  source: str
  fetched_at: datetime


class ForecastSnapshot(BaseModel):
  """Combined NWS + OpenWeather forecasts at a single fetch time."""
  location: str
  fetched_at: datetime
  nws_daily: list[DailyForecast] = Field(default_factory=list)
  nws_hourly: list[HourlyForecast] = Field(default_factory=list)
  ow_daily: list[DailyForecast] = Field(default_factory=list)
  ow_hourly: list[HourlyForecast] = Field(default_factory=list)
