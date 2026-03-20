"""Tests for kalshi_client — client retry logic, models, and endpoint wrappers."""
import unittest.mock as mock

import pytest
import responses as resp_lib

from src.kalshi_client.client import KalshiAPIError, KalshiClient
from src.kalshi_client.endpoints import (
  cancel_order,
  get_markets,
  get_open_orders,
  get_orderbook,
  get_portfolio,
  place_order,
)
from src.kalshi_client.models import Market, Order, OrderBook, Portfolio, Position

KALSHI_BASE = "https://trading-api.kalshi.com/trade-api/v2"

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

MARKET_PAYLOAD = {
  "ticker": "KXHIGHNY-24JUL04-T85",
  "series_ticker": "KXHIGHNY",
  "event_ticker": "KXHIGHNY-24JUL04",
  "title": "NYC high >= 85°F on Jul 4?",
  "yes_bid": 44,
  "yes_ask": 46,
  "last_price": 45,
  "volume": 1200,
  "status": "open",
  "close_time": "2024-07-04T21:00:00Z",
}

ORDER_PAYLOAD = {
  "order_id": "ord_abc123",
  "ticker": "KXHIGHNY-24JUL04-T85",
  "side": "yes",
  "action": "buy",
  "type": "limit",
  "count": 3,
  "yes_price": 44,
  "no_price": 56,
  "status": "resting",
  "created_time": "2024-07-03T10:00:00Z",
}


def _make_client() -> KalshiClient:
  return KalshiClient(api_key="test-key", base_url=KALSHI_BASE)


# ---------------------------------------------------------------------------
# KalshiClient — HTTP layer
# ---------------------------------------------------------------------------

class TestKalshiClientHTTP:
  @resp_lib.activate
  def test_successful_get(self) -> None:
    resp_lib.add(resp_lib.GET, f"{KALSHI_BASE}/ping", json={"ok": True})
    assert _make_client().get("/ping") == {"ok": True}

  @resp_lib.activate
  def test_raises_on_4xx(self) -> None:
    resp_lib.add(resp_lib.GET, f"{KALSHI_BASE}/ping", json={}, status=404)
    with pytest.raises(KalshiAPIError) as exc_info:
      _make_client().get("/ping")
    assert exc_info.value.status_code == 404

  @resp_lib.activate
  def test_retries_on_429_then_succeeds(self) -> None:
    resp_lib.add(resp_lib.GET, f"{KALSHI_BASE}/ping", json={}, status=429)
    resp_lib.add(resp_lib.GET, f"{KALSHI_BASE}/ping", json={"ok": True})
    with mock.patch("time.sleep"):
      result = _make_client().get("/ping")
    assert result == {"ok": True}

  @resp_lib.activate
  def test_raises_after_max_retries(self) -> None:
    for _ in range(5):
      resp_lib.add(resp_lib.GET, f"{KALSHI_BASE}/ping", json={}, status=500)
    with mock.patch("time.sleep"), pytest.raises(KalshiAPIError):
      _make_client().get("/ping")

  @resp_lib.activate
  def test_bearer_token_in_auth_header(self) -> None:
    resp_lib.add(resp_lib.GET, f"{KALSHI_BASE}/ping", json={})
    _make_client().get("/ping")
    assert resp_lib.calls[0].request.headers["Authorization"] == "Bearer test-key"

  @resp_lib.activate
  def test_post_sends_json_body(self) -> None:
    resp_lib.add(resp_lib.POST, f"{KALSHI_BASE}/orders", json={"order": ORDER_PAYLOAD})
    _make_client().post("/orders", json={"ticker": "X", "count": 1})
    import json
    body = json.loads(resp_lib.calls[0].request.body)
    assert body["ticker"] == "X"

  @resp_lib.activate
  def test_delete_returns_response(self) -> None:
    resp_lib.add(resp_lib.DELETE, f"{KALSHI_BASE}/orders/ord_abc123", json={"ok": True})
    result = _make_client().delete("/orders/ord_abc123")
    assert result == {"ok": True}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class TestMarketModel:
  def test_yes_price_mid_when_bid_and_ask_set(self) -> None:
    m = Market.model_validate(MARKET_PAYLOAD)
    assert m.yes_price == 45  # (44 + 46) // 2

  def test_yes_price_falls_back_to_last_price(self) -> None:
    payload = {**MARKET_PAYLOAD, "yes_bid": 0, "yes_ask": 0, "last_price": 42}
    m = Market.model_validate(payload)
    assert m.yes_price == 42

  def test_close_time_parsed_as_datetime(self) -> None:
    m = Market.model_validate(MARKET_PAYLOAD)
    assert m.close_time is not None
    assert m.close_time.year == 2024


