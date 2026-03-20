"""Main daemon: poll every 10 min, orchestrate signal -> risk -> order."""
# Phase 4: implement full body
import time

from src.config import settings
from src.monitoring.logger import configure_logging, get_logger

log = get_logger(__name__)


def run_once() -> None:
  """Single poll cycle: fetch data, compute signals, execute orders."""
  raise NotImplementedError


def main() -> None:
  configure_logging(settings.log_level)
  log.info("bot_starting", env=settings.env, paper=settings.paper_trading)
  while True:
    try:
      run_once()
    except Exception:
      log.exception("poll_cycle_error")
    time.sleep(settings.poll_interval_seconds)


if __name__ == "__main__":
  main()
