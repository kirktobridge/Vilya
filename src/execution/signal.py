"""Compute edge from model_prob vs market-implied probability."""
from dataclasses import dataclass


@dataclass
class Signal:
  ticker: str
  model_prob: float
  market_implied: float
  edge_buy: float    # model_prob - market_implied
  edge_sell: float   # market_implied - (1 - model_prob)
  action: str        # "buy_yes" | "buy_no" | "skip"


def compute_signal(
  ticker: str,
  model_prob: float,
  yes_price_cents: int,
  ev_threshold: float,
) -> Signal:
  """
  Return a Signal indicating whether to buy YES, buy NO, or skip.

  edge_buy  = model_prob - market_implied  -> buy YES if > threshold
  edge_sell = market_implied - (1 - model_prob) -> buy NO if > threshold
  """
  market_implied = yes_price_cents / 100.0
  edge_buy = model_prob - market_implied
  edge_sell = market_implied - (1.0 - model_prob)

  if edge_buy > ev_threshold:
    action = "buy_yes"
  elif edge_sell > ev_threshold:
    action = "buy_no"
  else:
    action = "skip"

  return Signal(
    ticker=ticker,
    model_prob=model_prob,
    market_implied=market_implied,
    edge_buy=edge_buy,
    edge_sell=edge_sell,
    action=action,
  )
