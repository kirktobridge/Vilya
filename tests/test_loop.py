"""Tests for execution.loop.run_once."""
import unittest.mock as mock
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.execution.loop import run_once
from src.execution.order_manager import OrderManager
from src.execution.risk import RiskError, RiskManager, RiskState
from src.kalshi_client.models import Market, Portfolio, Position
from src.models.predict import ModelBundle


# ---------------------------------------------------------------------------
# Helpers / factories
# ---------------------------------------------------------------------------

def _make_market(
  ticker: str = "KXHIGHNY-24JUN12-T90",
  yes_bid: int = 40,
  yes_ask: int = 44,
  close_time: datetime | None = None,
) -> Market:
  if close_time is None:
    close_time = datetime(2099, 6, 12, 20, 0, tzinfo=timezone.utc)
  return Market(
    ticker=ticker,
    series_ticker="KXHIGHNY",
    event_ticker="KXHIGHNY-24JUN12",
    yes_bid=yes_bid,
    yes_ask=yes_ask,
    last_price=42,
    volume=500,
    status="open",
    close_time=close_time,
  )


def _make_portfolio(balance: int = 100_00, positions: list[Position] | None = None) -> Portfolio:
  return Portfolio(balance=balance, positions=positions or [])


def _make_run_once_kwargs(
  client: MagicMock | None = None,
  risk: RiskManager | None = None,
  orders: OrderManager | None = None,
  model: ModelBundle | None = None,
  engine: MagicMock | None = None,
  series_ticker: str = "KXHIGHNY",
  location: str = "NYC_CENTRAL_PARK",
  ev_threshold: float = 0.03,
  max_contracts: int = 5,
) -> dict:
  if client is None:
    client = MagicMock()
  if risk is None:
    risk = RiskManager(RiskState(peak_equity=100.0, current_equity=100.0))
  if orders is None:
    mgr_client = MagicMock()
    orders = OrderManager(mgr_client, paper=True)
  if model is None:
    model = MagicMock(spec=ModelBundle)
    model.feature_names = ["nws_t24_forecast_high_f"]
  if engine is None:
    engine = MagicMock()
    engine.begin.return_value.__enter__ = MagicMock(return_value=MagicMock())
    engine.begin.return_value.__exit__ = MagicMock(return_value=False)
  return dict(
    client=client,
    risk=risk,
    orders=orders,
    model=model,
    engine=engine,
    series_ticker=series_ticker,
    location=location,
    ev_threshold=ev_threshold,
    max_contracts=max_contracts,
  )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRunOnceSkips:
  @patch("src.execution.loop.get_portfolio")
  @patch("src.execution.loop.get_markets")
  @patch("src.execution.loop.build_live_feature_row", return_value=None)
  @patch("src.execution.loop.predict_prob")
  def test_skips_when_no_features(self, mock_pred, mock_feat, mock_markets, mock_port) -> None:
    mock_port.return_value = _make_portfolio()
    mock_markets.return_value = [_make_market()]
    kwargs = _make_run_once_kwargs()
    with patch.object(kwargs["orders"], "place_limit_order") as mock_place:
      run_once(**kwargs)
    mock_place.assert_not_called()

  @patch("src.execution.loop.get_portfolio")
  @patch("src.execution.loop.get_markets")
  @patch("src.execution.loop.build_live_feature_row")
  @patch("src.execution.loop.predict_prob", return_value=0.50)  # no edge
  def test_skips_on_weak_signal(self, mock_pred, mock_feat, mock_markets, mock_port) -> None:
    mock_port.return_value = _make_portfolio()
    mock_markets.return_value = [_make_market(yes_bid=47, yes_ask=53)]  # yes_price=50, no edge
    mock_feat.return_value = {"nws_t24_forecast_high_f": 88.0}
    kwargs = _make_run_once_kwargs()
    with patch.object(kwargs["orders"], "place_limit_order") as mock_place:
      run_once(**kwargs)
    mock_place.assert_not_called()

  @patch("src.execution.loop.get_portfolio")
  @patch("src.execution.loop.get_markets")
  def test_skips_already_closed_market(self, mock_markets, mock_port) -> None:
    mock_port.return_value = _make_portfolio()
    past = datetime(2020, 1, 1, tzinfo=timezone.utc)
    mock_markets.return_value = [_make_market(close_time=past)]
    kwargs = _make_run_once_kwargs()
    with patch("src.execution.loop.build_live_feature_row") as mock_feat:
      run_once(**kwargs)
    mock_feat.assert_not_called()


