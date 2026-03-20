"""Tests for execution.risk hard constraints."""
import pytest

from src.execution.risk import RiskError, RiskManager, RiskState


def test_max_contracts_blocked() -> None:
  rm = RiskManager()
  with pytest.raises(RiskError, match="max"):
    rm.check_order(contracts=6, price_cents=50)


def test_daily_notional_cap() -> None:
  state = RiskState(daily_notional=498.0)
  rm = RiskManager(state)
  # 5 contracts at $1 each = $5 notional, total $503 > $500
  with pytest.raises(RiskError, match="notional"):
    rm.check_order(contracts=5, price_cents=100)


def test_order_within_limits_passes() -> None:
  rm = RiskManager()
  rm.check_order(contracts=3, price_cents=50)  # $1.50 notional — should pass


def test_kill_switch_engages_on_drawdown() -> None:
  state = RiskState(peak_equity=500.0, current_equity=399.0)
  rm = RiskManager(state)
  with pytest.raises(RiskError, match="Kill switch"):
    rm.check_kill_switch()


def test_kill_switch_not_triggered_below_threshold() -> None:
  state = RiskState(peak_equity=500.0, current_equity=401.0)
  rm = RiskManager(state)
  rm.check_kill_switch()  # should not raise


def test_record_order_accumulates_notional() -> None:
  rm = RiskManager()
  rm.record_order(contracts=5, price_cents=80)
  assert rm.state.daily_notional == pytest.approx(4.0)


def test_already_killed_blocks_all_orders() -> None:
  state = RiskState(killed=True)
  rm = RiskManager(state)
  with pytest.raises(RiskError, match="Kill switch already engaged"):
    rm.check_kill_switch()
