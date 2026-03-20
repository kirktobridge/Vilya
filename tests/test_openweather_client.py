"""Tests for weather_data.openweather_client."""
import time
import unittest.mock as mock
from datetime import date, datetime, timezone

import pytest
import responses as resp_lib

from src.weather_data.openweather_client import OWClient, OWError, _parse_daily, _parse_hourly

OW_BASE = "https://api.openweathermap.org/data/3.0"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DAILY_PERIOD = {
  "dt": 1718150400,  # 2024-06-12 00:00 UTC
  "temp": {"day": 85.2, "min": 70.1, "max": 90.3, "night": 72.5, "eve": 80.0, "morn": 68.0},
  "humidity": 65,
  "pop": 0.20,
}

HOURLY_PERIOD = {
  "dt": 1718193600,  # 2024-06-12 12:00 UTC
  "temp": 87.0,
  "wind_speed": 9.0,
  "humidity": 60,
  "pop": 0.10,
}

ONE_CALL_RESPONSE = {
  "lat": 40.7828, "lon": -73.9654,
  "daily": [DAILY_PERIOD],
  "hourly": [HOURLY_PERIOD],
}

TIMEMACHINE_RESPONSE = {
  "lat": 40.7828, "lon": -73.9654,
  "data": [
    {"dt": 1718150400, "temp": 88.0, "humidity": 62, "wind_speed": 7.0},
    {"dt": 1718154000, "temp": 90.0, "humidity": 60, "wind_speed": 8.0},
    {"dt": 1718157600, "temp": 85.0, "humidity": 65, "wind_speed": 6.0},
  ],
}


def _make_client() -> OWClient:
  return OWClient(api_key="test-key", base_url=OW_BASE)


# ---------------------------------------------------------------------------
# Unit tests — pure parsing helpers
# ---------------------------------------------------------------------------

class TestParseDailyPeriod:
  def test_extracts_max_temp_as_high(self) -> None:
    fetched_at = datetime(2024, 6, 11, 12, 0, tzinfo=timezone.utc)
    df = _parse_daily(DAILY_PERIOD, fetched_at)
    assert df.high_f == pytest.approx(90.3)

  def test_extracts_min_temp_as_low(self) -> None:
    fetched_at = datetime(2024, 6, 11, 12, 0, tzinfo=timezone.utc)
    df = _parse_daily(DAILY_PERIOD, fetched_at)
    assert df.low_f == pytest.approx(70.1)

  def test_valid_date_from_unix_timestamp(self) -> None:
    fetched_at = datetime(2024, 6, 11, 12, 0, tzinfo=timezone.utc)
    df = _parse_daily(DAILY_PERIOD, fetched_at)
    assert df.valid_date == date(2024, 6, 12)

  def test_precip_prob_parsed(self) -> None:
    fetched_at = datetime(2024, 6, 11, 12, 0, tzinfo=timezone.utc)
    df = _parse_daily(DAILY_PERIOD, fetched_at)
    assert df.precip_prob == pytest.approx(0.20)

  def test_humidity_parsed(self) -> None:
    fetched_at = datetime(2024, 6, 11, 12, 0, tzinfo=timezone.utc)
    df = _parse_daily(DAILY_PERIOD, fetched_at)
    assert df.humidity_pct == 65

  def test_source_is_openweather(self) -> None:
    fetched_at = datetime(2024, 6, 11, 12, 0, tzinfo=timezone.utc)
    df = _parse_daily(DAILY_PERIOD, fetched_at)
    assert df.source == "openweather"

  def test_missing_humidity_is_none(self) -> None:
    period = {**DAILY_PERIOD}
    period.pop("humidity")
    fetched_at = datetime(2024, 6, 11, 12, 0, tzinfo=timezone.utc)
    df = _parse_daily(period, fetched_at)
    assert df.humidity_pct is None

  def test_falls_back_to_day_temp_when_no_max(self) -> None:
    period = {**DAILY_PERIOD, "temp": {"day": 85.0, "min": 70.0, "night": 72.0}}
    fetched_at = datetime(2024, 6, 11, 12, 0, tzinfo=timezone.utc)
    df = _parse_daily(period, fetched_at)
    assert df.high_f == pytest.approx(85.0)


class TestParseHourlyPeriod:
  def test_temperature_parsed(self) -> None:
    h = _parse_hourly(HOURLY_PERIOD)
    assert h.temperature_f == pytest.approx(87.0)

  def test_wind_speed_parsed(self) -> None:
    h = _parse_hourly(HOURLY_PERIOD)
    assert h.wind_speed_mph == pytest.approx(9.0)

  def test_source_is_openweather(self) -> None:
    h = _parse_hourly(HOURLY_PERIOD)
    assert h.source == "openweather"

  def test_missing_wind_defaults_to_zero(self) -> None:
    period = {k: v for k, v in HOURLY_PERIOD.items() if k != "wind_speed"}
    h = _parse_hourly(period)
    assert h.wind_speed_mph == 0.0


