"""Hard risk constraints. Never bypass."""
from dataclasses import dataclass, field
from datetime import date

from src.config import settings
from src.monitoring.logger import get_logger

log = get_logger(__name__)


@dataclass
class RiskState:
  date: date = field(default_factory=date.today)
  daily_notional: float = 0.0
  peak_equity: float = 0.0
  current_equity: float = 0.0
  killed: bool = False  # kill switch engaged

  @property
  def intraday_drawdown(self) -> float:
    return self.peak_equity - self.current_equity


class RiskError(Exception):
  """Raised when a risk constraint blocks an order."""


class RiskManager:
  def __init__(self, state: RiskState | None = None) -> None:
    self.state = state or RiskState()

  def reset_daily(self) -> None:
    """Reset per-day accumulators. Call at midnight or first poll of new day."""
    today = date.today()
    if self.state.date != today:
      log.info("risk_daily_reset", prev_date=str(self.state.date))
      self.state.date = today
      self.state.daily_notional = 0.0

  def check_kill_switch(self) -> None:
    """Raise if intraday drawdown exceeds kill-switch threshold."""
    if self.state.killed:
      raise RiskError("Kill switch already engaged")
    if self.state.intraday_drawdown >= settings.drawdown_kill_switch:
      self.state.killed = True
      log.error(
        "kill_switch_engaged",
        drawdown=self.state.intraday_drawdown,
        limit=settings.drawdown_kill_switch,
      )
      raise RiskError(
        f"Kill switch: drawdown ${self.state.intraday_drawdown:.2f} "
        f">= ${settings.drawdown_kill_switch}"
      )

  def check_order(self, contracts: int, price_cents: int) -> None:
    """Validate a proposed order against all hard risk limits."""
    self.reset_daily()
    self.check_kill_switch()

    if contracts > settings.max_contracts_per_market:
      raise RiskError(
        f"contracts {contracts} > max {settings.max_contracts_per_market}"
      )

    notional = contracts * (price_cents / 100.0)
    if self.state.daily_notional + notional > settings.max_daily_notional:
      raise RiskError(
        f"Daily notional ${self.state.daily_notional + notional:.2f} "
        f"> cap ${settings.max_daily_notional}"
      )

  def record_order(self, contracts: int, price_cents: int) -> None:
    """Update state after a confirmed order placement."""
    self.state.daily_notional += contracts * (price_cents / 100.0)

  def update_equity(self, equity: float) -> None:
    """Update equity tracking; called after each portfolio fetch."""
    if equity > self.state.peak_equity:
      self.state.peak_equity = equity
    self.state.current_equity = equity
