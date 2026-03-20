"""Place and cancel limit orders; monitor for stale order conditions."""
# Phase 4: implement full bodies
from dataclasses import dataclass, field
from datetime import datetime

from src.kalshi_client.client import KalshiClient
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
  placed_at: datetime = field(default_factory=datetime.utcnow)


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
    raise NotImplementedError

  def cancel_stale_orders(
    self,
    ticker: str,
    current_price_cents: int,
    current_model_prob: float,
  ) -> list[str]:
    """Cancel tracked orders for ticker if price or prob drifted too far."""
    raise NotImplementedError

  def cancel_all(self) -> None:
    """Cancel every tracked open order. Used by kill switch."""
    raise NotImplementedError