# ---------------------------------------------------------------------------
# Integration tests — OWClient with mocked HTTP
# ---------------------------------------------------------------------------

class TestOWClientInstantiation:
  def test_custom_base_url(self) -> None:
    client = OWClient(api_key="key", base_url="http://localhost:8080")
    assert client._base_url == "http://localhost:8080"


class TestOneCall:
  @resp_lib.activate
  def test_returns_raw_dict(self) -> None:
    resp_lib.add(resp_lib.GET, f"{OW_BASE}/onecall", json=ONE_CALL_RESPONSE)
    data = _make_client().one_call(40.7828, -73.9654)
    assert "daily" in data
    assert "hourly" in data

  @resp_lib.activate
  def test_api_key_sent_as_appid(self) -> None:
    resp_lib.add(resp_lib.GET, f"{OW_BASE}/onecall", json=ONE_CALL_RESPONSE)
    _make_client().one_call(40.7828, -73.9654)
    assert "appid=test-key" in resp_lib.calls[0].request.url

  @resp_lib.activate
  def test_units_imperial(self) -> None:
    resp_lib.add(resp_lib.GET, f"{OW_BASE}/onecall", json=ONE_CALL_RESPONSE)
    _make_client().one_call(40.7828, -73.9654)
    assert "units=imperial" in resp_lib.calls[0].request.url

  @resp_lib.activate
  def test_raises_ow_error_on_401(self) -> None:
    resp_lib.add(resp_lib.GET, f"{OW_BASE}/onecall", json={}, status=401)
    with pytest.raises(OWError) as exc_info:
      _make_client().one_call(40.7828, -73.9654)
    assert exc_info.value.status_code == 401


class TestFetchDailyForecast:
  @resp_lib.activate
  def test_returns_daily_list(self) -> None:
    resp_lib.add(resp_lib.GET, f"{OW_BASE}/onecall", json=ONE_CALL_RESPONSE)
    days = _make_client().fetch_daily_forecast(40.7828, -73.9654)
    assert len(days) == 1
    assert days[0].high_f == pytest.approx(90.3)

  @resp_lib.activate
  def test_empty_daily_returns_empty_list(self) -> None:
    resp_lib.add(resp_lib.GET, f"{OW_BASE}/onecall", json={"daily": [], "hourly": []})
    assert _make_client().fetch_daily_forecast(40.7828, -73.9654) == []


class TestFetchHourlyForecast:
  @resp_lib.activate
  def test_returns_hourly_list(self) -> None:
    resp_lib.add(resp_lib.GET, f"{OW_BASE}/onecall", json=ONE_CALL_RESPONSE)
    hours = _make_client().fetch_hourly_forecast(40.7828, -73.9654)
    assert len(hours) == 1
    assert hours[0].temperature_f == pytest.approx(87.0)


class TestFetchHistorical:
  @resp_lib.activate
  def test_returns_raw_dict(self) -> None:
    resp_lib.add(resp_lib.GET, f"{OW_BASE}/onecall/timemachine", json=TIMEMACHINE_RESPONSE)
    data = _make_client().fetch_historical(40.7828, -73.9654, 1718150400)
    assert "data" in data
    assert len(data["data"]) == 3

  @resp_lib.activate
  def test_dt_param_sent(self) -> None:
    resp_lib.add(resp_lib.GET, f"{OW_BASE}/onecall/timemachine", json=TIMEMACHINE_RESPONSE)
    _make_client().fetch_historical(40.7828, -73.9654, 1718150400)
    assert "dt=1718150400" in resp_lib.calls[0].request.url


class TestRetryBehavior:
  @resp_lib.activate
  def test_retries_on_429_then_succeeds(self) -> None:
    resp_lib.add(resp_lib.GET, f"{OW_BASE}/onecall", json={}, status=429)
    resp_lib.add(resp_lib.GET, f"{OW_BASE}/onecall", json=ONE_CALL_RESPONSE, status=200)
    with mock.patch("time.sleep"):
      data = _make_client().one_call(40.7828, -73.9654)
    assert "daily" in data

  @resp_lib.activate
  def test_raises_after_max_retries(self) -> None:
    for _ in range(4):
      resp_lib.add(resp_lib.GET, f"{OW_BASE}/onecall", json={}, status=500)
    with mock.patch("time.sleep"), pytest.raises(OWError):
      _make_client().one_call(40.7828, -73.9654)
