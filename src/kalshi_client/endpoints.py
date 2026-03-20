"""Typed endpoint wrappers for the Kalshi REST API."""
from src.kalshi_client.client import KalshiClient
from src.kalshi_client.models import Market, Order, OrderBook, Portfolio, Position


def get_markets(client: KalshiClient, series_ticker: str) -> list[Market]:
  """Return all open markets for a series (e.g. KXHIGHNY)."""
  data = client.get("/markets", params={"series_ticker": series_ticker, "status": "open"})
  return [Market.model_validate(m) for m in data.get("markets", [])]


def get_orderbook(client: KalshiClient, ticker: str) -> OrderBook:
  """Return current YES/NO order book for a market."""
  data = client.get(f"/markets/{ticker}/orderbook")
  ob = data.get("orderbook", {})
  return OrderBook(
    ticker=ticker,
    yes=[(int(p), int(s)) for p, s in ob.get("yes", [])],
    no=[(int(p), int(s)) for p, s in ob.get("no", [])],
  )


def get_portfolio(client: KalshiClient) -> Portfolio:
  """Return current balance and open positions (two API calls)."""
  balance_data = client.get("/portfolio/balance")
  positions_data = client.get("/portfolio/positions")
  positions = [Position.model_validate(p) for p in positions_data.get("positions", [])]
  return Portfolio(balance=balance_data.get("balance", 0), positions=positions)


def place_order(
  client: KalshiClient,
  ticker: str,
  side: str,
  count: int,
  price: int,
) -> Order:
  """Submit a limit buy order. price is in cents (0-100)."""
  payload: dict[str, object] = {
    "ticker": ticker,
    "side": side,
    "type": "limit",
    "action": "buy",
    "count": count,
    "yes_price": price if side == "yes" else 100 - price,
    "no_price": price if side == "no" else 100 - price,
  }
  data = client.post("/orders", json=payload)
  return Order.model_validate(data["order"])


def cancel_order(client: KalshiClient, order_id: str) -> None:
  """Cancel an open order by ID."""
  client.delete(f"/orders/{order_id}")


def get_open_orders(client: KalshiClient) -> list[Order]:
  """Return all resting (open) orders."""
  data = client.get("/orders", params={"status": "resting"})
  return [Order.model_validate(o) for o in data.get("orders", [])]
