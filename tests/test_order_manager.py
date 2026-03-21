"""Tests for execution.order_manager."""
import unittest.mock as mock

import pytest
import responses as resp_lib

from src.execution.order_manager import OrderManager, TrackedOrder, _PRICE_DRIFT_CENTS, _PROB_DRIFT_THRESHOLD
from src.kalshi_client.client import KalshiClient

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
TICKER = "KXHIGHNY-24JUN12-T90"

MOCK_ORDER_RESPONSE = {
  "order": {
    "order_id": "ord-abc123",
    "ticker": TICKER,
    "side": "yes",
    "action": "buy",
    "type": "limit",
    "count": 1,
    "yes_price": 42,
    "no_price": 58,
    "status": "resting",
  }
}


def _make_manager(paper: bool = True) -> OrderManager:
  client = KalshiClient(api_key="test-key", base_url=KALSHI_BASE)
  return OrderManager(client, paper=paper)


def _inject_tracked(mgr: OrderManager, order_id: str, ticker: str, price: int, prob: float) -> None:
  mgr._open[order_id] = TrackedOrder(
    order_id=order_id, ticker=ticker, side="yes",
    price_at_placement=price, prob_at_placement=prob,
  )


# ---------------------------------------------------------------------------
# place_limit_order — paper mode
# ---------------------------------------------------------------------------

class TestPlaceLimitOrderPaper:
  def test_returns_none_in_paper_mode(self) -> None:
    mgr = _make_manager(paper=True)
    result = mgr.place_limit_order(TICKER, "yes", 1, 42, 0.55)
    assert result is None

  def test_paper_does_not_add_to_open(self) -> None:
    mgr = _make_manager(paper=True)
    mgr.place_limit_order(TICKER, "yes", 1, 42, 0.55)
    assert len(mgr._open) == 0


# ---------------------------------------------------------------------------
# place_limit_order — live mode
# ---------------------------------------------------------------------------

class TestPlaceLimitOrderLive:
  @resp_lib.activate
  def test_live_calls_api(self) -> None:
    resp_lib.add(resp_lib.POST, f"{KALSHI_BASE}/portfolio/orders", json=MOCK_ORDER_RESPONSE)
    mgr = _make_manager(paper=False)
    order_id = mgr.place_limit_order(TICKER, "yes", 1, 42, 0.55)
    assert order_id == "ord-abc123"

  @resp_lib.activate
  def test_live_tracks_order_in_open(self) -> None:
    resp_lib.add(resp_lib.POST, f"{KALSHI_BASE}/portfolio/orders", json=MOCK_ORDER_RESPONSE)
    mgr = _make_manager(paper=False)
    mgr.place_limit_order(TICKER, "yes", 1, 42, 0.55)
    assert "ord-abc123" in mgr._open

  @resp_lib.activate
  def test_tracked_order_stores_price_and_prob(self) -> None:
    resp_lib.add(resp_lib.POST, f"{KALSHI_BASE}/portfolio/orders", json=MOCK_ORDER_RESPONSE)
    mgr = _make_manager(paper=False)
    mgr.place_limit_order(TICKER, "yes", 1, 42, 0.55)
    tracked = mgr._open["ord-abc123"]
    assert tracked.price_at_placement == 42
    assert tracked.prob_at_placement == pytest.approx(0.55)


# ---------------------------------------------------------------------------
# cancel_stale_orders
# ---------------------------------------------------------------------------

