"""Place and cancel limit orders; monitor for stale order conditions."""
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.kalshi_client.client import KalshiClient
from src.kalshi_client.endpoints import cancel_order, place_order
from src.monitoring.logger import get_logger

log = get_logger(__name__)

_PRICE_DRIFT_CENTS = 5
_PROB_DRIFT_THRESHOLD = 0.10


@dataclass
class TrackedOrder:
  order_id: str
  ticker: str
  side: str
  price_at_placement: int
  prob_at_placement: float
  placed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class OrderManager:
  def __init__(self, client: KalshiClient, paper: bool = True) -> None:
    self._client = client
    self._paper = paper
    self._open: dict[str, TrackedOrder] = {}  # order_id -> TrackedOrder

  def place_limit_order(
    self,
    ticker: str,
    side: str,
    count: int,
    price_cents: int,
    model_prob: float,
  ) -> str | None:
    """Submit a limit order. Returns order_id or None if paper mode."""
    if self._paper:
      log.info(
        "paper_order",
        ticker=ticker, side=side, count=count, price_cents=price_cents,
      )
      return None

    order = place_order(self._client, ticker, side, count, price_cents)
    tracked = TrackedOrder(
      order_id=order.order_id,
      ticker=ticker,
      side=side,
      price_at_placement=price_cents,
      prob_at_placement=model_prob,
    )
    self._open[order.order_id] = tracked
    log.info(
      "order_placed",
      order_id=order.order_id, ticker=ticker, side=side, count=count,
    )
    return order.order_id

  def cancel_stale_orders(
    self,
    ticker: str,
    current_price_cents: int,
    current_model_prob: float,
  ) -> list[str]:
    """Cancel tracked orders for ticker if price or prob drifted too far."""
    cancelled: list[str] = []
    for order_id, tracked in list(self._open.items()):
      if tracked.ticker != ticker:
        continue
      price_drift = abs(current_price_cents - tracked.price_at_placement)
      prob_drift = abs(current_model_prob - tracked.prob_at_placement)
      if price_drift <= _PRICE_DRIFT_CENTS and prob_drift <= _PROB_DRIFT_THRESHOLD:
        continue

      if not self._paper:
        try:
          cancel_order(self._client, order_id)
        except Exception:
          log.exception("cancel_failed", order_id=order_id)
          continue  # leave in _open so we retry next cycle

      del self._open[order_id]
      cancelled.append(order_id)
      log.info(
        "order_cancelled_stale",
        order_id=order_id, price_drift=price_drift, prob_drift=prob_drift,
      )
    return cancelled

  def cancel_all(self) -> None:
    """Cancel every tracked open order. Used by kill switch."""
    for order_id in list(self._open.keys()):
      if not self._paper:
        try:
          cancel_order(self._client, order_id)
        except Exception:
          log.exception("cancel_all_failed", order_id=order_id)
      del self._open[order_id]
    log.warning("cancel_all_done")
