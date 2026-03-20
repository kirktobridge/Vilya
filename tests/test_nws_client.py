"""Tests for weather_data.nws_client (Phase 1 — stubs, expand when implemented)."""
import pytest

from src.weather_data.nws_client import NWSClient


def test_nws_client_instantiates() -> None:
  client = NWSClient(base_url="https://api.weather.gov")
  assert client._base_url == "https://api.weather.gov"


def test_resolve_gridpoint_not_implemented() -> None:
  client = NWSClient()
  with pytest.raises(NotImplementedError):
    client.resolve_gridpoint(40.7828, -73.9654)


def test_fetch_daily_forecast_not_implemented() -> None:
  client = NWSClient()
  with pytest.raises(NotImplementedError):
    client.fetch_daily_forecast(40.7828, -73.9654)
