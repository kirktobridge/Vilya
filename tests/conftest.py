"""Shared pytest fixtures: mock Kalshi API, mock NWS API."""
import os

import pytest
import responses as resp_lib

# Ensure test env vars are set before any src imports
os.environ.setdefault("KALSHI_API_KEY", "test_key")
os.environ.setdefault("OPENWEATHER_API_KEY", "test_key")
os.environ.setdefault("DATABASE_URL", "postgresql://bot:bot@localhost:5432/kalshi_bot")


KALSHI_BASE = "https://trading-api.kalshi.com/trade-api/v2"
NWS_BASE = "https://api.weather.gov"
OW_BASE = "https://api.openweathermap.org/data/3.0"

MOCK_MARKET = {
  "ticker": "KXHIGHNY-24JUN12-T90",
  "series_ticker": "KXHIGHNY",
  "event_ticker": "KXHIGHNY-24JUN12",
  "title": "Will NYC high be >= 90°F on Jun 12?",
  "yes_price": 42,
  "volume": 1500,
  "status": "open",
}

MOCK_ORDERBOOK = {
  "ticker": "KXHIGHNY-24JUN12-T90",
  "yes_bids": [[41, 10], [40, 25]],
  "yes_asks": [[43, 8], [45, 20]],
}

MOCK_PORTFOLIO = {
  "available_balance": 1000.0,
  "portfolio_value": 1050.0,
  "positions": [],
}


@pytest.fixture()
def mock_kalshi_api():
  """Activate responses mock for Kalshi endpoints."""
  with resp_lib.RequestsMock() as rsps:
    rsps.add(
      resp_lib.GET,
      f"{KALSHI_BASE}/markets",
      json={"markets": [MOCK_MARKET]},
      status=200,
    )
    rsps.add(
      resp_lib.GET,
      f"{KALSHI_BASE}/markets/KXHIGHNY-24JUN12-T90/orderbook",
      json=MOCK_ORDERBOOK,
      status=200,
    )
    rsps.add(
      resp_lib.GET,
      f"{KALSHI_BASE}/portfolio/balance",
      json=MOCK_PORTFOLIO,
      status=200,
    )
    yield rsps


@pytest.fixture()
def mock_nws_api():
  """Activate responses mock for NWS endpoints."""
  with resp_lib.RequestsMock() as rsps:
    rsps.add(
      resp_lib.GET,
      f"{NWS_BASE}/points/40.7828,-73.9654",
      json={
        "properties": {
          "forecast": f"{NWS_BASE}/gridpoints/OKX/33,37/forecast",
          "forecastHourly": f"{NWS_BASE}/gridpoints/OKX/33,37/forecast/hourly",
          "forecastGridData": f"{NWS_BASE}/gridpoints/OKX/33,37",
        }
      },
      status=200,
    )
    yield rsps
