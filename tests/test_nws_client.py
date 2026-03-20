"""Tests for weather_data.nws_client."""
from datetime import date, datetime, timezone

import pytest
import responses as resp_lib

from src.weather_data.nws_client import (
  NWSClient,
  NWSError,
  _extract_percent,
  _parse_daily_periods,
  _parse_wind_speed,
)

NWS_BASE = "https://api.weather.gov"

# ------------------------------------------------------------------
# Fixtures / helpers
# ------------------------------------------------------------------

POINTS_RESPONSE = {
  "properties": {
    "forecast": f"{NWS_BASE}/gridpoints/OKX/33,37/forecast",
    "forecastHourly": f"{NWS_BASE}/gridpoints/OKX/33,37/forecast/hourly",
    "forecastGridData": f"{NWS_BASE}/gridpoints/OKX/33,37",
  }
}

FORECAST_RESPONSE = {
  "properties": {
    "periods": [
      {
        "number": 1,
        "name": "Today",
        "startTime": "2024-06-12T06:00:00-04:00",
        "endTime": "2024-06-12T18:00:00-04:00",
        "isDaytime": True,
        "temperature": 88,
        "temperatureUnit": "F",
        "windSpeed": "10 mph",
        "windDirection": "SW",
        "probabilityOfPrecipitation": {"unitCode": "wmoUnit:percent", "value": 20},
        "relativeHumidity": {"unitCode": "wmoUnit:percent", "value": 65},
        "shortForecast": "Partly Sunny",
        "detailedForecast": "",
      },
      {
        "number": 2,
        "name": "Tonight",
        "startTime": "2024-06-12T18:00:00-04:00",
        "endTime": "2024-06-13T06:00:00-04:00",
        "isDaytime": False,
        "temperature": 72,
        "temperatureUnit": "F",
        "windSpeed": "5 mph",
        "windDirection": "S",
        "probabilityOfPrecipitation": {"unitCode": "wmoUnit:percent", "value": 10},
        "relativeHumidity": {"unitCode": "wmoUnit:percent", "value": 80},
        "shortForecast": "Mostly Clear",
        "detailedForecast": "",
      },
      {
        "number": 3,
        "name": "Thursday",
        "startTime": "2024-06-13T06:00:00-04:00",
        "endTime": "2024-06-13T18:00:00-04:00",
        "isDaytime": True,
        "temperature": 91,
        "temperatureUnit": "F",
        "windSpeed": "5 to 10 mph",
        "windDirection": "SW",
        "probabilityOfPrecipitation": {"unitCode": "wmoUnit:percent", "value": 0},
        "relativeHumidity": {"unitCode": "wmoUnit:percent", "value": 55},
        "shortForecast": "Sunny",
        "detailedForecast": "",
      },
    ]
  }
}

HOURLY_RESPONSE = {
  "properties": {
    "periods": [
      {
        "number": 1,
        "startTime": "2024-06-12T12:00:00-04:00",
        "endTime": "2024-06-12T13:00:00-04:00",
        "isDaytime": True,
        "temperature": 85,
        "temperatureUnit": "F",
        "windSpeed": "8 mph",
        "windDirection": "SW",
        "probabilityOfPrecipitation": {"unitCode": "wmoUnit:percent", "value": 15},
        "relativeHumidity": {"unitCode": "wmoUnit:percent", "value": 60},
        "shortForecast": "Partly Cloudy",
        "detailedForecast": "",
      },
      {
        "number": 2,
        "startTime": "2024-06-12T13:00:00-04:00",
        "endTime": "2024-06-12T14:00:00-04:00",
        "isDaytime": True,
        "temperature": 87,
        "temperatureUnit": "F",
        "windSpeed": "10 to 15 mph",
        "windDirection": "S",
        "probabilityOfPrecipitation": {"unitCode": "wmoUnit:percent", "value": None},
        "relativeHumidity": {"unitCode": "wmoUnit:percent", "value": None},
        "shortForecast": "Mostly Sunny",
        "detailedForecast": "",
      },
    ]
  }
}


def _register_standard_mocks(rsps: resp_lib.RequestsMock) -> None:
  rsps.add(resp_lib.GET, f"{NWS_BASE}/points/40.7828,-73.9654", json=POINTS_RESPONSE, status=200)
  rsps.add(
    resp_lib.GET,
    f"{NWS_BASE}/gridpoints/OKX/33,37/forecast",
    json=FORECAST_RESPONSE,
    status=200,
    headers={"ETag": '"abc123"'},
  )
  rsps.add(
    resp_lib.GET,
    f"{NWS_BASE}/gridpoints/OKX/33,37/forecast/hourly",
    json=HOURLY_RESPONSE,
    status=200,
    headers={"ETag": '"xyz789"'},
  )


# ------------------------------------------------------------------
# Unit tests — pure parsing helpers
# ------------------------------------------------------------------

