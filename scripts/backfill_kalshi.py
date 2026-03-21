"""
Backfill historical Kalshi market data for a given series.

Usage:
  poetry run python scripts/backfill_kalshi.py --series KXHIGHNY

Fetches all settled markets in the series plus their intraday price history,
writing to kalshi_markets and kalshi_prices.
"""
import argparse
import time
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import text

from src.db import get_engine
from src.kalshi_client.client import KalshiClient
from src.monitoring.logger import get_logger

log = get_logger(__name__)

_UPSERT_MARKET = text("""
  INSERT INTO kalshi_markets
    (ticker, series_ticker, event_ticker, title, close_time, yes_settlement)
  VALUES
    (:ticker, :series_ticker, :event_ticker, :title, :close_time, :yes_settlement)
  ON CONFLICT (ticker) DO UPDATE
    SET yes_settlement = EXCLUDED.yes_settlement,
        close_time     = EXCLUDED.close_time
""")

_INSERT_PRICE = text("""
  INSERT INTO kalshi_prices (ticker, yes_price, volume, snapshot_at)
  VALUES (:ticker, :yes_price, :volume, :snapshot_at)
  ON CONFLICT DO NOTHING
""")


def _dollars_to_cents(val: object) -> int:
  if val is None or val == "":
    return 0
  return int(round(Decimal(str(val)) * 100))


def _parse_settlement(market: dict[str, object]) -> bool | None:
  """Parse yes_settlement from a raw market dict (new or old API shape)."""
  result = market.get("result")
  if result == "yes":
    return True
  if result == "no":
    return False
  # Legacy field
  raw = market.get("yes_settlement")
  if raw is not None:
    return bool(raw)
  return None


def _fetch_all_markets(client: KalshiClient, series_ticker: str) -> list[dict[str, object]]:
  """Page through all settled markets for a series via the events endpoint."""
  markets: list[dict[str, object]] = []
  cursor = ""
  while True:
    params: dict[str, object] = {
      "series_ticker": series_ticker,
      "status": "settled",
      "with_nested_markets": "true",
      "limit": 100,
    }
    if cursor:
      params["cursor"] = cursor
    data = client.get("/events", params=params)
    time.sleep(0.05)  # 20 req/sec rate limit

    events: list[dict[str, object]] = data.get("events", [])
    for event in events:
      event_ticker = str(event.get("event_ticker", ""))
      for m in event.get("markets", []):
        m_dict = dict(m)
        # Attach series/event ticker if not already present
        m_dict.setdefault("series_ticker", series_ticker)
        m_dict.setdefault("event_ticker", event_ticker)
        markets.append(m_dict)

    cursor = data.get("cursor", "")
    if not cursor or not events:
      break
  return markets


def _fetch_price_history(
  client: KalshiClient, ticker: str
) -> list[dict[str, object]]:
  data = client.get(f"/markets/{ticker}/history", params={"limit": 1000})
  return data.get("history", [])  # type: ignore[return-value]


def backfill(series_ticker: str) -> None:
  client = KalshiClient()
  engine = get_engine()

  log.info("kalshi_backfill_start", series_ticker=series_ticker)
  markets = _fetch_all_markets(client, series_ticker)
  log.info("kalshi_backfill_markets_fetched", count=len(markets))

  for m in markets:
    # Commit market row first so a failed history fetch doesn't roll it back
    with engine.begin() as conn:
      conn.execute(_UPSERT_MARKET, {
        "ticker": m["ticker"],
        "series_ticker": m.get("series_ticker", series_ticker),
        "event_ticker": m.get("event_ticker", ""),
        "title": m.get("title"),
        "close_time": m.get("close_time"),
        "yes_settlement": _parse_settlement(m),
      })

    try:
      history = _fetch_price_history(client, str(m["ticker"]))
      time.sleep(0.05)  # 20 req/sec rate limit
    except Exception as exc:
      log.warning("kalshi_history_unavailable", ticker=m["ticker"], error=str(exc))
      history = []

    if history:
      with engine.begin() as conn:
        for tick in history:
          ts_ms = tick.get("ts", 0)
          snapshot_at = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc)
          # New API may return yes_price_dollars; old shape uses yes_price (cents)
          yes_price_raw = tick.get("yes_price_dollars")
          if yes_price_raw is not None:
            yes_price = _dollars_to_cents(yes_price_raw)
          else:
            yes_price = int(tick.get("yes_price", 0))
          conn.execute(_INSERT_PRICE, {
            "ticker": m["ticker"],
            "yes_price": yes_price,
            "volume": int(tick.get("volume_fp", tick.get("volume", 0))),
            "snapshot_at": snapshot_at,
          })

    log.info("kalshi_backfill_market_done", ticker=m["ticker"], history=len(history))

  log.info("kalshi_backfill_complete", series_ticker=series_ticker, markets=len(markets))


def main() -> None:
  parser = argparse.ArgumentParser(description="Backfill Kalshi market history")
  parser.add_argument("--series", default="KXHIGHNY", help="Series ticker to backfill")
  args = parser.parse_args()
  backfill(args.series)


if __name__ == "__main__":
  main()
