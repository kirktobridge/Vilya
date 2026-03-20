"""Feature engineering: extract model inputs from a ForecastSnapshot."""
# Phase 2/3: implement full bodies
from typing import Any

from src.weather_data.models import ForecastSnapshot


def extract_features(snapshot: ForecastSnapshot, target_date: Any) -> dict[str, float]:
  """
  Build a flat feature dict for the ML model from a ForecastSnapshot.

  Features:
    forecast_high_f_t24, _t12, _t6, _t3    (NWS + OW at multiple lead times)
    forecast_delta_24_12                     (how forecast is evolving)
    provider_spread                          (nws_high - ow_high at T-12)
    precip_prob_t12, humidity_t12
    day_of_year, month                       (seasonality)
    climatological_mean_high, _std_high      (historical avg for date/location)
  """
  raise NotImplementedError


def compute_climatology(location: str, month: int, day: int) -> tuple[float, float]:
  """Return (mean_high_f, std_high_f) for a location/date from historical records."""
  raise NotImplementedError