class TestParseWindSpeed:
  def test_simple_speed(self) -> None:
    assert _parse_wind_speed("10 mph") == 10.0

  def test_range_averages(self) -> None:
    assert _parse_wind_speed("5 to 15 mph") == 10.0

  def test_zero_fallback(self) -> None:
    assert _parse_wind_speed("Calm") == 0.0

  def test_single_digit(self) -> None:
    assert _parse_wind_speed("7 mph") == 7.0


class TestExtractPercent:
  def test_normal_value(self) -> None:
    assert _extract_percent({"value": 42}) == 42

  def test_none_value(self) -> None:
    assert _extract_percent({"value": None}) == 0

  def test_missing_field(self) -> None:
    assert _extract_percent(None) == 0


class TestParseDailyPeriods:
  def setup_method(self) -> None:
    self._fetched_at = datetime(2024, 6, 12, 10, 0, tzinfo=timezone.utc)

  def test_pairs_day_night_into_one_record(self) -> None:
    days = _parse_daily_periods(FORECAST_RESPONSE["properties"]["periods"], self._fetched_at)
    jun_12 = next(d for d in days if d.valid_date == date(2024, 6, 12))
    assert jun_12.high_f == 88.0
    assert jun_12.low_f == 72.0

  def test_day_period_populates_high(self) -> None:
    days = _parse_daily_periods(FORECAST_RESPONSE["properties"]["periods"], self._fetched_at)
    jun_13 = next(d for d in days if d.valid_date == date(2024, 6, 13))
    assert jun_13.high_f == 91.0
    assert jun_13.low_f is None  # no night period in fixture

  def test_precip_from_day_period(self) -> None:
    days = _parse_daily_periods(FORECAST_RESPONSE["properties"]["periods"], self._fetched_at)
    jun_12 = next(d for d in days if d.valid_date == date(2024, 6, 12))
    assert jun_12.precip_prob == pytest.approx(0.20)

  def test_humidity_from_day_period(self) -> None:
    days = _parse_daily_periods(FORECAST_RESPONSE["properties"]["periods"], self._fetched_at)
    jun_12 = next(d for d in days if d.valid_date == date(2024, 6, 12))
    assert jun_12.humidity_pct == 65

  def test_sorted_ascending_by_date(self) -> None:
    days = _parse_daily_periods(FORECAST_RESPONSE["properties"]["periods"], self._fetched_at)
    dates = [d.valid_date for d in days]
    assert dates == sorted(dates)

  def test_source_is_nws(self) -> None:
    days = _parse_daily_periods(FORECAST_RESPONSE["properties"]["periods"], self._fetched_at)
    assert all(d.source == "nws" for d in days)

  def test_fetched_at_propagated(self) -> None:
    days = _parse_daily_periods(FORECAST_RESPONSE["properties"]["periods"], self._fetched_at)
    assert all(d.fetched_at == self._fetched_at for d in days)


# ------------------------------------------------------------------
# Integration tests — NWSClient with mocked HTTP
# ------------------------------------------------------------------

class TestNWSClientInstantiation:
  def test_default_base_url(self) -> None:
    client = NWSClient()
    assert client._base_url == NWS_BASE

  def test_custom_base_url(self) -> None:
    client = NWSClient(base_url="http://localhost:8080")
    assert client._base_url == "http://localhost:8080"


class TestResolveGridpoint:
  @resp_lib.activate
  def test_returns_forecast_urls(self) -> None:
    resp_lib.add(resp_lib.GET, f"{NWS_BASE}/points/40.7828,-73.9654", json=POINTS_RESPONSE)
    client = NWSClient(base_url=NWS_BASE)
    urls = client.resolve_gridpoint(40.7828, -73.9654)
    assert urls["forecast"] == f"{NWS_BASE}/gridpoints/OKX/33,37/forecast"
    assert urls["forecastHourly"] == f"{NWS_BASE}/gridpoints/OKX/33,37/forecast/hourly"

  @resp_lib.activate
  def test_caches_gridpoint_in_process(self) -> None:
    resp_lib.add(resp_lib.GET, f"{NWS_BASE}/points/40.7828,-73.9654", json=POINTS_RESPONSE)
    client = NWSClient(base_url=NWS_BASE)
    client.resolve_gridpoint(40.7828, -73.9654)
    client.resolve_gridpoint(40.7828, -73.9654)  # second call must not hit network
    assert len(resp_lib.calls) == 1

  @resp_lib.activate
  def test_raises_nws_error_on_404(self) -> None:
    resp_lib.add(resp_lib.GET, f"{NWS_BASE}/points/0.0,0.0", json={}, status=404)
    client = NWSClient(base_url=NWS_BASE)
    with pytest.raises(NWSError) as exc_info:
      client.resolve_gridpoint(0.0, 0.0)
    assert exc_info.value.status_code == 404