class TestPositionModel:
  def test_positive_position_is_yes_contracts(self) -> None:
    p = Position(ticker="X", position=5)
    assert p.yes_contracts == 5
    assert p.no_contracts == 0

  def test_negative_position_is_no_contracts(self) -> None:
    p = Position(ticker="X", position=-3)
    assert p.yes_contracts == 0
    assert p.no_contracts == 3


class TestPortfolioModel:
  def test_available_balance_usd_conversion(self) -> None:
    port = Portfolio(balance=10050)
    assert port.available_balance_usd == pytest.approx(100.50)


class TestOrderModel:
  def test_parses_type_alias(self) -> None:
    order = Order.model_validate(ORDER_PAYLOAD)
    assert order.order_type == "limit"
    assert order.order_id == "ord_abc123"


# ---------------------------------------------------------------------------
# Endpoint wrappers
# ---------------------------------------------------------------------------

class TestGetMarkets:
  @resp_lib.activate
  def test_returns_market_list(self) -> None:
    resp_lib.add(
      resp_lib.GET,
      f"{KALSHI_BASE}/markets",
      json={"markets": [MARKET_PAYLOAD], "cursor": ""},
    )
    markets = get_markets(_make_client(), "KXHIGHNY")
    assert len(markets) == 1
    assert markets[0].ticker == "KXHIGHNY-24JUL04-T85"

  @resp_lib.activate
  def test_series_ticker_passed_as_query_param(self) -> None:
    resp_lib.add(resp_lib.GET, f"{KALSHI_BASE}/markets", json={"markets": []})
    get_markets(_make_client(), "KXHIGHNY")
    assert "series_ticker=KXHIGHNY" in resp_lib.calls[0].request.url

  @resp_lib.activate
  def test_status_open_passed_as_query_param(self) -> None:
    resp_lib.add(resp_lib.GET, f"{KALSHI_BASE}/markets", json={"markets": []})
    get_markets(_make_client(), "KXHIGHNY")
    assert "status=open" in resp_lib.calls[0].request.url

  @resp_lib.activate
  def test_empty_response_returns_empty_list(self) -> None:
    resp_lib.add(resp_lib.GET, f"{KALSHI_BASE}/markets", json={"markets": []})
    assert get_markets(_make_client(), "KXHIGHNY") == []


class TestGetOrderbook:
  @resp_lib.activate
  def test_parses_yes_and_no_sides(self) -> None:
    resp_lib.add(
      resp_lib.GET,
      f"{KALSHI_BASE}/markets/KXHIGHNY-24JUL04-T85/orderbook",
      json={"orderbook": {"yes": [[44, 100], [43, 200]], "no": [[55, 50]]}},
    )
    ob = get_orderbook(_make_client(), "KXHIGHNY-24JUL04-T85")
    assert ob.ticker == "KXHIGHNY-24JUL04-T85"
    assert ob.yes == [(44, 100), (43, 200)]
    assert ob.no == [(55, 50)]

  @resp_lib.activate
  def test_empty_orderbook(self) -> None:
    resp_lib.add(
      resp_lib.GET,
      f"{KALSHI_BASE}/markets/X/orderbook",
      json={"orderbook": {}},
    )
    ob = get_orderbook(_make_client(), "X")
    assert ob.yes == []
    assert ob.no == []


