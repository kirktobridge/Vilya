"""Typed endpoint wrappers for the Kalshi REST API."""
# Phase 1: implement full bodies
from src.kalshi_client.client import KalshiClient
from src.kalshi_client.models import Market, Order, OrderBook, Portfolio


def get_markets(client: KalshiClient, series_ticker: str) -> list[Market]:
  """Return open markets for a given series ticker."""
  raise NotImplementedError


def get_orderbook(client: KalshiClient, ticker: str) -> OrderBook:
  """Return current order book for a market."""
  raise NotImplementedError


def get_portfolio(client: KalshiClient) -> Portfolio:
  """Return current balance and positions."""
  raise NotImplementedError


def place_order(
  client: KalshiClient,
  ticker: str,
  side: str,
  count: int,
  price: int,
) -> Order:
  """Submit a limit order. Returns the created Order."""
  raise NotImplementedError


def cancel_order(client: KalshiClient, order_id: str) -> None:
  """Cancel an open order by ID."""
  raise NotImplementedError


def get_open_orders(client: KalshiClient) -> list[Order]:
  """Return all open orders."""
  raise NotImplementedError
