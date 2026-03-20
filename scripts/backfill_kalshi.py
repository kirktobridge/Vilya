"""
Backfill historical Kalshi market data for a given series.

Usage:
  poetry run python scripts/backfill_kalshi.py --series KXHIGHNY

Fetches all settled markets in the series plus their intraday price history,
writing to kalshi_markets and kalshi_prices.
"""
import argparse
from datetime import datetime, timezone

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


def _fetch_all_markets(client: KalshiClient, series_ticker: str) -> list[dict[str, object]]:
  """Page through all settled markets for a series."""
  markets: list[dict[str, object]] = []
  cursor = ""
  while True:
    params: dict[str, object] = {
      "series_ticker": series_ticker, "status": "settled", "limit": 100,
    }
    if cursor:
      params["cursor"] = cursor
    data = client.get("/markets", params=params)
    batch: list[dict[str, object]] = data.get("markets", [])
    markets.extend(batch)
    cursor = data.get("cursor", "")
    if not cursor or len(batch) == 0:
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

  with engine.begin() as conn:
    for m in markets:
      conn.execute(_UPSERT_MARKET, {
        "ticker": m["ticker"],
        "series_ticker": m.get("series_ticker", series_ticker),
        "event_ticker": m.get("event_ticker", ""),
        "title": m.get("title"),
        "close_time": m.get("close_time"),
        "yes_settlement": m.get("yes_settlement"),
      })

      history = _fetch_price_history(client, str(m["ticker"]))
      for tick in history:
        ts_ms = tick.get("ts", 0)
        snapshot_at = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc)
        conn.execute(_INSERT_PRICE, {
          "ticker": m["ticker"],
          "yes_price": tick.get("yes_price"),
          "volume": tick.get("volume", 0),
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