class TestGetPortfolio:
  @resp_lib.activate
  def test_combines_balance_and_positions(self) -> None:
    resp_lib.add(resp_lib.GET, f"{KALSHI_BASE}/portfolio/balance", json={"balance": 50000})
    resp_lib.add(
      resp_lib.GET,
      f"{KALSHI_BASE}/portfolio/positions",
      json={"positions": [{"ticker": "KXHIGHNY-24JUL04-T85", "position": 3}]},
    )
    port = get_portfolio(_make_client())
    assert port.available_balance_usd == pytest.approx(500.0)
    assert len(port.positions) == 1
    assert port.positions[0].yes_contracts == 3

  @resp_lib.activate
  def test_empty_positions(self) -> None:
    resp_lib.add(resp_lib.GET, f"{KALSHI_BASE}/portfolio/balance", json={"balance": 0})
    resp_lib.add(resp_lib.GET, f"{KALSHI_BASE}/portfolio/positions", json={"positions": []})
    port = get_portfolio(_make_client())
    assert port.positions == []


class TestPlaceOrder:
  @resp_lib.activate
  def test_returns_order_object(self) -> None:
    resp_lib.add(
      resp_lib.POST, f"{KALSHI_BASE}/orders", json={"order": ORDER_PAYLOAD}
    )
    order = place_order(_make_client(), "KXHIGHNY-24JUL04-T85", "yes", 3, 44)
    assert order.order_id == "ord_abc123"
    assert order.count == 3

  @resp_lib.activate
  def test_yes_side_sets_correct_prices(self) -> None:
    resp_lib.add(resp_lib.POST, f"{KALSHI_BASE}/orders", json={"order": ORDER_PAYLOAD})
    import json
    place_order(_make_client(), "KXHIGHNY-24JUL04-T85", "yes", 3, 44)
    body = json.loads(resp_lib.calls[0].request.body)
    assert body["yes_price"] == 44
    assert body["no_price"] == 56  # 100 - 44

  @resp_lib.activate
  def test_no_side_sets_correct_prices(self) -> None:
    no_order = {**ORDER_PAYLOAD, "side": "no", "yes_price": 44, "no_price": 56}
    resp_lib.add(resp_lib.POST, f"{KALSHI_BASE}/orders", json={"order": no_order})
    import json
    place_order(_make_client(), "KXHIGHNY-24JUL04-T85", "no", 3, 56)
    body = json.loads(resp_lib.calls[0].request.body)
    assert body["no_price"] == 56
    assert body["yes_price"] == 44  # 100 - 56

  @resp_lib.activate
  def test_order_type_is_always_limit(self) -> None:
    resp_lib.add(resp_lib.POST, f"{KALSHI_BASE}/orders", json={"order": ORDER_PAYLOAD})
    import json
    place_order(_make_client(), "KXHIGHNY-24JUL04-T85", "yes", 3, 44)
    body = json.loads(resp_lib.calls[0].request.body)
    assert body["type"] == "limit"


class TestCancelOrder:
  @resp_lib.activate
  def test_sends_delete_to_correct_url(self) -> None:
    resp_lib.add(resp_lib.DELETE, f"{KALSHI_BASE}/orders/ord_abc123", json={})
    cancel_order(_make_client(), "ord_abc123")
    assert resp_lib.calls[0].request.method == "DELETE"
    assert "/orders/ord_abc123" in resp_lib.calls[0].request.url

  @resp_lib.activate
  def test_returns_none(self) -> None:
    resp_lib.add(resp_lib.DELETE, f"{KALSHI_BASE}/orders/ord_abc123", json={})
    result = cancel_order(_make_client(), "ord_abc123")
    assert result is None


class TestGetOpenOrders:
  @resp_lib.activate
  def test_returns_order_list(self) -> None:
    resp_lib.add(
      resp_lib.GET,
      f"{KALSHI_BASE}/orders",
      json={"orders": [ORDER_PAYLOAD]},
    )
    orders = get_open_orders(_make_client())
    assert len(orders) == 1
    assert orders[0].status == "resting"

  @resp_lib.activate
  def test_status_resting_query_param(self) -> None:
    resp_lib.add(resp_lib.GET, f"{KALSHI_BASE}/orders", json={"orders": []})
    get_open_orders(_make_client())
    assert "status=resting" in resp_lib.calls[0].request.url

  @resp_lib.activate
  def test_empty_orders(self) -> None:
    resp_lib.add(resp_lib.GET, f"{KALSHI_BASE}/orders", json={"orders": []})
    assert get_open_orders(_make_client()) == []
