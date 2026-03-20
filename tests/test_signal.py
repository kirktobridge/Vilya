"""Tests for execution.signal edge calculation."""
import pytest

from src.execution.signal import compute_signal


def test_buy_yes_when_model_above_market() -> None:
  sig = compute_signal("TICK-001", model_prob=0.65, yes_price_cents=55, ev_threshold=0.03)
  assert sig.action == "buy_yes"
  assert pytest.approx(sig.edge_buy, abs=1e-6) == 0.10


def test_buy_no_when_model_below_market() -> None:
  sig = compute_signal("TICK-001", model_prob=0.30, yes_price_cents=65, ev_threshold=0.03)
  assert sig.action == "buy_no"
  assert sig.edge_sell > 0.03


def test_skip_when_no_edge() -> None:
  sig = compute_signal("TICK-001", model_prob=0.50, yes_price_cents=49, ev_threshold=0.03)
  assert sig.action == "skip"


def test_market_implied_conversion() -> None:
  sig = compute_signal("TICK-001", model_prob=0.50, yes_price_cents=50, ev_threshold=0.03)
  assert pytest.approx(sig.market_implied) == 0.50


def test_exact_threshold_is_skip() -> None:
  # edge_buy == threshold exactly should not trigger
  sig = compute_signal("TICK-001", model_prob=0.53, yes_price_cents=50, ev_threshold=0.03)
  assert sig.action == "skip"
