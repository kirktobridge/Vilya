"""Tests for features.engineering — pure feature extraction functions."""
import math
from datetime import date, datetime, timezone

import pytest

from src.features.engineering import (
  build_seasonal_features,
  compute_climatology,
  extract_features,
)
from src.weather_data.models import DailyForecast, ForecastSnapshot

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FETCHED_AT = datetime(2024, 6, 11, 12, 0, tzinfo=timezone.utc)
TARGET_DATE = date(2024, 6, 12)


def _daily(source: str, high: float, low: float, precip: float = 0.1, humidity: int = 60) -> DailyForecast:
  return DailyForecast(
    valid_date=TARGET_DATE,
    high_f=high,
    low_f=low,
    precip_prob=precip,
    humidity_pct=humidity,
    source=source,
    fetched_at=FETCHED_AT,
  )


def _snapshot(nws_high: float = 88.0, ow_high: float = 86.0) -> ForecastSnapshot:
  return ForecastSnapshot(
    location="NYC_CENTRAL_PARK",
    fetched_at=FETCHED_AT,
    nws_daily=[_daily("nws", nws_high, 70.0)],
    ow_daily=[_daily("openweather", ow_high, 68.0)],
  )


# ---------------------------------------------------------------------------
# extract_features
# ---------------------------------------------------------------------------

class TestExtractFeatures:
  def test_nws_high_returned(self) -> None:
    f = extract_features(_snapshot(nws_high=88.0), TARGET_DATE)
    assert f["nws_high_f"] == pytest.approx(88.0)

  def test_ow_high_returned(self) -> None:
    f = extract_features(_snapshot(ow_high=86.0), TARGET_DATE)
    assert f["ow_high_f"] == pytest.approx(86.0)

  def test_provider_spread_is_nws_minus_ow(self) -> None:
    f = extract_features(_snapshot(nws_high=88.0, ow_high=86.0), TARGET_DATE)
    assert f["provider_spread"] == pytest.approx(2.0)

  def test_precip_prob_from_nws(self) -> None:
    f = extract_features(_snapshot(), TARGET_DATE)
    assert f["nws_precip_prob"] == pytest.approx(0.1)

  def test_humidity_from_nws(self) -> None:
    f = extract_features(_snapshot(), TARGET_DATE)
    assert f["nws_humidity"] == pytest.approx(60.0)

  def test_missing_nws_daily_returns_nan(self) -> None:
    snapshot = ForecastSnapshot(
      location="NYC_CENTRAL_PARK",
      fetched_at=FETCHED_AT,
      nws_daily=[],
      ow_daily=[_daily("openweather", 86.0, 68.0)],
    )
    f = extract_features(snapshot, TARGET_DATE)
    assert math.isnan(f["nws_high_f"])
    assert math.isnan(f["provider_spread"])

  def test_missing_ow_daily_returns_nan(self) -> None:
    snapshot = ForecastSnapshot(
      location="NYC_CENTRAL_PARK",
      fetched_at=FETCHED_AT,
      nws_daily=[_daily("nws", 88.0, 70.0)],
      ow_daily=[],
    )
    f = extract_features(snapshot, TARGET_DATE)
    assert math.isnan(f["ow_high_f"])
    assert math.isnan(f["provider_spread"])

  def test_wrong_target_date_returns_nan(self) -> None:
    wrong_date = date(2024, 6, 20)
    f = extract_features(_snapshot(), wrong_date)
    assert math.isnan(f["nws_high_f"])
    assert math.isnan(f["ow_high_f"])

  def test_none_high_f_returns_nan(self) -> None:
    nws = DailyForecast(
      valid_date=TARGET_DATE, high_f=None, precip_prob=0.0, source="nws", fetched_at=FETCHED_AT
    )
    snapshot = ForecastSnapshot(
      location="NYC_CENTRAL_PARK", fetched_at=FETCHED_AT, nws_daily=[nws], ow_daily=[]
    )
    f = extract_features(snapshot, TARGET_DATE)
    assert math.isnan(f["nws_high_f"])


# ---------------------------------------------------------------------------
# build_seasonal_features
# ---------------------------------------------------------------------------

class TestBuildSeasonalFeatures:
  def test_day_of_year_june_12(self) -> None:
    f = build_seasonal_features(date(2024, 6, 12))
    assert f["day_of_year"] == pytest.approx(164.0)

  def test_month_june(self) -> None:
    f = build_seasonal_features(date(2024, 6, 12))
    assert f["month"] == pytest.approx(6.0)

  def test_jan_1_is_day_1(self) -> None:
    f = build_seasonal_features(date(2024, 1, 1))
    assert f["day_of_year"] == pytest.approx(1.0)

  def test_dec_31_is_day_366_in_leap_year(self) -> None:
    f = build_seasonal_features(date(2024, 12, 31))
    assert f["day_of_year"] == pytest.approx(366.0)


# ---------------------------------------------------------------------------
# compute_climatology
# ---------------------------------------------------------------------------

class TestComputeClimatology:
  def test_nyc_july_mean_high(self) -> None:
    mean, std = compute_climatology("NYC_CENTRAL_PARK", 7, 4)
    assert mean == pytest.approx(85.0)
    assert std == pytest.approx(6.0)

  def test_nyc_january_mean_high(self) -> None:
    mean, std = compute_climatology("NYC_CENTRAL_PARK", 1, 15)
    assert mean == pytest.approx(39.0)

  def test_unknown_location_returns_default(self) -> None:
    mean, std = compute_climatology("UNKNOWN_CITY", 6, 15)
    assert mean == pytest.approx(80.0)  # June normals fall back to NYC

  def test_returns_tuple_of_two_floats(self) -> None:
    result = compute_climatology("NYC_CENTRAL_PARK", 6, 12)
    assert isinstance(result, tuple)
    assert len(result) == 2
