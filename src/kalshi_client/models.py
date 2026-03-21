"""Pydantic v2 models for Kalshi API responses."""
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


def _dollars_to_cents(val: object) -> int:
  """Convert a dollar string like '0.4200' to integer cents (42)."""
  if val is None or val == "":
    return 0
  return int(round(Decimal(str(val)) * 100))


class Market(BaseModel):
  ticker: str
  event_ticker: str = ""
  title: Optional[str] = None
  # New API: dollar string fields (e.g. "0.4400")
  yes_bid_dollars: Optional[str] = None
  yes_ask_dollars: Optional[str] = None
  last_price_dollars: Optional[str] = None
  volume_fp: Optional[str] = None
  status: str = "open"
  close_time: Optional[datetime] = None
  # Settlement result ("yes" | "no" | None)
  result: Optional[str] = None

  @model_validator(mode="before")
  @classmethod
  def _accept_legacy_cents(cls, data: Any) -> Any:
    """Convert legacy integer-cent fields to dollar strings for backward compat."""
    if not isinstance(data, dict):
      return data
    data = dict(data)  # don't mutate caller's dict
    for old_field, new_field in (
      ("yes_bid", "yes_bid_dollars"),
      ("yes_ask", "yes_ask_dollars"),
      ("last_price", "last_price_dollars"),
    ):
      if old_field in data and new_field not in data:
        cents = data.pop(old_field)
        data[new_field] = f"{int(cents) / 100:.4f}" if cents else None
    if "volume" in data and "volume_fp" not in data:
      data["volume_fp"] = str(data.pop("volume"))
    # series_ticker only appears at the event level in new API; discard silently
    data.pop("series_ticker", None)
    return data

  @property
  def yes_bid(self) -> int:
    return _dollars_to_cents(self.yes_bid_dollars)

  @property
  def yes_ask(self) -> int:
    return _dollars_to_cents(self.yes_ask_dollars)

  @property
  def last_price(self) -> int:
    return _dollars_to_cents(self.last_price_dollars)

  @property
  def volume(self) -> int:
    if self.volume_fp is None:
      return 0
    try:
      return int(self.volume_fp)
    except (ValueError, TypeError):
      return 0

  @property
  def yes_price(self) -> int:
    """Best mid-price; falls back to last traded price."""
    if self.yes_bid and self.yes_ask:
      return (self.yes_bid + self.yes_ask) // 2
    return self.last_price

  @property
  def yes_settlement(self) -> Optional[bool]:
    if self.result == "yes":
      return True
    if self.result == "no":
      return False
    return None


class OrderBook(BaseModel):
  ticker: str
  yes: list[tuple[int, int]] = Field(
    default_factory=list, description="YES bids: (price_cents, size) pairs"
  )
  no: list[tuple[int, int]] = Field(
    default_factory=list, description="NO bids: (price_cents, size) pairs"
  )


class Order(BaseModel):
  model_config = {"populate_by_name": True}

  order_id: str
  ticker: str
  side: str = Field(description="yes | no")
  action: str = Field(default="buy", description="buy | sell")
  order_type: str = Field(alias="type", default="limit", description="limit | market")
  count: int
  yes_price: int = 0
  no_price: int = 0
  status: str
  created_time: Optional[datetime] = None


class Position(BaseModel):
  ticker: str
  # New API: fixed-point string; positive = YES held, negative = NO held
  position_fp: str = "0"
  market_exposure_fp: Optional[str] = None
  realized_pnl_fp: Optional[str] = None
  resting_orders_count: int = 0

  @model_validator(mode="before")
  @classmethod
  def _accept_legacy_position(cls, data: Any) -> Any:
    """Accept integer position= field and convert to position_fp."""
    if not isinstance(data, dict):
      return data
    data = dict(data)  # don't mutate caller's dict
    if "position" in data and "position_fp" not in data:
      data["position_fp"] = str(data.pop("position"))
    return data

  @property
  def position(self) -> int:
    try:
      return int(self.position_fp)
    except (ValueError, TypeError):
      return 0

  @property
  def yes_contracts(self) -> int:
    return max(0, self.position)

  @property
  def no_contracts(self) -> int:
    return max(0, -self.position)


class Portfolio(BaseModel):
  balance_dollars: Optional[str] = None
  balance: int = 0  # cents, populated from balance_dollars if present
  positions: list[Position] = Field(default_factory=list)

  @model_validator(mode="after")
  def _parse_balance(self) -> "Portfolio":
    if self.balance_dollars is not None and self.balance == 0:
      self.balance = _dollars_to_cents(self.balance_dollars)
    return self

  @property
  def available_balance_usd(self) -> float:
    return self.balance / 100.0
