"""Tests for src/features/forecast_store."""
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from src.features.forecast_store import fetch_and_store_forecasts, save_forecasts
from src.weather_data.models import DailyForecast


def _make_forecast(
  valid_date: date = date(2026, 6, 12),
  source: str = "nws",
  high_f: float = 88.0,
  low_f: float = 72.0,
) -> DailyForecast:
  return DailyForecast(
    valid_date=valid_date,
    high_f=high_f,
    low_f=low_f,
    precip_prob=0.1,
    humidity_pct=65,
    source=source,
    fetched_at=datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc),
  )


def _make_engine() -> MagicMock:
  engine = MagicMock()
  conn = MagicMock()
  engine.begin.return_value.__enter__ = MagicMock(return_value=conn)
  engine.begin.return_value.__exit__ = MagicMock(return_value=False)
  return engine


# ---------------------------------------------------------------------------
# save_forecasts
# ---------------------------------------------------------------------------

class TestSaveForecasts:
  def test_returns_zero_for_empty_list(self) -> None:
    engine = _make_engine()
    count = save_forecasts(engine, "NYC_CENTRAL_PARK", [])
    assert count == 0

  def test_does_not_call_engine_on_empty(self) -> None:
    engine = _make_engine()
    save_forecasts(engine, "NYC_CENTRAL_PARK", [])
    engine.begin.assert_not_called()

  def test_returns_count_of_saved_rows(self) -> None:
    engine = _make_engine()
    forecasts = [_make_forecast(date(2026, 6, 12)), _make_forecast(date(2026, 6, 13))]
    count = save_forecasts(engine, "NYC_CENTRAL_PARK", forecasts)
    assert count == 2

  def test_calls_engine_begin(self) -> None:
    engine = _make_engine()
    save_forecasts(engine, "NYC_CENTRAL_PARK", [_make_forecast()])
    engine.begin.assert_called_once()

  def test_executes_insert_with_correct_location(self) -> None:
    engine = _make_engine()
    conn = engine.begin.return_value.__enter__.return_value
    forecast = _make_forecast(source="nws", high_f=90.0)
    save_forecasts(engine, "NYC_CENTRAL_PARK", [forecast])
    _, call_args = conn.execute.call_args
    rows = call_args  # positional: (stmt, rows)
    # The second positional arg is the list of row dicts
    execute_call = conn.execute.call_args
    rows_passed = execute_call.args[1]
    assert rows_passed[0]["location"] == "NYC_CENTRAL_PARK"
    assert rows_passed[0]["source"] == "nws"
    assert rows_passed[0]["forecast_high_f"] == 90.0

  def test_maps_forecast_fields_correctly(self) -> None:
    engine = _make_engine()
    conn = engine.begin.return_value.__enter__.return_value
    fc = _make_forecast(
      valid_date=date(2026, 7, 4),
      source="openweather",
      high_f=95.0,
      low_f=78.0,
    )
    save_forecasts(engine, "NYC_CENTRAL_PARK", [fc])
    rows = conn.execute.call_args.args[1]
    assert rows[0]["valid_date"] == date(2026, 7, 4)
    assert rows[0]["source"] == "openweather"
    assert rows[0]["forecast_high_f"] == 95.0
    assert rows[0]["forecast_low_f"] == 78.0
    assert rows[0]["precip_prob"] == pytest.approx(0.1)
    assert rows[0]["humidity_pct"] == 65

  def test_saves_multiple_forecasts_in_one_execute(self) -> None:
    engine = _make_engine()
    conn = engine.begin.return_value.__enter__.return_value
    forecasts = [_make_forecast(date(2026, 6, i)) for i in range(12, 15)]
    save_forecasts(engine, "NYC_CENTRAL_PARK", forecasts)
    rows = conn.execute.call_args.args[1]
    assert len(rows) == 3


# ---------------------------------------------------------------------------
# fetch_and_store_forecasts
# ---------------------------------------------------------------------------

class TestFetchAndStoreForecasts:
  def test_calls_nws_and_ow_fetch(self) -> None:
    nws = MagicMock()
    ow = MagicMock()
    nws.fetch_daily_forecast.return_value = [_make_forecast(source="nws")]
    ow.fetch_daily_forecast.return_value = [_make_forecast(source="openweather")]
    engine = _make_engine()

    with patch("src.features.forecast_store.save_forecasts") as mock_save:
      fetch_and_store_forecasts(nws, ow, engine, "NYC_CENTRAL_PARK", 40.78, -73.97)

    nws.fetch_daily_forecast.assert_called_once_with(40.78, -73.97)
    ow.fetch_daily_forecast.assert_called_once_with(40.78, -73.97)

  def test_saves_both_sources(self) -> None:
    nws = MagicMock()
    ow = MagicMock()
    nws_fc = [_make_forecast(source="nws")]
    ow_fc = [_make_forecast(source="openweather")]
    nws.fetch_daily_forecast.return_value = nws_fc
    ow.fetch_daily_forecast.return_value = ow_fc
    engine = _make_engine()

    with patch("src.features.forecast_store.save_forecasts") as mock_save:
      fetch_and_store_forecasts(nws, ow, engine, "NYC_CENTRAL_PARK", 40.78, -73.97)

    assert mock_save.call_count == 2
    saved_forecasts = [c.args[2] for c in mock_save.call_args_list]
    assert nws_fc in saved_forecasts
    assert ow_fc in saved_forecasts

  def test_continues_if_nws_raises(self) -> None:
    nws = MagicMock()
    ow = MagicMock()
    nws.fetch_daily_forecast.side_effect = RuntimeError("NWS down")
    ow.fetch_daily_forecast.return_value = [_make_forecast(source="openweather")]
    engine = _make_engine()

    with patch("src.features.forecast_store.save_forecasts") as mock_save:
      fetch_and_store_forecasts(nws, ow, engine, "NYC_CENTRAL_PARK", 40.78, -73.97)

    # OW should still have been called and saved despite NWS failure
    ow.fetch_daily_forecast.assert_called_once()
    mock_save.assert_called_once()

  def test_continues_if_ow_raises(self) -> None:
    nws = MagicMock()
    ow = MagicMock()
    nws.fetch_daily_forecast.return_value = [_make_forecast(source="nws")]
    ow.fetch_daily_forecast.side_effect = RuntimeError("OW down")
    engine = _make_engine()

    with patch("src.features.forecast_store.save_forecasts") as mock_save:
      fetch_and_store_forecasts(nws, ow, engine, "NYC_CENTRAL_PARK", 40.78, -73.97)

    # NWS save should still have been called
    mock_save.assert_called_once()

  def test_both_fail_does_not_raise(self) -> None:
    nws = MagicMock()
    ow = MagicMock()
    nws.fetch_daily_forecast.side_effect = RuntimeError("NWS down")
    ow.fetch_daily_forecast.side_effect = RuntimeError("OW down")
    engine = _make_engine()

    # Should not raise
    fetch_and_store_forecasts(nws, ow, engine, "NYC_CENTRAL_PARK", 40.78, -73.97)
