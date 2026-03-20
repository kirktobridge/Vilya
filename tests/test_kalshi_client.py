"""Tests for kalshi_client.client (retry logic, auth)."""
import pytest
import responses as resp_lib

from src.kalshi_client.client import KalshiAPIError, KalshiClient

KALSHI_BASE = "https://trading-api.kalshi.com/trade-api/v2"


@resp_lib.activate
def test_successful_get() -> None:
  resp_lib.add(resp_lib.GET, f"{KALSHI_BASE}/ping", json={"ok": True}, status=200)
  client = KalshiClient(api_key="test", base_url=KALSHI_BASE)
  result = client.get("/ping")
  assert result == {"ok": True}


@resp_lib.activate
def test_raises_on_4xx() -> None:
  resp_lib.add(resp_lib.GET, f"{KALSHI_BASE}/ping", json={"error": "not found"}, status=404)
  client = KalshiClient(api_key="test", base_url=KALSHI_BASE)
  with pytest.raises(KalshiAPIError) as exc_info:
    client.get("/ping")
  assert exc_info.value.status_code == 404


@resp_lib.activate
def test_retries_on_429() -> None:
  # First call returns 429, second returns 200
  resp_lib.add(resp_lib.GET, f"{KALSHI_BASE}/ping", json={}, status=429)
  resp_lib.add(resp_lib.GET, f"{KALSHI_BASE}/ping", json={"ok": True}, status=200)
  client = KalshiClient(api_key="test", base_url=KALSHI_BASE)
  # Patch sleep to avoid slow tests
  import unittest.mock as mock
  with mock.patch("time.sleep"):
    result = client.get("/ping")
  assert result == {"ok": True}


@resp_lib.activate
def test_auth_header_sent() -> None:
  resp_lib.add(resp_lib.GET, f"{KALSHI_BASE}/ping", json={}, status=200)
  client = KalshiClient(api_key="my_secret_key", base_url=KALSHI_BASE)
  client.get("/ping")
  assert resp_lib.calls[0].request.headers["Authorization"] == "Bearer my_secret_key"
