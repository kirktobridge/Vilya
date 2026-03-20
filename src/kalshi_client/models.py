"""Pydantic v2 models for Kalshi API responses."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class Market(BaseModel):
  ticker: str
  series_ticker: str
  event_ticker: str
  title: Optional[str] = None
  yes_bid: int = 0
  yes_ask: int = 0
  last_price: int = 0
  volume: int = 0
  status: str = "open"
  close_time: Optional[datetime] = None

  @property
  def yes_price(self) -> int:
    """Best mid-price; falls back to last traded price."""
    if self.yes_bid and self.yes_ask:
      return (self.yes_bid + self.yes_ask) // 2
    return self.last_price


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
  position: int = Field(default=0, description="Positive = YES contracts, negative = NO contracts")
  market_exposure: int = Field(default=0, description="Notional exposure in cents")
  realized_pnl: int = Field(default=0, description="Realised P&L in cents")
  resting_orders_count: int = 0

  @property
  def yes_contracts(self) -> int:
    return max(0, self.position)

  @property
  def no_contracts(self) -> int:
    return max(0, -self.position)


class Portfolio(BaseModel):
  balance: int = Field(description="Available cash in cents")
  positions: list[Position] = Field(default_factory=list)

  @property
  def available_balance_usd(self) -> float:
    return self.balance / 100.0
