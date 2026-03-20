"""Pydantic v2 models for Kalshi API responses."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class Market(BaseModel):
  ticker: str
  series_ticker: str
  event_ticker: str
  title: Optional[str] = None
  yes_price: int = Field(description="Current YES price in cents (0-100)")
  volume: int = 0
  status: str = "open"
  close_time: Optional[datetime] = None


class OrderBook(BaseModel):
  ticker: str
  yes_bids: list[tuple[int, int]] = Field(default_factory=list, description="(price, size) pairs")
  yes_asks: list[tuple[int, int]] = Field(default_factory=list, description="(price, size) pairs")


class Order(BaseModel):
  order_id: str
  ticker: str
  side: str = Field(description="yes | no")
  order_type: str = Field(description="limit | market")
  count: int
  price: int = Field(description="Limit price in cents")
  status: str
  created_time: Optional[datetime] = None


class Position(BaseModel):
  ticker: str
  yes_contracts: int = 0
  no_contracts: int = 0
  realized_pnl: float = 0.0
  unrealized_pnl: float = 0.0


class Portfolio(BaseModel):
  available_balance: float = Field(description="Cash available in USD")
  portfolio_value: float = 0.0
  positions: list[Position] = Field(default_factory=list)