class TestFetchDailyForecast:
  @resp_lib.activate
  def test_returns_daily_forecasts(self) -> None:
    _register_standard_mocks(resp_lib)
    client = NWSClient(base_url=NWS_BASE)
    days = client.fetch_daily_forecast(40.7828, -73.9654)
    assert len(days) >= 1
    assert days[0].high_f == 88.0

  @resp_lib.activate
  def test_etag_stored_after_first_fetch(self) -> None:
    _register_standard_mocks(resp_lib)
    client = NWSClient(base_url=NWS_BASE)
    client.fetch_daily_forecast(40.7828, -73.9654)
    forecast_url = f"{NWS_BASE}/gridpoints/OKX/33,37/forecast"
    assert client._etags.get(forecast_url) == '"abc123"'

  @resp_lib.activate
  def test_304_returns_cached_data(self) -> None:
    forecast_url = f"{NWS_BASE}/gridpoints/OKX/33,37/forecast"
    resp_lib.add(resp_lib.GET, f"{NWS_BASE}/points/40.7828,-73.9654", json=POINTS_RESPONSE)
    # First call -> 200 with ETag
    resp_lib.add(
      resp_lib.GET,
      forecast_url,
      json=FORECAST_RESPONSE,
      status=200,
      headers={"ETag": '"abc123"'},
    )
    # Second call -> 304 Not Modified (no body — 304 must be bodyless)
    resp_lib.add(resp_lib.GET, forecast_url, body=b"", status=304)

    client = NWSClient(base_url=NWS_BASE)
    first = client.fetch_daily_forecast(40.7828, -73.9654)
    second = client.fetch_daily_forecast(40.7828, -73.9654)
    assert first[0].high_f == second[0].high_f
    assert len(resp_lib.calls) == 3  # points + forecast + 304

  @resp_lib.activate
  def test_if_none_match_sent_on_second_call(self) -> None:
    forecast_url = f"{NWS_BASE}/gridpoints/OKX/33,37/forecast"
    resp_lib.add(resp_lib.GET, f"{NWS_BASE}/points/40.7828,-73.9654", json=POINTS_RESPONSE)
    resp_lib.add(
      resp_lib.GET, forecast_url, json=FORECAST_RESPONSE, status=200,
      headers={"ETag": '"abc123"'},
    )
    resp_lib.add(resp_lib.GET, forecast_url, json=FORECAST_RESPONSE, status=200)

    client = NWSClient(base_url=NWS_BASE)
    client.fetch_daily_forecast(40.7828, -73.9654)
    client.fetch_daily_forecast(40.7828, -73.9654)

    second_req = resp_lib.calls[2].request
    assert second_req.headers.get("If-None-Match") == '"abc123"'


class TestFetchHourlyForecast:
  @resp_lib.activate
  def test_returns_hourly_list(self) -> None:
    _register_standard_mocks(resp_lib)
    client = NWSClient(base_url=NWS_BASE)
    hours = client.fetch_hourly_forecast(40.7828, -73.9654)
    assert len(hours) == 2
    assert hours[0].temperature_f == 85.0
    assert hours[0].source == "nws"

  @resp_lib.activate
  def test_wind_range_averaged(self) -> None:
    _register_standard_mocks(resp_lib)
    client = NWSClient(base_url=NWS_BASE)
    hours = client.fetch_hourly_forecast(40.7828, -73.9654)
    assert hours[1].wind_speed_mph == pytest.approx(12.5)  # (10+15)/2

  @resp_lib.activate
  def test_none_humidity_becomes_none(self) -> None:
    _register_standard_mocks(resp_lib)
    client = NWSClient(base_url=NWS_BASE)
    hours = client.fetch_hourly_forecast(40.7828, -73.9654)
    assert hours[1].humidity_pct is None

  @resp_lib.activate
  def test_none_precip_becomes_zero(self) -> None:
    _register_standard_mocks(resp_lib)
    client = NWSClient(base_url=NWS_BASE)
    hours = client.fetch_hourly_forecast(40.7828, -73.9654)
    assert hours[1].precip_prob == pytest.approx(0.0)


class TestRetryBehavior:
  @resp_lib.activate
  def test_retries_on_500_then_succeeds(self) -> None:
    import unittest.mock as mock
    forecast_url = f"{NWS_BASE}/gridpoints/OKX/33,37/forecast"
    resp_lib.add(resp_lib.GET, f"{NWS_BASE}/points/40.7828,-73.9654", json=POINTS_RESPONSE)
    resp_lib.add(resp_lib.GET, forecast_url, json={}, status=500)
    resp_lib.add(resp_lib.GET, forecast_url, json=FORECAST_RESPONSE, status=200)

    client = NWSClient(base_url=NWS_BASE)
    with mock.patch("time.sleep"):
      days = client.fetch_daily_forecast(40.7828, -73.9654)
    assert days[0].high_f == 88.0

  @resp_lib.activate
  def test_raises_after_max_retries(self) -> None:
    import unittest.mock as mock
    forecast_url = f"{NWS_BASE}/gridpoints/OKX/33,37/forecast"
    resp_lib.add(resp_lib.GET, f"{NWS_BASE}/points/40.7828,-73.9654", json=POINTS_RESPONSE)
    for _ in range(4):
      resp_lib.add(resp_lib.GET, forecast_url, json={}, status=500)

    client = NWSClient(base_url=NWS_BASE)
    with mock.patch("time.sleep"), pytest.raises(NWSError):
      client.fetch_daily_forecast(40.7828, -73.9654)
