"""Feature engineering: extract model inputs from ForecastSnapshot objects."""
import math
from datetime import date

from src.weather_data.models import DailyForecast, ForecastSnapshot

# NYC Central Park NOAA 30-year normals (1991-2020): month -> (mean_high_f, std_high_f)
_NYC_NORMALS: dict[int, tuple[float, float]] = {
  1: (39.0, 8.0),  2: (42.0, 9.0),  3: (51.0, 8.0),  4: (62.0, 7.0),
  5: (72.0, 7.0),  6: (80.0, 6.0),  7: (85.0, 6.0),  8: (83.0, 6.0),
  9: (76.0, 6.0), 10: (65.0, 7.0), 11: (53.0, 8.0), 12: (43.0, 9.0),
}

_LOCATION_NORMALS: dict[str, dict[int, tuple[float, float]]] = {
  "NYC_CENTRAL_PARK": _NYC_NORMALS,
}

_NAN = float("nan")


def extract_features(snapshot: ForecastSnapshot, target_date: date) -> dict[str, float]:
  """
  Extract a flat feature dict from a ForecastSnapshot for a specific target date.

  Returns provider-level features (nws_*, ow_*) and a provider_spread.
  The pipeline is responsible for adding lead-time suffixes (_t24, _t12, etc.).
  """
  nws = _find_daily(snapshot.nws_daily, target_date)
  ow = _find_daily(snapshot.ow_daily, target_date)

  nws_high = nws.high_f if nws and nws.high_f is not None else _NAN
  ow_high = ow.high_f if ow and ow.high_f is not None else _NAN
  spread = nws_high - ow_high if not (math.isnan(nws_high) or math.isnan(ow_high)) else _NAN

  return {
    "nws_high_f": nws_high,
    "ow_high_f": ow_high,
    "nws_low_f": nws.low_f if nws and nws.low_f is not None else _NAN,
    "ow_low_f": ow.low_f if ow and ow.low_f is not None else _NAN,
    "nws_precip_prob": nws.precip_prob if nws else _NAN,
    "ow_precip_prob": ow.precip_prob if ow else _NAN,
    "nws_humidity": float(nws.humidity_pct) if nws and nws.humidity_pct is not None else _NAN,
    "ow_humidity": float(ow.humidity_pct) if ow and ow.humidity_pct is not None else _NAN,
    "provider_spread": spread,
  }


def build_seasonal_features(target_date: date) -> dict[str, float]:
  """Return day_of_year and month as floats for the ML model."""
  return {
    "day_of_year": float(target_date.timetuple().tm_yday),
    "month": float(target_date.month),
  }


def compute_climatology(location: str, month: int, day: int) -> tuple[float, float]:
  """
  Return (mean_high_f, std_high_f) for a location + calendar date.

  Uses NOAA 30-year monthly normals. The day parameter is accepted for
  future use when daily-resolution climatology is available.
  """
  normals = _LOCATION_NORMALS.get(location, _NYC_NORMALS)
  return normals.get(month, (65.0, 8.0))


def _find_daily(forecasts: list[DailyForecast], target: date) -> DailyForecast | None:
  return next((f for f in forecasts if f.valid_date == target), None)