class TestCancelStaleOrders:
  def test_price_drift_triggers_cancel(self) -> None:
    mgr = _make_manager(paper=True)
    _inject_tracked(mgr, "ord-1", TICKER, price=42, prob=0.55)
    cancelled = mgr.cancel_stale_orders(TICKER, 42 + _PRICE_DRIFT_CENTS + 1, 0.55)
    assert "ord-1" in cancelled
    assert "ord-1" not in mgr._open

  def test_prob_drift_triggers_cancel(self) -> None:
    mgr = _make_manager(paper=True)
    _inject_tracked(mgr, "ord-1", TICKER, price=42, prob=0.55)
    cancelled = mgr.cancel_stale_orders(TICKER, 42, 0.55 + _PROB_DRIFT_THRESHOLD + 0.01)
    assert "ord-1" in cancelled

  def test_within_bounds_not_cancelled(self) -> None:
    mgr = _make_manager(paper=True)
    _inject_tracked(mgr, "ord-1", TICKER, price=42, prob=0.55)
    cancelled = mgr.cancel_stale_orders(TICKER, 43, 0.56)  # drift = 1 cent, 0.01 prob
    assert cancelled == []
    assert "ord-1" in mgr._open

  def test_different_ticker_not_cancelled(self) -> None:
    mgr = _make_manager(paper=True)
    _inject_tracked(mgr, "ord-1", "OTHER-TICKER-99", price=42, prob=0.55)
    # Large drift on a different ticker
    cancelled = mgr.cancel_stale_orders(TICKER, 99, 0.99)
    assert cancelled == []
    assert "ord-1" in mgr._open

  def test_returns_empty_when_no_tracked_orders(self) -> None:
    mgr = _make_manager(paper=True)
    assert mgr.cancel_stale_orders(TICKER, 50, 0.5) == []

  @resp_lib.activate
  def test_live_calls_cancel_endpoint(self) -> None:
    resp_lib.add(resp_lib.DELETE, f"{KALSHI_BASE}/portfolio/orders/ord-1", status=200)
    mgr = _make_manager(paper=False)
    _inject_tracked(mgr, "ord-1", TICKER, price=42, prob=0.55)
    mgr.cancel_stale_orders(TICKER, 99, 0.99)
    assert len(resp_lib.calls) == 1
    assert "/portfolio/orders/ord-1" in resp_lib.calls[0].request.url

  def test_exact_price_drift_boundary_not_cancelled(self) -> None:
    mgr = _make_manager(paper=True)
    _inject_tracked(mgr, "ord-1", TICKER, price=42, prob=0.55)
    # Exactly at the boundary — should NOT cancel (> not >=)
    cancelled = mgr.cancel_stale_orders(TICKER, 42 + _PRICE_DRIFT_CENTS, 0.55)
    assert cancelled == []

  def test_exact_prob_drift_boundary_not_cancelled(self) -> None:
    mgr = _make_manager(paper=True)
    _inject_tracked(mgr, "ord-1", TICKER, price=42, prob=0.55)
    cancelled = mgr.cancel_stale_orders(TICKER, 42, 0.55 + _PROB_DRIFT_THRESHOLD)
    assert cancelled == []


# ---------------------------------------------------------------------------
# cancel_all
# ---------------------------------------------------------------------------

class TestCancelAll:
  def test_clears_all_open_orders_paper(self) -> None:
    mgr = _make_manager(paper=True)
    _inject_tracked(mgr, "ord-1", TICKER, 42, 0.55)
    _inject_tracked(mgr, "ord-2", "OTHER-99", 50, 0.60)
    mgr.cancel_all()
    assert mgr._open == {}

  def test_cancel_all_empty_does_not_raise(self) -> None:
    mgr = _make_manager(paper=True)
    mgr.cancel_all()  # should not raise

  @resp_lib.activate
  def test_live_cancel_all_calls_api_for_each(self) -> None:
    resp_lib.add(resp_lib.DELETE, f"{KALSHI_BASE}/portfolio/orders/ord-1", status=200)
    resp_lib.add(resp_lib.DELETE, f"{KALSHI_BASE}/portfolio/orders/ord-2", status=200)
    mgr = _make_manager(paper=False)
    _inject_tracked(mgr, "ord-1", TICKER, 42, 0.55)
    _inject_tracked(mgr, "ord-2", "OTHER-99", 50, 0.60)
    mgr.cancel_all()
    assert len(resp_lib.calls) == 2
    assert mgr._open == {}