class TestRunOncePlacesOrder:
  @patch("src.execution.loop.get_portfolio")
  @patch("src.execution.loop.get_markets")
  @patch("src.execution.loop.build_live_feature_row")
  @patch("src.execution.loop.predict_prob", return_value=0.70)  # strong YES signal
  def test_places_order_on_strong_buy_yes(self, mock_pred, mock_feat, mock_markets, mock_port) -> None:
    mock_port.return_value = _make_portfolio()
    # yes_price = (30+36)//2 = 33, model=0.70, edge_buy=0.70-0.33=0.37 >> 0.03
    mock_markets.return_value = [_make_market(yes_bid=30, yes_ask=36)]
    mock_feat.return_value = {"nws_t24_forecast_high_f": 92.0}
    kwargs = _make_run_once_kwargs()
    with patch.object(kwargs["orders"], "place_limit_order", return_value=None) as mock_place:
      run_once(**kwargs)
    mock_place.assert_called_once()
    call_kwargs = mock_place.call_args
    assert call_kwargs.args[1] == "yes"  # side

  @patch("src.execution.loop.get_portfolio")
  @patch("src.execution.loop.get_markets")
  @patch("src.execution.loop.build_live_feature_row")
  @patch("src.execution.loop.predict_prob", return_value=0.30)  # strong NO signal
  def test_places_order_on_strong_buy_no(self, mock_pred, mock_feat, mock_markets, mock_port) -> None:
    mock_port.return_value = _make_portfolio()
    # yes_price=(64+70)//2=67, model=0.30, edge_sell=0.67-0.30=0.37 >> 0.03
    mock_markets.return_value = [_make_market(yes_bid=64, yes_ask=70)]
    mock_feat.return_value = {"nws_t24_forecast_high_f": 80.0}
    kwargs = _make_run_once_kwargs()
    with patch.object(kwargs["orders"], "place_limit_order", return_value=None) as mock_place:
      run_once(**kwargs)
    mock_place.assert_called_once()
    assert mock_place.call_args.args[1] == "no"  # side


class TestRunOnceKillSwitch:
  @patch("src.execution.loop.get_portfolio")
  @patch("src.execution.loop.get_markets")
  def test_aborts_on_kill_switch(self, mock_markets, mock_port) -> None:
    mock_port.return_value = _make_portfolio(balance=0)
    mock_markets.return_value = [_make_market()]
    state = RiskState(peak_equity=200.0, current_equity=50.0, killed=False)
    kwargs = _make_run_once_kwargs(risk=RiskManager(state))
    with patch.object(kwargs["orders"], "cancel_all") as mock_cancel_all:
      with patch("src.execution.loop.build_live_feature_row") as mock_feat:
        run_once(**kwargs)
    mock_cancel_all.assert_called_once()
    mock_feat.assert_not_called()  # should abort before processing markets

  @patch("src.execution.loop.get_portfolio")
  @patch("src.execution.loop.get_markets")
  def test_already_killed_aborts(self, mock_markets, mock_port) -> None:
    mock_port.return_value = _make_portfolio()
    mock_markets.return_value = [_make_market()]
    state = RiskState(killed=True)
    kwargs = _make_run_once_kwargs(risk=RiskManager(state))
    with patch.object(kwargs["orders"], "cancel_all") as mock_cancel_all:
      with patch("src.execution.loop.build_live_feature_row") as mock_feat:
        run_once(**kwargs)
    mock_cancel_all.assert_called_once()
    mock_feat.assert_not_called()


class TestRunOncePositionMaxed:
  @patch("src.execution.loop.get_portfolio")
  @patch("src.execution.loop.get_markets")
  @patch("src.execution.loop.build_live_feature_row")
  @patch("src.execution.loop.predict_prob", return_value=0.70)
  def test_skips_when_position_maxed(self, mock_pred, mock_feat, mock_markets, mock_port) -> None:
    ticker = "KXHIGHNY-24JUN12-T90"
    # Already holding max_contracts=5 YES contracts
    pos = Position(ticker=ticker, position=5)
    mock_port.return_value = _make_portfolio(positions=[pos])
    mock_markets.return_value = [_make_market(ticker=ticker, yes_bid=30, yes_ask=36)]
    mock_feat.return_value = {"nws_t24_forecast_high_f": 92.0}
    kwargs = _make_run_once_kwargs(max_contracts=5)
    with patch.object(kwargs["orders"], "place_limit_order") as mock_place:
      run_once(**kwargs)
    mock_place.assert_not_called()


class TestRunOnceCancelsStale:
  @patch("src.execution.loop.get_portfolio")
  @patch("src.execution.loop.get_markets")
  @patch("src.execution.loop.build_live_feature_row")
  @patch("src.execution.loop.predict_prob", return_value=0.50)
  def test_cancel_stale_called_per_market(self, mock_pred, mock_feat, mock_markets, mock_port) -> None:
    mock_port.return_value = _make_portfolio()
    mock_markets.return_value = [_make_market()]
    mock_feat.return_value = {"nws_t24_forecast_high_f": 85.0}
    kwargs = _make_run_once_kwargs()
    with patch.object(kwargs["orders"], "cancel_stale_orders", return_value=[]) as mock_cancel:
      run_once(**kwargs)
    mock_cancel.assert_called_once()


class TestRunOnceRiskBlocked:
  @patch("src.execution.loop.get_portfolio")
  @patch("src.execution.loop.get_markets")
  @patch("src.execution.loop.build_live_feature_row")
  @patch("src.execution.loop.predict_prob", return_value=0.70)
  def test_risk_block_skips_order(self, mock_pred, mock_feat, mock_markets, mock_port) -> None:
    mock_port.return_value = _make_portfolio()
    mock_markets.return_value = [_make_market(yes_bid=30, yes_ask=36)]
    mock_feat.return_value = {"nws_t24_forecast_high_f": 92.0}
    # Already at daily notional cap
    state = RiskState(daily_notional=499.99)
    kwargs = _make_run_once_kwargs(risk=RiskManager(state))
    with patch.object(kwargs["orders"], "place_limit_order") as mock_place:
      run_once(**kwargs)
    mock_place.assert_not_called()
